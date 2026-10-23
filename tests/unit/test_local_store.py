import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from media_converter.common.errors import AppError, ErrorCode
from media_converter.jobs.models import JobAttempt, JobState
from media_converter.jobs.state_machine import transition
from media_converter.media.models import ConversionSettings
from media_converter.storage.local_store import SCHEMA_VERSION, LocalStore
from tests.unit.test_conversion_models import make_asset

pytestmark = pytest.mark.unit


def test_transaction_rolls_back_business_and_outbox(tmp_path):
    path = tmp_path / "state.sqlite3"
    with LocalStore(path) as store:
        with sqlite3.connect(path) as c:
            c.execute(
                "CREATE TRIGGER fail_outbox BEFORE INSERT ON outbox_events "
                "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
            )
        with pytest.raises(sqlite3.IntegrityError):
            store.save_settings(ConversionSettings())
        assert store.get_settings() is None and store.pending_events() == []


def test_repositories_duplicate_terminal_and_recovery(tmp_path):
    path = tmp_path / "state.sqlite3"
    attempt = JobAttempt(batch_id="batch", asset_id="asset", plan_id="plan")
    with LocalStore(path) as store:
        asset = make_asset(tmp_path)
        store.save_asset(asset)
        assert store.get_asset(asset.asset_id) == asset
        store.save_preset("preset", "测试", ConversionSettings())
        assert store.get_preset("preset")["name"] == "测试"
        store.save_attempt(attempt)
    with LocalStore(path) as store:
        interrupted = store.get_attempt(attempt.attempt_id)
        assert interrupted.state == JobState.INTERRUPTED
        count = len(store.pending_events())
        store.save_attempt(interrupted)
        assert len(store.pending_events()) == count
        with pytest.raises(AppError):
            store.save_attempt(attempt)
        event = store.pending_events()[0]
        store.record_sync_failure(event.event_id, ErrorCode.DEPENDENCY_UNAVAILABLE)
        assert store.pending_events()[0].retry_count == 1
        store.acknowledge_event(event.event_id)
        assert all(e.event_id != event.event_id for e in store.pending_events())
    with LocalStore(path) as store:
        assert store.get_attempt(attempt.attempt_id) == interrupted


def test_old_schema_migration_preserves_data(tmp_path):
    path = tmp_path / "old.sqlite3"
    migration = Path(__file__).parents[2] / "src/media_converter/storage/migrations/001_initial.sql"
    with sqlite3.connect(path) as c:
        c.executescript(migration.read_text("utf-8"))
        c.execute("PRAGMA user_version=1")
        c.execute(
            "INSERT INTO settings VALUES(?,?,?)",
            ("current", 1, ConversionSettings().model_dump_json()),
        )
    with LocalStore(path) as store:
        assert store.get_settings() == ConversionSettings()
        store.save_settings(ConversionSettings(settings_version=2))
        assert len(store.pending_events()) == 1
    with sqlite3.connect(path) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_serial_writes_concurrent_readers_and_close(tmp_path):
    store = LocalStore(tmp_path / "parallel.sqlite3")

    def work(index):
        store.save_preset(str(index), f"preset {index}", ConversionSettings())
        return store.get_preset(str(index))["preset_id"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert set(pool.map(work, range(30))) == {str(i) for i in range(30)}
    assert len(store.pending_events()) == 30
    store.close()
    assert not store._thread.is_alive()
    with pytest.raises(AppError):
        store.save_settings(ConversionSettings())


def test_cancelled_cannot_be_success_and_no_duplicate_events(tmp_path):
    with LocalStore(tmp_path / "terminal.sqlite3") as store:
        attempt = JobAttempt(batch_id="b", asset_id="a", plan_id="p")
        store.save_attempt(attempt)
        cancelled = transition(attempt, JobState.CANCELLED)
        store.save_attempt(cancelled)
        store.save_attempt(cancelled)
        assert len(store.pending_events()) == 2
        with pytest.raises(AppError):
            store.save_attempt(cancelled.model_copy(update={"state": JobState.SUCCEEDED}))
