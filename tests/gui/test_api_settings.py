import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialogButtonBox

from media_converter.services.config import ConfigService
from media_converter.ui.api_settings import APISettingsDialog

pytestmark = pytest.mark.gui


def test_api_save_restart_clear_and_sentinel(qtbot, tmp_path):
    service = ConfigService(tmp_path)
    dialog = APISettingsDialog(service)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.key_edit.setText("gui-sentinel-secret")
    qtbot.mouseClick(
        dialog.buttons.button(QDialogButtonBox.StandardButton.Save), Qt.MouseButton.LeftButton
    )
    assert service.request_config()[1] == "gui-sentinel-secret"
    assert "sentinel" not in service.path.read_text(encoding="utf-8")
    restored = APISettingsDialog(ConfigService(tmp_path))
    qtbot.addWidget(restored)
    assert restored.key_edit.text() == "" and restored.key_edit.echoMode().name == "Password"
    restored.clear()
    assert service.load().credential_ref is None
