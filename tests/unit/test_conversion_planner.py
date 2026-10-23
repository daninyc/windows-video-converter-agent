import pytest

from media_converter.config import AppPaths
from media_converter.media.models import ConversionSettings, ImportRoot, StreamInfo
from media_converter.media.planner import ConversionPlanner
from media_converter.media.toolchain import inspect_toolchain
from tests.fixture_support import probed_fixture

pytestmark = pytest.mark.unit


def make_plan(fixture_root, tmp_path, container="mkv", relative="media/双音轨 双字幕.mkv"):
    asset = probed_fixture(fixture_root, relative)
    snapshot = inspect_toolchain(AppPaths.from_argument(tmp_path / "data"))
    settings = ConversionSettings(
        container=container,
        video_encoder="libvpx-vp9" if container == "webm" else "libx264",
        audio_encoder="libopus" if container == "webm" else "aac",
        quality_value=32 if container == "webm" else 23,
        output_dir=tmp_path / "outputs",
    )
    root = ImportRoot(root_id=asset.root_id, resolved_path=fixture_root, display_group="fixtures")
    return ConversionPlanner(snapshot).plan_one(settings, asset, root)


def test_all_tracks_explicit_and_loss_consent_bound_to_plan(fixture_root, tmp_path):
    mkv = make_plan(fixture_root, tmp_path)
    assert [stream.source_index for stream in mkv.stream_mapping] == [0, 1, 2, 3, 4]
    assert not mkv.loss_items and mkv.consent_satisfied
    assert mkv.ffmpeg_args.count("-map") == 5
    assert "language=zho" in mkv.ffmpeg_args and "language=eng" in mkv.ffmpeg_args
    mp4 = make_plan(fixture_root, tmp_path, "mp4")
    assert [loss.stream_index for loss in mp4.loss_items] == [3, 4]
    assert not mp4.consent_satisfied and mp4.confirm(mp4.plan_hash).consent_satisfied
    webm = make_plan(fixture_root, tmp_path, "webm")
    assert sum(mapping.kind == "audio" for mapping in webm.stream_mapping) == 2
    assert all(
        mapping.encoder == "libopus" for mapping in webm.stream_mapping if mapping.kind == "audio"
    )


def test_multiple_main_video_rejected(fixture_root, tmp_path):
    from media_converter.common.errors import AppError

    plan = make_plan(fixture_root, tmp_path)
    asset = plan.source_asset.model_copy(
        update={
            "streams": (
                *plan.source_asset.streams,
                StreamInfo(stream_index=8, kind="video", codec="h264"),
            )
        }
    )
    snapshot = inspect_toolchain(AppPaths.from_argument(tmp_path / "data"))
    with pytest.raises(AppError):
        ConversionPlanner(snapshot).plan_one(
            plan.settings_snapshot,
            asset,
            ImportRoot(root_id=asset.root_id, resolved_path=fixture_root, display_group="fixtures"),
        )
