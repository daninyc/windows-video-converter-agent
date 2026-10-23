import pytest

from media_converter.config import AppPaths
from media_converter.media.toolchain import inspect_toolchain

pytestmark = pytest.mark.integration


def test_real_binaries_with_isolated_path(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    snapshot = inspect_toolchain(AppPaths.from_argument(tmp_path))
    snapshot.require_ready()
    assert "ffmpeg version" in snapshot.ffmpeg_version
    assert "ffprobe version" in snapshot.ffprobe_version
    assert snapshot.ffmpeg.path.is_absolute()
    assert snapshot.ffprobe.path.is_absolute()
    assert len(snapshot.ffmpeg.sha256) == 64
