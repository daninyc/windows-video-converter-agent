import array
import asyncio
import json
import subprocess
from decimal import Decimal

import pytest

from media_converter.common.errors import AppError, ErrorCode
from media_converter.common.process import capture_process
from media_converter.config import AppPaths
from media_converter.jobs.job_service import JobService
from media_converter.jobs.models import JobState
from media_converter.media.importer import ImportService
from media_converter.media.models import ConversionSettings
from media_converter.media.planner import ConversionPlanner
from media_converter.media.probe import ProbeService
from media_converter.media.toolchain import inspect_toolchain
from media_converter.storage.local_store import LocalStore

pytestmark = pytest.mark.integration


async def convert(source, container, folder, *, confirm=True):
    capabilities = inspect_toolchain(AppPaths.from_argument(folder / "data"))
    with LocalStore(folder / "state.sqlite3") as store:
        imported = ImportService(store).import_paths([source])
        asset = await ProbeService(capabilities.ffprobe.path).probe(imported.assets[0])
        settings = ConversionSettings(
            container=container,
            video_encoder="libvpx-vp9" if container == "webm" else "libx264",
            audio_encoder="auto",
            quality_value=32 if container == "webm" else 23,
            output_dir=folder / "out",
        )
        plan = ConversionPlanner(capabilities).plan_one(settings, asset, imported.roots[0])
        if confirm and plan.loss_items:
            plan = plan.confirm(plan.plan_hash)
        jobs = JobService(store, capabilities)
        batch = await jobs.start_batch([plan], "media-edge")
        result = (await jobs.wait(batch))[0]
        return capabilities, plan, result, jobs.validations.get(result.attempt_id)


@pytest.mark.parametrize("container", ["mp4", "mkv", "webm"])
@pytest.mark.parametrize(
    "relative",
    [
        "media/无音频.mp4",
        "media/旋转.mov",
        "media/变帧率.mp4",
        "media/超短.mp4",
        "media/兼容字幕.mp4",
        "media/双音轨 双字幕.mkv",
    ],
)
async def test_media_matrix(relative, container, fixture_root, tmp_path, record_property):
    capabilities, plan, result, checked = await convert(
        fixture_root / relative, container, tmp_path
    )
    assert result.state == JobState.SUCCEEDED, result.error_code
    assert checked["full_decode"] and len(checked["streams"]) == len(plan.stream_mapping)
    if "旋转" in relative:
        assert (checked["width"], checked["height"]) == (90, 160)
    if "无音频" in relative:
        assert not any(stream["codec_type"] == "audio" for stream in checked["streams"])
    if "双音轨" in relative:
        audio = [s for s in checked["streams"] if s["codec_type"] == "audio"]
        assert [s["tags"]["language"] for s in audio] == ["zho", "eng"]
        assert [s["disposition"]["default"] for s in audio] == [1, 0]
    if "变帧率" in relative:
        frames = json.loads(
            await capture_process(
                capabilities.ffprobe.path,
                [
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_frames",
                    "-show_entries",
                    "frame=best_effort_timestamp_time",
                    "-of",
                    "json",
                    result.output_path,
                ],
            )
        )["frames"]
        times = [Decimal(f["best_effort_timestamp_time"]) for f in frames]
        assert len({round(b - a, 3) for a, b in zip(times, times[1:], strict=False)}) > 1
    record_property("output", result.output_path)
    record_property("losses_confirmed", len(plan.loss_items))


async def test_unconfirmed_loss_does_not_create_output(fixture_root, tmp_path):
    _, _, result, _ = await convert(
        fixture_root / "media/双音轨 双字幕.mkv", "mp4", tmp_path, confirm=False
    )
    assert result.state == JobState.FAILED and result.error_code == ErrorCode.CONSENT_REQUIRED
    assert not list((tmp_path / "out").glob("**/*"))


@pytest.mark.parametrize("case", ["multi-video", "hdr"])
async def test_unsupported_real_media_refuses_plan(case, fixture_root, tmp_path):
    capabilities = inspect_toolchain(AppPaths.from_argument(tmp_path / "data"))
    source = tmp_path / (case + ".mkv")
    args = ["-v", "error", "-n", "-i", str(fixture_root / "media/中文 空格/基础.mp4")]
    if case == "multi-video":
        args += ["-map", "0:v", "-map", "0:v", "-c", "copy"]
    else:
        args += [
            "-an",
            "-c:v",
            "copy",
            "-bsf:v",
            "h264_metadata=colour_primaries=9:transfer_characteristics=16:matrix_coefficients=9",
        ]
    await capture_process(capabilities.ffmpeg.path, [*args, str(source)])
    with pytest.raises(AppError) as error:
        await convert(source, "mp4", tmp_path / "conversion")
    assert error.value.info.code == ErrorCode.INCOMPATIBLE_STREAM


@pytest.mark.parametrize("container", ["mp4", "mkv", "webm"])
async def test_synthetic_flash_and_tone_sync(container, tmp_path, record_property):
    capabilities = inspect_toolchain(AppPaths.from_argument(tmp_path / "data"))
    source = tmp_path / "sync.mkv"
    await capture_process(
        capabilities.ffmpeg.path,
        [
            "-v",
            "error",
            "-n",
            "-f",
            "lavfi",
            "-i",
            "color=black:size=160x90:rate=25:duration=1.2,"
            "drawbox=color=white:t=fill:enable=between(t\\,0.5\\,0.58)",
            "-f",
            "lavfi",
            "-i",
            "aevalsrc=if(between(t\\,0.5\\,0.58)\\,0.8*sin(2*PI*1000*t)\\,0):s=48000:d=1.2",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-c:a",
            "pcm_s16le",
            str(source),
        ],
    )
    _, _, result, _ = await convert(source, container, tmp_path / "conversion")
    assert result.state == JobState.SUCCEEDED, result.error_code

    def raw(args):
        return subprocess.run(
            [str(capabilities.ffmpeg.path), "-v", "error", "-i", result.output_path, *args],
            capture_output=True,
            check=True,
            timeout=30,
        ).stdout

    video = await asyncio.to_thread(
        raw, ["-an", "-vf", "scale=1:1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
    )
    sound = array.array(
        "h", await asyncio.to_thread(raw, ["-vn", "-ac", "1", "-ar", "48000", "-f", "s16le", "-"])
    )
    visual_time = (
        next(i for i in range(len(video) // 3) if sum(video[i * 3 : i * 3 + 3]) > 500) / 25
    )
    audio_time = next(i for i, value in enumerate(sound) if abs(value) > 8000) / 48000
    assert abs(visual_time - audio_time) <= 0.1
    record_property("av_marker_offset_ms", round((visual_time - audio_time) * 1000, 3))
