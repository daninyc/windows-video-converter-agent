from pathlib import Path

import pytest

from media_converter.common.errors import AppError
from media_converter.config import AppPaths
from media_converter.media.toolchain import (
    CapabilitySnapshot,
    identify_binary,
    inspect_toolchain,
    locate_binaries,
    parse_encoders,
    parse_muxers,
)

pytestmark = pytest.mark.unit


def test_parsing_and_missing_encoder_report(tmp_path):
    path = tmp_path / "binary"
    path.write_bytes(b"v1")
    identity = identify_binary(path)
    snapshot = CapabilitySnapshot(
        ffmpeg=identity,
        ffprobe=identity,
        ffmpeg_version="test",
        ffprobe_version="test",
        encoders=parse_encoders(" V..... libx264 desc\n A..... aac desc\n A..... libopus desc"),
        muxers=parse_muxers(" E mp4 desc\n E matroska,webm desc"),
    )
    assert snapshot.missing_encoders == ("libvpx-vp9",)
    assert not snapshot.missing_muxers and not snapshot.ready
    with pytest.raises(AppError):
        snapshot.require_ready()


def test_explicit_missing_binary_does_not_fallback(tmp_path):
    with pytest.raises(AppError):
        locate_binaries(AppPaths.from_argument(tmp_path), ffmpeg=Path("missing.exe"))


def test_invalid_development_config_is_a_typed_error(tmp_path):
    (tmp_path / "toolchain.json").write_text('{"ffmpeg": 12}', "utf-8")
    with pytest.raises(AppError) as failure:
        locate_binaries(AppPaths.from_argument(tmp_path))
    assert failure.value.info.code == "INVALID_ARGUMENT"


def test_cache_invalidates_when_binary_changes(tmp_path, monkeypatch):
    import media_converter.media.toolchain as module

    binary = tmp_path / "fake-binary"
    binary.write_bytes(b"version1")
    calls = []

    def run(path, args):
        calls.append(args)
        return "version1\n" if "-version" in args else " V..... libx264\n E mp4\n"

    monkeypatch.setattr(module, "run_tool", run)
    paths = AppPaths.from_argument(tmp_path / "data")
    first = inspect_toolchain(paths, ffmpeg=binary, ffprobe=binary)
    assert len(calls) == 4
    assert inspect_toolchain(paths, ffmpeg=binary, ffprobe=binary) == first
    assert len(calls) == 4
    binary.write_bytes(b"version2")
    updated = inspect_toolchain(paths, ffmpeg=binary, ffprobe=binary)
    assert len(calls) == 8 and updated.ffmpeg.sha256 != first.ffmpeg.sha256
