import asyncio

import pytest

from media_converter.config import AppPaths
from media_converter.jobs.ffmpeg_process import FFmpegProcess
from media_converter.jobs.output_commit import OutputLease
from media_converter.jobs.output_validator import OutputValidator
from media_converter.media.toolchain import inspect_toolchain
from tests.unit.test_conversion_planner import make_plan

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("container", ["mp4", "mkv", "webm"])
async def test_process_real_three_targets_tracks_and_validation(container, fixture_root, tmp_path):
    plan = make_plan(fixture_root, tmp_path, container)
    if plan.loss_items:
        plan = plan.confirm(plan.plan_hash)
    snapshot = inspect_toolchain(AppPaths.from_argument(tmp_path / "data"))
    lease = OutputLease(plan)
    lease.acquire()
    try:
        events = []
        result = await FFmpegProcess(snapshot).run(plan, asyncio.Event(), events.append)
        assert result.exit_code == 0 and not result.cancelled and result.evidence.pid > 0
        assert events and result.progress_end
        checked = await OutputValidator(snapshot).validate(plan)
        assert checked["full_decode"]
        final = lease.commit()
        assert final.is_file() and final.stat().st_size > 0
    finally:
        lease.cleanup()


async def test_batch_real_sequential_and_persisted(fixture_root, tmp_path, record_property):
    from media_converter.jobs.job_service import JobService
    from media_converter.jobs.models import JobState
    from media_converter.storage.local_store import LocalStore

    plans = [
        make_plan(fixture_root, tmp_path, relative=relative)
        for relative in ["media/中文 空格/基础.mp4", "media/无音频.mp4"]
    ]
    snapshot = inspect_toolchain(AppPaths.from_argument(tmp_path / "data"))
    with LocalStore(tmp_path / "state.sqlite3") as store:
        service = JobService(store, snapshot)
        batch = await service.start_batch(plans, "real-batch")
        results = await service.wait(batch)
        assert all(item.state == JobState.SUCCEEDED for item in results)
        assert service.processor.peak_active == 1 and len(service.processor.evidence) == 2
        assert all(store.get_attempt(item.attempt_id) == item for item in results)
        record_property("ffmpeg_peak_concurrency", service.processor.peak_active)


@pytest.mark.parametrize("whole_batch", [False, True])
async def test_cancel_real_process_and_retry_is_new_attempt(whole_batch, fixture_root, tmp_path):
    from media_converter.jobs.job_service import JobService
    from media_converter.jobs.models import JobState
    from media_converter.media.models import ConversionPlan, ImportRoot
    from media_converter.storage.local_store import LocalStore

    original = make_plan(fixture_root, tmp_path, relative="media/中文 空格/基础.mp4")
    args = list(original.ffmpeg_args)
    position = args.index("-i")
    args[position:position] = ["-readrate", "0.2"]
    data = original.model_dump()
    data.update(ffmpeg_args=tuple(args), plan_hash="")
    first = ConversionPlan.model_validate(data)
    second = make_plan(fixture_root, tmp_path, relative="media/无音频.mp4")
    cancelled = []
    with LocalStore(tmp_path / "state.sqlite3") as store:
        root = ImportRoot(
            root_id=first.source_asset.root_id, resolved_path=fixture_root, display_group="fixtures"
        )
        store.save_import_root(root)
        store.save_asset(first.source_asset)
        service = JobService(store, inspect_toolchain(AppPaths.from_argument(tmp_path / "data")))

        def event(event):
            if (
                event.kind == "progress"
                and event.attempt.attempt_id == first.attempt_id
                and not cancelled
            ):
                cancelled.append(True)
                asyncio.create_task(
                    service.cancel_batch(event.batch_id)
                    if whole_batch
                    else service.cancel_current(event.batch_id)
                )

        service.on_event = event
        batch = await service.start_batch([first, second], "cancel-real")
        results = await service.wait(batch)
        assert cancelled and results[0].state == JobState.CANCELLED
        assert results[1].state == (JobState.CANCELLED if whole_batch else JobState.SUCCEEDED)
        assert not first.temporary_path.parent.exists() and not first.final_path.exists()
        retried = await service.prepare_retry(first.attempt_id)
        assert retried.attempt_id != first.attempt_id
        retry_batch = await service.retry(first.attempt_id, retried)
        assert await service.retry(first.attempt_id, retried) == retry_batch
        attempt = (await service.wait(retry_batch))[0]
        assert attempt.state == JobState.SUCCEEDED and attempt.job_id == results[0].job_id
        assert store.get_attempt(first.attempt_id).state == JobState.CANCELLED


@pytest.mark.parametrize(
    "relative", ["media/中文 空格/基础.mp4", "media/基础.mov", "media/基础.avi", "media/基础.webm"]
)
@pytest.mark.parametrize("container", ["mp4", "mkv", "webm"])
async def test_batch_five_input_formats_across_targets(relative, container, fixture_root, tmp_path):
    from media_converter.jobs.job_service import JobService
    from media_converter.jobs.models import JobState
    from media_converter.storage.local_store import LocalStore

    plan = make_plan(fixture_root, tmp_path, container, relative)
    with LocalStore(tmp_path / "state.sqlite3") as store:
        service = JobService(store, inspect_toolchain(AppPaths.from_argument(tmp_path / "data")))
        batch = await service.start_batch([plan], "format-matrix")
        result = (await service.wait(batch))[0]
        assert result.state == JobState.SUCCEEDED, result.error_code


@pytest.mark.parametrize(
    "relative", ["media/旋转.mov", "media/变帧率.mp4", "media/超短.mp4", "media/兼容字幕.mp4"]
)
async def test_batch_rotation_vfr_short_and_compatible_subtitle(relative, fixture_root, tmp_path):
    import json
    from decimal import Decimal

    from media_converter.common.process import capture_process
    from media_converter.jobs.job_service import JobService
    from media_converter.jobs.models import JobState
    from media_converter.storage.local_store import LocalStore

    plan = make_plan(fixture_root, tmp_path, "mp4", relative)
    snapshot = inspect_toolchain(AppPaths.from_argument(tmp_path / "data"))
    with LocalStore(tmp_path / "state.sqlite3") as store:
        service = JobService(store, snapshot)
        batch = await service.start_batch([plan], "edge-media")
        result = (await service.wait(batch))[0]
        assert result.state == JobState.SUCCEEDED, result.error_code
        if "变帧率" in relative:
            frames = json.loads(
                await capture_process(
                    snapshot.ffprobe.path,
                    [
                        "-v",
                        "error",
                        "-select_streams",
                        "v",
                        "-show_frames",
                        "-show_entries",
                        "frame=best_effort_timestamp_time",
                        "-of",
                        "json",
                        result.output_path,
                    ],
                )
            )["frames"]
            times = [Decimal(frame["best_effort_timestamp_time"]) for frame in frames]
            assert len({round(b - a, 3) for a, b in zip(times, times[1:], strict=False)}) > 1


@pytest.mark.parametrize("container", ["mp4", "mkv", "webm"])
async def test_batch_advanced_bitrate_fps_and_aspect_ratio(container, fixture_root, tmp_path):
    from media_converter.jobs.job_service import JobService
    from media_converter.jobs.models import JobState
    from media_converter.media.models import ConversionSettings, FrameRate, ImportRoot, Resolution
    from media_converter.media.planner import ConversionPlanner
    from media_converter.storage.local_store import LocalStore

    previous = make_plan(fixture_root, tmp_path, container, "media/中文 空格/基础.mp4")
    data = previous.settings_snapshot.model_dump()
    data.update(
        quality_mode="bitrate",
        quality_value=None,
        video_bitrate_bps=200_000,
        frame_rate=FrameRate(numerator=30000, denominator=1001),
        resolution=Resolution(width=80, height=80),
    )
    settings = ConversionSettings.model_validate(data)
    snapshot = inspect_toolchain(AppPaths.from_argument(tmp_path / "data"))
    plan = ConversionPlanner(snapshot).plan_one(
        settings,
        previous.source_asset,
        ImportRoot(
            root_id=previous.source_asset.root_id,
            resolved_path=fixture_root,
            display_group="fixtures",
        ),
    )
    with LocalStore(tmp_path / "state.sqlite3") as store:
        service = JobService(store, snapshot)
        batch = await service.start_batch([plan], "advanced-settings")
        result = (await service.wait(batch))[0]
        assert result.state == JobState.SUCCEEDED, result.error_code
        validation = service.validations[result.attempt_id]
        assert validation["width"] == 80 and validation["height"] == 46


async def test_retry_changed_source_requires_new_probe_and_new_consent(fixture_root, tmp_path):
    import os

    from media_converter.jobs.job_service import JobService
    from media_converter.jobs.models import JobAttempt, JobState
    from media_converter.jobs.state_machine import transition
    from media_converter.media.importer import ImportService
    from media_converter.media.models import ConversionSettings
    from media_converter.media.planner import ConversionPlanner
    from media_converter.media.probe import ProbeService
    from media_converter.storage.local_store import LocalStore

    source = tmp_path / "source.mkv"
    source.write_bytes((fixture_root / "media/双音轨 双字幕.mkv").read_bytes())
    snapshot = inspect_toolchain(AppPaths.from_argument(tmp_path / "data"))
    with LocalStore(tmp_path / "state.sqlite3") as store:
        imported = ImportService(store).import_paths([source])
        asset = await ProbeService(snapshot.ffprobe.path, store).probe(imported.assets[0])
        plan = ConversionPlanner(snapshot).plan_one(
            ConversionSettings(output_dir=tmp_path / "out"), asset, imported.roots[0]
        )
        plan = plan.confirm(plan.plan_hash)
        attempt = JobAttempt(
            attempt_id=plan.attempt_id,
            batch_id="old-batch",
            asset_id=plan.asset_id,
            plan_id=plan.plan_id,
        )
        store.register_batch("old-command", "old-batch", (plan,), (attempt,))
        store.save_attempt(transition(attempt, JobState.FAILED))
        stat = source.stat()
        os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
        service = JobService(store, snapshot)
        new_plan = await service.prepare_retry(attempt.attempt_id)
        assert new_plan.source_fingerprint != plan.source_fingerprint
        assert new_plan.source_asset.probe_status == "succeeded"
        assert new_plan.loss_items and not new_plan.consent_satisfied
        assert new_plan.attempt_id != attempt.attempt_id
        assert store.get_attempt(attempt.attempt_id).state == JobState.FAILED


async def test_webm_webvtt_subtitle_is_preserved(fixture_root, tmp_path):
    from media_converter.common.process import capture_process
    from media_converter.jobs.job_service import JobService
    from media_converter.jobs.models import JobState
    from media_converter.media.importer import ImportService
    from media_converter.media.models import ConversionSettings
    from media_converter.media.planner import ConversionPlanner
    from media_converter.media.probe import ProbeService
    from media_converter.storage.local_store import LocalStore

    snapshot = inspect_toolchain(AppPaths.from_argument(tmp_path / "data"))
    source = tmp_path / "subtitled.webm"
    await capture_process(
        snapshot.ffmpeg.path,
        [
            "-v",
            "error",
            "-n",
            "-i",
            str(fixture_root / "media/基础.webm"),
            "-i",
            str(fixture_root / "subtitles/文字.srt"),
            "-map",
            "0",
            "-map",
            "1:0",
            "-c",
            "copy",
            "-c:s",
            "webvtt",
            str(source),
        ],
    )
    with LocalStore(tmp_path / "state.sqlite3") as store:
        imported = ImportService(store).import_paths([source])
        asset = await ProbeService(snapshot.ffprobe.path, store).probe(imported.assets[0])
        settings = ConversionSettings(
            container="webm",
            video_encoder="libvpx-vp9",
            audio_encoder="auto",
            quality_value=32,
            output_dir=tmp_path / "out",
        )
        plan = ConversionPlanner(snapshot).plan_one(settings, asset, imported.roots[0])
        assert not plan.loss_items and sum(m.kind == "subtitle" for m in plan.stream_mapping) == 1
        service = JobService(store, snapshot)
        result = (await service.wait(await service.start_batch([plan], "webvtt")))[0]
        assert result.state == JobState.SUCCEEDED
        assert service.validations[result.attempt_id]["streams"][-1]["codec_name"] == "webvtt"
