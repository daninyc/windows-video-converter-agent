import asyncio

import pytest

from media_converter.media.models import FileFingerprint
from media_converter.media.thumbnail import ThumbnailResult, ThumbnailService, thumbnail_key
from tests.unit.test_conversion_models import make_asset

pytestmark = pytest.mark.unit


async def test_cache_identity_inflight_merge_and_cancelled_subscriber(tmp_path, monkeypatch):
    asset = make_asset(tmp_path)
    service = ThumbnailService(None, tmp_path / "cache")
    calls = []

    async def generate(asset, cached):
        calls.append(1)
        await asyncio.sleep(0.03)
        cached.write_bytes(b"\xff\xd8image")
        return ThumbnailResult(cached)

    monkeypatch.setattr(service, "_generate", generate)
    first = asyncio.create_task(service.get(asset))
    second = asyncio.create_task(service.get(asset))
    await asyncio.sleep(0.005)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert (await second).path and len(calls) == 1
    assert (await service.get(asset)).cache_hit
    old_key = thumbnail_key(asset)
    asset.resolved_path.write_bytes(b"new source")
    assert (await service.get(asset)).error_code == "FILE_CHANGED"
    changed = asset.model_copy(
        update={"fingerprint": FileFingerprint.from_path(asset.resolved_path)}
    )
    assert thumbnail_key(changed) != old_key


async def test_representative_frame_failure_falls_back_to_start(tmp_path, monkeypatch):
    import media_converter.media.thumbnail as module
    from media_converter.common.errors import AppError, ErrorCode

    asset = make_asset(tmp_path).model_copy(update={"duration_us": 40_000})
    positions = []

    async def capture(binary, arguments, **kwargs):
        from pathlib import Path

        positions.append(arguments[arguments.index("-ss") + 1])
        if len(positions) == 1:
            raise AppError(ErrorCode.PROCESS_FAILED)
        Path(arguments[-1]).write_bytes(b"\xff\xd8test-image")
        return b""

    monkeypatch.setattr(module, "capture_process", capture)
    result = await ThumbnailService(None, tmp_path / "cache").get(asset)
    assert result.path is not None and len(positions) == 2 and positions[-1] == "0"
