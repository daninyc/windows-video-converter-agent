import asyncio

import pytest
from PySide6.QtGui import QImage

from media_converter.config import AppPaths
from media_converter.media.models import FileFingerprint, MediaAsset
from media_converter.media.probe import ProbeService
from media_converter.media.thumbnail import ThumbnailService
from media_converter.media.toolchain import inspect_toolchain
from tests.fixture_support import load_fixture_manifest

pytestmark = pytest.mark.integration


def asset_for(root, relative):
    path = root / relative
    return MediaAsset(
        root_id="fixtures",
        relative_path=relative,
        resolved_path=path,
        fingerprint=FileFingerprint.from_path(path),
    )


async def test_probe_real_manifest_and_broken_file(fixture_root, tmp_path):
    snapshot = inspect_toolchain(AppPaths.from_argument(tmp_path))
    service = ProbeService(snapshot.ffprobe.path)
    manifest = load_fixture_manifest(fixture_root)
    cases = [item for item in manifest["files"] if item["kind"] == "media"]
    results = await asyncio.gather(
        *(service.probe(asset_for(fixture_root, item["path"])) for item in cases)
    )
    for item, result in zip(cases, results, strict=True):
        if item["expected"].get("probe_error"):
            assert result.probe_status == "failed"
        else:
            assert result.probe_status == "succeeded"
            assert [stream.codec for stream in result.streams] == item["expected"]["codecs"]
            assert result.duration_us == item["observed"]["duration_us"]
    assert next(asset for asset in results if "旋转" in asset.relative_path).rotation_deg == 90


async def test_thumbnail_real_short_rotated_and_placeholder(fixture_root, tmp_path):
    snapshot = inspect_toolchain(AppPaths.from_argument(tmp_path))
    probe = ProbeService(snapshot.ffprobe.path)
    thumbnails = ThumbnailService(snapshot.ffmpeg.path, tmp_path / "thumbnails")
    for relative in ["media/超短.mp4", "media/旋转.mov", "media/中文 空格/基础.mp4"]:
        asset = await probe.probe(asset_for(fixture_root, relative))
        result = await thumbnails.get(asset)
        assert result.path and not QImage(str(result.path)).isNull()
        image = QImage(str(result.path))
        if "旋转" in relative:
            assert image.height() > image.width()
    result = await thumbnails.get(asset_for(fixture_root, "media/损坏.mp4"))
    assert result.path is None and result.error_code


async def test_probe_changed_corrupt_file_clears_old_metadata(fixture_root, tmp_path):
    target = tmp_path / "changed.mp4"
    target.write_bytes((fixture_root / "media/中文 空格/基础.mp4").read_bytes())
    asset = asset_for(tmp_path, "changed.mp4")
    service = ProbeService(
        inspect_toolchain(AppPaths.from_argument(tmp_path / "data")).ffprobe.path
    )
    original = await service.probe(asset)
    assert original.width == 160
    target.write_bytes(b"corrupt replacement")
    changed = await service.probe(original)
    assert changed.probe_status == "failed" and changed.width is None and not changed.streams
