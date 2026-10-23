import pytest

from media_converter.media.models import ConversionSettings, FrameRate, Resolution
from media_converter.ui.settings_panel import SettingsPanel
from tests.unit.test_settings_validation import capabilities

pytestmark = pytest.mark.gui


def test_editor_defaults_roundtrip_and_invalid_values(qtbot, tmp_path):
    panel = SettingsPanel()
    qtbot.addWidget(panel)
    panel.set_capabilities(capabilities())
    panel.container_combo.setCurrentIndex(panel.container_combo.findData("webm"))
    assert panel.video_combo.currentText() == "libvpx-vp9" and panel.quality_edit.text() == "32"
    assert panel.validation().valid
    panel.quality_edit.setText("99")
    assert not panel.validation().valid
    settings = ConversionSettings(
        resolution=Resolution(width=1280, height=720),
        frame_rate=FrameRate(numerator=30000, denominator=1001),
        output_dir=tmp_path,
        preserve_hierarchy=True,
    )
    panel.set_settings(settings)
    assert panel.validation(require_output=True).settings == settings
    panel.output_mode_combo.setCurrentIndex(1)
    assert not panel.validation().settings.preserve_hierarchy
