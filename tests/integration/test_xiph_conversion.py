"""Opt-in real-world sequence; preparation is separate from offline pytest execution."""

import asyncio
import hashlib
import json
import os
import platform
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pytest

from media_converter.common.context import new_id
from media_converter.common.process import capture_process
from media_converter.config import AppPaths, application_root
from media_converter.jobs.job_service import JobService
from media_converter.jobs.models import JobState
from media_converter.media.importer import ImportService
from media_converter.media.models import ConversionSettings
from media_converter.media.planner import ConversionPlanner
from media_converter.media.probe import ProbeService
from media_converter.media.thumbnail import ThumbnailService
from media_converter.media.toolchain import inspect_toolchain
from media_converter.storage.local_store import LocalStore

pytestmark = pytest.mark.integration


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


async def test_xiph_crowd_run_1080p50_conversion(request, record_property):
    root = request.config.getoption("--xiph-root")
    if root is None:
        pytest.skip("真实素材须先下载，再显式指定 --xiph-root；见 docs/XIPH_TEST.md")
    root = root.resolve()
    provenance = json.loads(
        (application_root() / "docs/test-media/xiph-crowd-run.json").read_text(encoding="utf-8")
    )
    # Explicit opt-in with missing/changed files must fail, never silently skip.
    for item in (provenance["source"], provenance["license"]):
        path = root / item["file"]
        assert path.stat().st_size == item["size_bytes"]
        assert sha256(path) == item["sha256"], f"素材或许可校验失败：{path.name}"
    source = root / provenance["source"]["file"]
    before = provenance["source"]["sha256"]
    case = application_root() / "artifacts/xiph-acceptance" / new_id()
    case.mkdir(parents=True)
    paths = AppPaths.from_argument(case / "data").ensure()
    capabilities = inspect_toolchain(paths)
    capabilities.require_ready()
    timings, states, progress = {}, [], []
    started_at = datetime.now(UTC).isoformat()
    started = time.perf_counter()

    def on_event(event):
        elapsed = time.perf_counter() - started
        if event.kind == "state":
            states.append({"state": event.attempt.state, "elapsed_seconds": elapsed})
        elif event.kind == "progress":
            progress.append({"elapsed_seconds": elapsed, **asdict(event.progress)})

    with LocalStore(paths.data_dir / "state.sqlite3") as store:
        imported = ImportService(store).import_paths([source])
        assert len(imported.assets) == 1 and not imported.rejected
        tick = time.perf_counter()
        asset = await ProbeService(capabilities.ffprobe.path, store).probe(imported.assets[0])
        timings["probe_seconds"] = time.perf_counter() - tick
        assert asset.probe_status == "succeeded"
        assert (asset.width, asset.height, asset.duration_us) == (1920, 1080, 10_000_000)
        assert asset.average_frame_rate.numerator == 50
        assert asset.average_frame_rate.denominator == 1
        assert len(asset.streams) == 1 and asset.streams[0].codec == "rawvideo"
        tick = time.perf_counter()
        thumbnail = await ThumbnailService(capabilities.ffmpeg.path, case / "thumbnails").get(asset)
        timings["thumbnail_seconds"] = time.perf_counter() - tick
        assert thumbnail.path is not None and thumbnail.path.is_file()
        settings = ConversionSettings(container="mp4", output_dir=case / "outputs")
        plan = ConversionPlanner(capabilities).plan_one(settings, asset, imported.roots[0])
        assert not plan.loss_items
        jobs = JobService(store, capabilities, on_event=on_event)
        tick = time.perf_counter()
        try:
            async with asyncio.timeout(300):
                batch = await jobs.start_batch([plan], "xiph-crowd-run-1080p50")
                attempt = (await jobs.wait(batch))[0]
        finally:
            await jobs.shutdown()
        timings["batch_seconds"] = time.perf_counter() - tick
        persisted = store.get_attempt(attempt.attempt_id)
        report = {
            "schema_version": 1,
            "started_at": started_at,
            "provenance": provenance,
            "machine": {
                "platform": platform.platform(),
                "processor": platform.processor(),
                "logical_cpus": os.cpu_count(),
            },
            "ffmpeg_version": capabilities.ffmpeg_version,
            "source_asset": asset.model_dump(mode="json"),
            "plan": plan.model_dump(mode="json"),
            "attempt": attempt.model_dump(mode="json"),
            "persisted_attempt_matches": persisted == attempt,
            "ffmpeg_processes": [asdict(item) for item in jobs.processor.evidence],
            "peak_concurrency": jobs.processor.peak_active,
            "validation": jobs.validations.get(attempt.attempt_id),
            "states": states,
            "progress": progress,
            "timings": timings,
        }
        evidence_path = case / "evidence.json"
        evidence_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        record_property("evidence", str(evidence_path))
        assert attempt.state == JobState.SUCCEEDED, attempt.error_code
        assert persisted == attempt and jobs.processor.peak_active == 1
        assert jobs.processor.active_count == 0
        assert jobs.validations[attempt.attempt_id]["full_decode"]
        assert progress and progress[-1]["ended"]
        known_progress = [
            item["processed_us"] for item in progress if item["processed_us"] is not None
        ]
        # Before x264 emits timestamps, FFmpeg legitimately reports out_time_us=N/A.
        assert known_progress and known_progress == sorted(known_progress)
        assert progress[-1]["processed_us"] is not None
        output = Path(attempt.output_path)
        counted = json.loads(
            await capture_process(
                capabilities.ffprobe.path,
                ["-v", "error", "-count_frames", "-show_streams", "-of", "json", str(output)],
                timeout=60,
            )
        )
        video = counted["streams"][0]
        assert len(counted["streams"]) == 1
        assert video["codec_name"] == "h264" and video["avg_frame_rate"] == "50/1"
        assert int(video["nb_read_frames"]) == 500
        after = sha256(source)
        assert after == before
        assert not plan.temporary_path.parent.exists()
        running = next(item["elapsed_seconds"] for item in states if item["state"] == "RUNNING")
        verifying = next(item["elapsed_seconds"] for item in states if item["state"] == "VERIFYING")
        timings["ffmpeg_run_seconds"] = verifying - running
        timings["end_to_end_seconds"] = time.perf_counter() - started
        report.update(
            source_sha256_after=after,
            output_sha256=sha256(output),
            output_bytes=output.stat().st_size,
            output_probe=counted,
            average_encode_fps=500 / timings["ffmpeg_run_seconds"],
            encode_realtime_factor=10 / timings["ffmpeg_run_seconds"],
            remaining_owned_processes=jobs.processor.active_count,
        )
        assert report["output_bytes"] > 0
        report["status"] = "passed"
        evidence_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
