import json
import sqlite3

import pytest

from media_converter.media.models import ConversionSettings
from media_converter.media.presets import PresetService
from media_converter.storage.local_store import LocalStore
from tests.unit.test_settings_validation import capabilities

pytestmark = pytest.mark.unit


def test_two_launches_updates_versions_and_invalid_encoder(tmp_path):
    path = tmp_path / "state.sqlite3"
    settings = ConversionSettings(output_dir=tmp_path / "outputs")
    with LocalStore(path) as store:
        service = PresetService(store, capabilities())
        identity = service.save("常用", settings)
        service.remember(settings)
        updated = settings.model_copy(update={"quality_value": 20, "settings_version": 2})
        assert service.save("常用", updated) == identity
        events = [event for event in store.pending_events() if event.entity_type == "presets"]
        assert [event.version for event in events] == [1, 2]
    with LocalStore(path) as store:
        service = PresetService(store, capabilities())
        assert service.restore().settings == settings
        assert service.load(identity).settings == updated
        missing = capabilities()
        missing.encoders = ("libvpx-vp9", "aac", "libopus")
        assert PresetService(store, missing).load(identity).settings is None
        assert PresetService(store, missing).restore().issues


def test_legacy_settings_defaults_survive_storage_migration(tmp_path):
    path = tmp_path / "state.sqlite3"
    with LocalStore(path) as store:
        identity = PresetService(store, capabilities()).save("legacy", ConversionSettings())
    with sqlite3.connect(path) as connection:
        payload = {"preset_id": identity, "name": "legacy", "settings": {"quality_value": 21}}
        connection.execute(
            "UPDATE presets SET payload=? WHERE entity_id=?", (json.dumps(payload), identity)
        )
    with LocalStore(path) as store:
        restored = PresetService(store, capabilities()).load(identity)
        assert restored.settings.quality_value == 21 and restored.settings.frame_rate is None
