import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from pydantic import ValidationError

from media_converter.common.errors import AppError, ErrorCode
from media_converter.config import AppPaths, application_root
from media_converter.media.models import FileFingerprint, FrozenModel

REQUIRED_ENCODERS = frozenset({"libx264", "aac", "libvpx-vp9", "libopus"})
REQUIRED_MUXERS = frozenset({"mp4", "matroska", "webm"})


class BinaryIdentity(FrozenModel):
    path: Path
    fingerprint: FileFingerprint
    sha256: str


def identify_binary(path: Path) -> BinaryIdentity:
    try:
        with path.open("rb") as file:
            digest = hashlib.file_digest(file, "sha256").hexdigest()
        return BinaryIdentity(
            path=path.resolve(), fingerprint=FileFingerprint.from_path(path), sha256=digest
        )
    except OSError as error:
        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE) from error


class CapabilitySnapshot(FrozenModel):
    schema_version: int = 1
    ffmpeg: BinaryIdentity
    ffprobe: BinaryIdentity
    ffmpeg_version: str
    ffprobe_version: str
    encoders: tuple[str, ...]
    muxers: tuple[str, ...]

    @property
    def missing_encoders(self) -> tuple[str, ...]:
        return tuple(sorted(REQUIRED_ENCODERS - set(self.encoders)))

    @property
    def missing_muxers(self) -> tuple[str, ...]:
        return tuple(sorted(REQUIRED_MUXERS - set(self.muxers)))

    @property
    def ready(self) -> bool:
        return not self.missing_encoders and not self.missing_muxers

    def require_ready(self):
        if not self.ready:
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)


def parse_encoders(output: str) -> tuple[str, ...]:
    return tuple(sorted(set(re.findall(r"^\s*[VAS][A-Z.]{5}\s+(\S+)", output, re.M))))


def parse_muxers(output: str) -> tuple[str, ...]:
    names = re.findall(r"^\s*E\s+(\S+)", output, re.M)
    return tuple(sorted({name for combined in names for name in combined.split(",")}))


def run_tool(binary: Path, arguments: list[str], *, timeout: float = 15) -> str:
    try:
        result = subprocess.run(
            [str(binary), *arguments],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as error:
        raise AppError(ErrorCode.TIMEOUT) from error
    except OSError as error:
        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE) from error
    if result.returncode != 0:
        raise AppError(ErrorCode.PROCESS_FAILED)
    return result.stdout


def locate_binaries(
    paths: AppPaths, *, ffmpeg: Path | None = None, ffprobe: Path | None = None
) -> tuple[Path, Path]:
    configuration = paths.data_dir / "toolchain.json"
    configured = {}
    if configuration.exists():
        try:
            configured = json.loads(configuration.read_text("utf-8"))
            if not isinstance(configured, dict):
                raise ValueError("invalid toolchain config")
            if any(
                key not in {"ffmpeg", "ffprobe"} or not isinstance(value, str) or not value
                for key, value in configured.items()
            ):
                raise ValueError("invalid binary path")
        except (OSError, ValueError) as error:
            raise AppError(ErrorCode.INVALID_ARGUMENT) from error
    selected = []
    for name, explicit in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)):
        configured_path = explicit or configured.get(name)
        if configured_path:
            path = Path(configured_path)
            if not path.is_absolute():
                path = application_root() / path
            if not path.is_file():
                raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
        else:
            filename = name + (".exe" if os.name == "nt" else "")
            candidates = [application_root() / "bin" / filename]
            if (application_root() / "environment").is_dir():
                candidates += sorted(Path("D:/ffmpeg_ffprobe").glob(f"*/bin/{filename}"))
            path = next((p for p in candidates if p.is_file()), None)
            if path is None:
                discovered = shutil.which(name)
                if discovered is None:
                    raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
                path = Path(discovered)
        selected.append(path.resolve())
    return selected[0], selected[1]


def inspect_toolchain(
    paths: AppPaths,
    *,
    ffmpeg: Path | None = None,
    ffprobe: Path | None = None,
    use_cache: bool = True,
) -> CapabilitySnapshot:
    encoder, probe = locate_binaries(paths, ffmpeg=ffmpeg, ffprobe=ffprobe)
    encoder_id, probe_id = identify_binary(encoder), identify_binary(probe)
    cache = paths.data_dir / "toolchain-capabilities.json"
    if use_cache and cache.is_file():
        try:
            snapshot = CapabilitySnapshot.model_validate_json(cache.read_text("utf-8"))
            if (
                snapshot.schema_version == 1
                and snapshot.ffmpeg == encoder_id
                and snapshot.ffprobe == probe_id
            ):
                return snapshot
        except (OSError, ValueError, ValidationError):
            pass
    snapshot = CapabilitySnapshot(
        ffmpeg=encoder_id,
        ffprobe=probe_id,
        ffmpeg_version=run_tool(encoder, ["-hide_banner", "-version"]).splitlines()[0],
        ffprobe_version=run_tool(probe, ["-hide_banner", "-version"]).splitlines()[0],
        encoders=parse_encoders(run_tool(encoder, ["-hide_banner", "-encoders"])),
        muxers=parse_muxers(run_tool(encoder, ["-hide_banner", "-muxers"])),
    )
    paths.ensure()
    cache.write_text(snapshot.model_dump_json(indent=2), "utf-8")
    return snapshot


async def inspect_toolchain_async(paths: AppPaths, **kwargs) -> CapabilitySnapshot:
    return await asyncio.to_thread(inspect_toolchain, paths, **kwargs)
