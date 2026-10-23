import json
import subprocess
import sys

import pytest
from PySide6.QtCore import Qt

from media_converter.media.models import ConversionSettings
from tests.gui.test_agent_panel import agent_window as agent_window

pytestmark = pytest.mark.gui


@pytest.mark.parametrize("scale", ["1", "1.5", "2"])
def test_complete_real_windows_desktop_scale_keyboard_and_setup(scale, tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "media_converter.devtools.capture_shell",
            "--full",
            "--scale",
            scale,
            "--output",
            str(tmp_path),
        ],
        capture_output=True,
        timeout=65,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")[-3000:]
    percent = round(float(scale) * 100)
    record = json.loads((tmp_path / f"desktop-{percent}.json").read_text("utf-8"))
    assert record["qt_platform"] == "windows" and record["device_pixel_ratio"] == float(scale)
    assert all(
        c["visible"] and c["visible_pixels"] and c["inside_window"] for c in record["controls"]
    )
    assert record["keyboard_tab"] and record["float_return"] and record["setup_checked"]
    assert record["logical_window"][0] <= record["available_geometry"][2]
    assert record["logical_window"][1] + 30 <= record["available_geometry"][3]
    assert (tmp_path / record["screenshot"]).stat().st_size > 1000
    assert (tmp_path / record["setup_screenshot"]).stat().st_size > 1000


def test_tool_summary_trace_and_view_closing_keep_conversation(agent_window, qtbot):
    window, _, agent, _ = agent_window
    context = agent.service.chats.begin(
        agent.current_id, "本地界面摘要检查", ConversionSettings()
    ).context
    agent._agent_event(
        {
            "kind": "tool",
            "context": context,
            "tool_name": "rag_search",
            "state": "SUCCEEDED",
            "cache_state": "hit",
        }
    )
    assert context.trace_id in agent.panel.trace.text()
    assert "检索内置资料" in agent.panel.tool_details.toPlainText()
    assert "hit" in agent.panel.tool_details.toPlainText()
    current = agent.current_id
    window.agent_dock.close()
    window.raise_()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    qtbot.keyClick(window, Qt.Key.Key_A, Qt.KeyboardModifier.AltModifier)
    qtbot.waitUntil(window.agent_dock.isVisible)
    assert window.agent_dock.isVisible() and agent.current_id == current
