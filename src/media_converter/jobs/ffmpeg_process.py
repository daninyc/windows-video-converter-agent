import asyncio
import hashlib
import json
import math
import os
from dataclasses import dataclass
from datetime import UTC, datetime

from media_converter.common.context import CallContext
from media_converter.common.errors import AppError, ErrorCode
from media_converter.common.logging import JsonlLogger, summary
from media_converter.common.process import terminate_owned


@dataclass(frozen=True)
class Progress:
    processed_us: int | None
    speed: float | None
    ended: bool

    def percentage(self, duration_us):
        if not duration_us or self.processed_us is None:
            return None
        return min(99, max(0, round(self.processed_us * 100 / duration_us)))


class ProgressParser:
    def __init__(self):
        self.buffer = b""
        self.fields = {}
        self.processed_us = None

    def feed(self, chunk: bytes):
        self.buffer += chunk
        events = []
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            key, _, value = line.decode("ascii", "replace").strip().partition("=")
            self.fields[key] = value
            if key == "progress":
                raw = self.fields.get("out_time_us", self.fields.get("out_time_ms"))
                try:
                    processed = max(0, int(raw))
                    self.processed_us = max(self.processed_us or 0, processed)
                except (ValueError, TypeError):
                    pass
                try:
                    speed = float(self.fields.get("speed", "").rstrip("x"))
                    if not math.isfinite(speed) or speed < 0:
                        speed = None
                except ValueError:
                    speed = None
                events.append(Progress(self.processed_us, speed, value == "end"))
                self.fields.clear()
        if len(self.buffer) > 8192:
            raise AppError(ErrorCode.PROTOCOL_MISMATCH)
        return events


@dataclass(frozen=True)
class ProcessEvidence:
    pid: int
    started_at: str
    argument_hash: str
    binary_sha256: str


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int
    cancelled: bool
    progress_end: bool
    evidence: ProcessEvidence
    stderr_summary: dict
    error_code: str | None = None


class FFmpegProcess:
    def __init__(self, capabilities, logger=None):
        self.capabilities = capabilities
        self.logger = logger or JsonlLogger()
        self.active_count = 0
        self.peak_active = 0
        self.evidence = []

    async def run(self, plan, cancel_event, on_progress=None, *, context=None):
        if self.active_count:
            raise AppError(ErrorCode.INVALID_STATE)
        if not plan.consent_satisfied:
            raise AppError(ErrorCode.CONSENT_REQUIRED)
        if plan.temporary_path.exists():
            raise AppError(ErrorCode.ACCESS_DENIED)
        context = context or CallContext()
        try:
            process = await asyncio.create_subprocess_exec(
                str(self.capabilities.ffmpeg.path),
                *plan.ffmpeg_args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=0x08000000 if os.name == "nt" else 0,
            )
        except OSError as error:
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE) from error
        evidence = ProcessEvidence(
            process.pid,
            datetime.now(UTC).isoformat(),
            hashlib.sha256(json.dumps(plan.ffmpeg_args).encode()).hexdigest(),
            self.capabilities.ffmpeg.sha256,
        )
        self.evidence.append(evidence)
        self.active_count += 1
        self.peak_active = max(self.peak_active, self.active_count)
        self.logger.event(
            "conversion.process_started",
            context,
            pid=process.pid,
            argument_hash=evidence.argument_hash,
            binary_sha256=evidence.binary_sha256,
            started_at=evidence.started_at,
            attempt_id=plan.attempt_id,
        )
        parser = ProgressParser()
        stderr = bytearray()
        ended = False

        async def stdout_reader():
            nonlocal ended
            while chunk := await process.stdout.read(4096):
                for progress in parser.feed(chunk):
                    ended = ended or progress.ended
                    if on_progress:
                        on_progress(progress)

        async def stderr_reader():
            while chunk := await process.stderr.read(8192):
                stderr.extend(chunk)
                del stderr[:-65536]

        readers = [asyncio.create_task(stdout_reader()), asyncio.create_task(stderr_reader())]
        waiting = asyncio.create_task(process.wait())
        cancelling = asyncio.create_task(cancel_event.wait())
        try:
            await asyncio.wait([waiting, cancelling], return_when=asyncio.FIRST_COMPLETED)
            cancelled = cancel_event.is_set()
            if cancelled and process.returncode is None:
                try:
                    process.stdin.write(b"q\n")
                    await process.stdin.drain()
                    await asyncio.wait_for(asyncio.shield(waiting), 2)
                except (BrokenPipeError, ConnectionError, TimeoutError):
                    await terminate_owned(process)
            code = await waiting
            await asyncio.gather(*readers)
            cancelled = cancelled or cancel_event.is_set()
            diagnostic = summary(stderr.decode("utf-8", "replace"))
            error_code = (
                ErrorCode.DISK_FULL
                if b"No space left" in stderr
                else ErrorCode.ACCESS_DENIED
                if b"Permission denied" in stderr
                else ErrorCode.PROCESS_FAILED
                if code
                else None
            )
            self.logger.event(
                "conversion.process_exited",
                context,
                pid=process.pid,
                exit_code=code,
                error_code=error_code,
                stderr=diagnostic,
            )
            return ProcessResult(code, cancelled, ended, evidence, diagnostic, error_code)
        finally:
            if process.returncode is None:
                await terminate_owned(process)
            for task in [*readers, waiting, cancelling]:
                task.cancel()
            await asyncio.gather(*readers, waiting, cancelling, return_exceptions=True)
            if process.stdin:
                process.stdin.close()
            self.active_count -= 1
