import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication

from media_converter.config import application_root
from media_converter.ui.settings_diff import SettingsDiffDialog
from tests.gui.test_agent_panel import agent_window  # noqa: F401,F811

pytestmark = pytest.mark.gui


def test_proposal_requires_checkbox_then_updates_only_next_batch(agent_window, qtbot, fixture_root):  # noqa: F811
    window, conversion, agent, provider = agent_window
    conversion.import_paths([fixture_root / "media/中文 空格/基础.mp4"])
    qtbot.waitUntil(
        lambda: (
            len(conversion.model.rows) == 1
            and conversion.model.rows[0].asset.probe_status == "succeeded"
        ),
        timeout=15000,
    )
    window.task_table.selectRow(0)
    qtbot.mouseClick(agent.panel.video_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: agent.panel.references.count() == 1, timeout=10000)
    original = window.settings_panel._current
    provider.propose = True
    provider.gate.set()
    agent.send("给出参数建议")
    qtbot.waitUntil(agent.panel.proposal_button.isEnabled, timeout=15000)
    assert window.settings_panel._current == original
    seen = []
    timer = QTimer()

    def confirm():
        dialog = QApplication.activeModalWidget()
        if isinstance(dialog, SettingsDiffDialog) and not seen:
            assert not dialog.apply_button.isEnabled()
            assert "恒定质量 CRF：23 → 25" in dialog.preview.toPlainText()
            assert "reference_id" not in dialog.preview.toPlainText()
            seen.append(True)
            qtbot.mouseClick(
                dialog.confirm,
                Qt.MouseButton.LeftButton,
                pos=QPoint(10, dialog.confirm.height() // 2),
            )
            folder = application_root() / "artifacts/agent-acceptance"
            folder.mkdir(parents=True, exist_ok=True)
            dialog.grab().save(str(folder / "proposal-confirmation.png"))
            qtbot.mouseClick(dialog.apply_button, Qt.MouseButton.LeftButton)

    timer.timeout.connect(confirm)
    timer.start(10)
    try:
        qtbot.mouseClick(agent.panel.proposal_button, Qt.MouseButton.LeftButton)
    finally:
        timer.stop()
    assert seen and window.settings_panel._current.quality_value == 25
    assert (
        original.quality_value == 23
        and window.settings_panel._current.settings_version == original.settings_version + 1
    )
    assert conversion.active_batch is None and conversion.jobs.processor.active_count == 0
