import asyncio
import hashlib
import json
import sys

import pytest

from media_converter.common.errors import AppError
from media_converter.devtools.bench_agent import benchmark
from media_converter.devtools.resources import ResourceMonitor
from media_converter.services.component_manifest import Artifact
from media_converter.services.downloads import Downloader
from media_converter.worker_runtime import installed_worker, worker_command

pytestmark = pytest.mark.unit


async def test_live_benchmark_without_human_receipt_never_connects(tmp_path):
    result = await benchmark(tmp_path, tmp_path / "result.json", live_api=True)
    assert result["status"] == "blocked" and result["online_called"] is False
    assert "media_playback_passed" in result["missing"]


def test_prepare_failure_writes_report_for_windowed_cli(tmp_path, monkeypatch):
    from media_converter.common.errors import ErrorCode
    from media_converter.devtools.__main__ import main
    from media_converter.services.preparer import SetupService

    async def fail(self, **kwargs):
        raise AppError(ErrorCode.ACCESS_DENIED)

    monkeypatch.setattr(SetupService, "prepare", fail)
    output = tmp_path / "failure.json"
    assert (
        main(
            ["prepare", "--components", "ai", "--data-dir", str(tmp_path), "--output", str(output)]
        )
        == 2
    )
    report = json.loads(output.read_text("utf-8"))
    assert not report["ok"] and report["error_code"] == "ACCESS_DENIED"


async def test_adjacent_worker_requires_valid_bytes_and_never_falls_back_to_network(tmp_path):
    item = Artifact(
        "ai-tools",
        "test",
        "",
        hashlib.sha256(b"valid").hexdigest(),
        5,
        "tools",
        "fixture",
        adjacent_only=True,
    )
    downloader = Downloader(tmp_path)
    with pytest.raises(AppError):
        await downloader.obtain(item)
    cached = tmp_path / "worker.zip"
    cached.write_bytes(b"valid")
    assert await downloader.obtain(item, cached=cached) == cached
    cached.write_bytes(b"wrong")
    with pytest.raises(AppError):
        await downloader.obtain(item, cached=cached)


def test_frozen_worker_fails_closed_on_missing_or_changed_executable(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    with pytest.raises(AppError):
        worker_command("mcp", tmp_path)
    exe = tmp_path / "components/tools/MediaConverterTools/MediaConverterTools.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"fixture")
    marker = tmp_path / "components/installed/ai-tools.json"
    marker.parent.mkdir()
    marker.write_text(
        json.dumps(
            {
                "files": {
                    "MediaConverterTools/MediaConverterTools.exe": hashlib.sha256(
                        b"fixture"
                    ).hexdigest()
                }
            }
        )
    )
    assert installed_worker(tmp_path) == exe
    assert worker_command("mcp", tmp_path) == [str(exe), "mcp"]
    exe.write_bytes(b"modified")
    with pytest.raises(AppError):
        installed_worker(tmp_path)


async def test_resource_monitor_observes_current_process_without_privileged_commands():
    with ResourceMonitor() as monitor:
        await asyncio.sleep(0.35)
    report = monitor.report()
    assert report["peak_observed_total_rss_bytes"] > 0
    assert any(row["pid"] > 0 and row["peak_rss_bytes"] > 0 for row in report["processes"])
