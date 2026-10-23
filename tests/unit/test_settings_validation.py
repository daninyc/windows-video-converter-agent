from types import SimpleNamespace

import pytest

from media_converter.media.models import ConversionSettings
from media_converter.media.settings import DEFAULT_ENCODERS, SettingsService

pytestmark = pytest.mark.unit


def capabilities():
    return SimpleNamespace(
        encoders=("libx264", "libvpx-vp9", "aac", "libopus"), muxers=("mp4", "matroska", "webm")
    )


def test_defaults_invalid_values_and_versions(tmp_path):
    service = SettingsService(capabilities())
    for container, (video, audio, quality) in DEFAULT_ENCODERS.items():
        assert service.validate(
            dict(
                container=container, video_encoder=video, audio_encoder=audio, quality_value=quality
            )
        ).valid
    assert not service.validate({"frame_rate": {"numerator": 1, "denominator": 0}}).valid
    assert not service.validate({"quality_value": -1}).valid
    assert not service.validate({"resolution": {"width": 501, "height": 300}}).valid
    assert not service.validate({"container": "webm"}).valid
    assert not service.validate({}, require_output=True).valid
    assert service.validate({"output_dir": tmp_path}, require_output=True).valid
    initial = ConversionSettings()
    changed = service.update(initial, {"quality_value": 20}).settings
    assert changed.settings_version == 2 and initial.quality_value == 23
    assert service.update(changed, {}).settings == changed
