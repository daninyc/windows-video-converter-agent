from pathlib import Path

import pytest
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QInputDialog

from media_converter.common.errors import AppError
from media_converter.media.presets import open_output_location
from media_converter.ui.preset_actions import PresetActions
from media_converter.ui.settings_panel import SettingsPanel

pytestmark = pytest.mark.gui


def test_save_load_requests_and_actual_output_uri(qtbot, tmp_path, monkeypatch):
    panel = SettingsPanel()
    qtbot.addWidget(panel)
    actions = PresetActions(panel)
    saved, loaded = [], []
    actions.save_requested.connect(saved.append)
    actions.load_requested.connect(loaded.append)
    actions.set_presets([{"preset_id": "one", "name": "常用"}])
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **kw: ("常用", True))
    actions._save()
    actions._load()
    assert saved == ["常用"] and loaded == ["one"]
    urls = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: urls.append(url) or True)
    output = tmp_path / "结果 (2).mp4"
    assert open_output_location(output) == tmp_path
    assert Path(urls[0].toLocalFile()) == tmp_path
    with pytest.raises(AppError):
        open_output_location(tmp_path / "missing" / "out.mp4")
