import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.stress]


def test_full_agreed_video_queue_and_measured_desktop_response():
    path = Path("artifacts/reports/video-pressure.json")
    if not path.exists():
        pytest.skip("run bench-video first")
    result = json.loads(path.read_text("utf-8"))
    assert result["ok"] and result["full_queue"]["succeeded"] == 52
    assert result["full_validations"] == 52 and result["ffmpeg_peak"] == 1
    assert result["qt_platform"] == "windows"
    assert result["heartbeat"]["p95_ms"] <= 200 and result["heartbeat"]["max_ms"] <= 1000
    assert result["cancel_ui_ms"] <= 1000 and result["ffmpeg_stop_ms"] <= 5000
    assert not result["online_called"] and all(r["ok"] for r in result["local_ai"])
    fixtures = json.loads(Path(result["fixtures"]).read_text("utf-8"))
    assert len(fixtures["files"]) == 52
    assert fixtures["files"][0]["seconds"] == 1800
    assert fixtures["files"][1]["width"] == 3840 and fixtures["files"][1]["seconds"] == 60
