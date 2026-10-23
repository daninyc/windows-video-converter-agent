import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from media_converter.common.context import new_id
from media_converter.common.errors import AppError, ErrorCode
from media_converter.common.process import capture_process
from media_converter.media.models import FileFingerprint


@dataclass(frozen=True)
class ThumbnailResult:
    path: Path | None
    error_code: str | None = None
    cache_hit: bool = False


def thumbnail_key(asset, width=192, height=108):
    payload = {
        "source": str(asset.resolved_path),
        "fingerprint": asset.fingerprint.model_dump(),
        "width": width,
        "height": height,
        "version": 1,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class ThumbnailService:
    def __init__(self, ffmpeg, cache_dir: Path, *, timeout=10):
        self.ffmpeg = ffmpeg
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self._slots = asyncio.Semaphore(2)
        self._inflight = {}

    async def get(self, asset) -> ThumbnailResult:
        try:
            if FileFingerprint.from_path(asset.resolved_path) != asset.fingerprint:
                raise AppError(ErrorCode.FILE_CHANGED)
            key = thumbnail_key(asset)
            cached = self.cache_dir / f"{key}.jpg"
            if cached.is_file():
                with cached.open("rb") as image:
                    valid_header = image.read(2) == b"\xff\xd8"
                if valid_header:
                    return ThumbnailResult(cached, cache_hit=True)
                cached.unlink()
            task = self._inflight.get(key)
            if task is None:
                if len(self._inflight) >= 130:
                    raise AppError(ErrorCode.QUEUE_FULL)
                task = asyncio.create_task(self._generate(asset, cached))
                self._inflight[key] = task
                task.add_done_callback(lambda finished: self._inflight.pop(key, None))
            return await asyncio.shield(task)
        except AppError as error:
            return ThumbnailResult(None, error.info.code)
        except OSError:
            return ThumbnailResult(None, ErrorCode.PROCESS_FAILED)

    async def _generate(self, asset, cached):
        temporary = self.cache_dir / f"{new_id()}.jpg"
        try:
            async with asyncio.timeout(30):
                async with self._slots:
                    seek = min((asset.duration_us or 0) / 3_000_000, 10)
                    for position in dict.fromkeys([seek, 0]):
                        try:
                            await capture_process(
                                self.ffmpeg,
                                [
                                    "-hide_banner",
                                    "-loglevel",
                                    "error",
                                    "-nostdin",
                                    "-n",
                                    "-ss",
                                    str(position),
                                    "-i",
                                    str(asset.resolved_path),
                                    "-map",
                                    "0:"
                                    + str(
                                        next(
                                            (
                                                stream.stream_index
                                                for stream in asset.streams
                                                if stream.kind == "video"
                                                and not stream.attached_picture
                                            ),
                                            0,
                                        )
                                    ),
                                    "-frames:v",
                                    "1",
                                    "-vf",
                                    "scale=192:108:force_original_aspect_ratio=decrease",
                                    str(temporary),
                                ],
                                timeout=self.timeout,
                            )
                            if temporary.is_file() and temporary.stat().st_size > 0:
                                break
                        except AppError:
                            pass
                        temporary.unlink(missing_ok=True)
                    if not temporary.exists():
                        return ThumbnailResult(None, ErrorCode.PROCESS_FAILED)
            if FileFingerprint.from_path(asset.resolved_path) != asset.fingerprint:
                return ThumbnailResult(None, ErrorCode.FILE_CHANGED)
            try:
                cached.hardlink_to(temporary)
            except FileExistsError:
                pass
            self._prune(cached)
            return ThumbnailResult(cached)
        except (AppError, OSError, TimeoutError) as error:
            return ThumbnailResult(
                None,
                error.info.code
                if isinstance(error, AppError)
                else ErrorCode.TIMEOUT
                if isinstance(error, TimeoutError)
                else ErrorCode.PROCESS_FAILED,
            )
        finally:
            temporary.unlink(missing_ok=True)

    def _prune(self, keep):
        files = sorted(
            self.cache_dir.glob("?" * 64 + ".jpg"), key=lambda file: file.stat().st_mtime_ns
        )
        size = sum(file.stat().st_size for file in files)
        while files and (len(files) > 200 or size > 128 * 1024 * 1024):
            file = files.pop(0)
            if file != keep:
                size -= file.stat().st_size
                file.unlink(missing_ok=True)
