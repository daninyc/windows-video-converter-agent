import json
import subprocess
import sys

import pytest
from PySide6.QtCore import Qt

from media_converter.config import AppPaths
from media_converter.ui.main_window import MainWindow
from media_converter.ui.theme import apply_theme

pytestmark = pytest.mark.gui


def test_shell_real_widgets_dock_and_disabled_features(qtbot, qapp, tmp_path):
    apply_theme(qapp)
    window = MainWindow(AppPaths.from_argument(tmp_path))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    assert not window.start_button.isEnabled()
    assert not window.add_files_button.isEnabled()
    assert not window.container_combo.isEnabled()
    assert window.task_model.rowCount() == 0
    widget = window.agent_dock.widget()
    qtbot.mouseClick(window.float_button, Qt.MouseButton.LeftButton)
    assert window.agent_dock.isFloating()
    qtbot.mouseClick(window.float_button, Qt.MouseButton.LeftButton)
    assert not window.agent_dock.isFloating() and window.agent_dock.widget() is widget
    qtbot.mouseClick(window.ai_toggle, Qt.MouseButton.LeftButton)
    assert not window.agent_dock.isVisible()
    qtbot.mouseClick(window.ai_toggle, Qt.MouseButton.LeftButton)
    assert window.agent_dock.isVisible()
    window.resize(window.minimumSize())
    qtbot.wait(50)
    for control in (window.task_table, window.start_button, window.ai_toggle, window.progress_bar):
        assert control.isVisible() and control.width() > 20 and control.height() > 0
    window.close()


@pytest.mark.parametrize("scale", ["1", "1.5", "2"])
def test_real_windows_scale_capture_exits_cleanly(scale, tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "media_converter.devtools.capture_shell",
            "--scale",
            scale,
            "--output",
            str(tmp_path),
        ],
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    percent = round(float(scale) * 100)
    record = json.loads((tmp_path / f"shell-{percent}.json").read_text("utf-8"))
    assert record["qt_platform"] == "windows"
    assert record["device_pixel_ratio"] == float(scale)
    assert record["image_pixels"] == [round(n * float(scale)) for n in record["logical_window"]]
    assert all(c["inside_window"] for c in record["controls"])
    assert (tmp_path / record["screenshot"]).stat().st_size > 1000
