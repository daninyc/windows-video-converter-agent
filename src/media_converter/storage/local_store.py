import json
import queue
import sqlite3
import threading
from concurrent.futures import Future
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from media_converter.common.errors import AppError, ErrorCode
from media_converter.jobs.models import TERMINAL_STATES, JobAttempt, JobState
from media_converter.jobs.state_machine import transition
from media_converter.media.models import ConversionPlan, ConversionSettings, ImportRoot, MediaAsset
from media_converter.storage.outbox import OutboxEvent

_TABLES = frozenset(
    {
        "settings",
        "presets",
        "assets",
        "job_attempts",
        "import_roots",
        "conversion_plans",
        "batch_commands",
    }
)
SCHEMA_VERSION = 4


class LocalStore:
    """One connection owned by the writer; every reader opens its own WAL connection."""

    def __init__(self, database_path: Path):
        self.path = Path(database_path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._queue = queue.Queue(maxsize=256)
        self._gate = threading.Lock()
        self._closed = False
        self._ready = Future()
        self._thread = threading.Thread(target=self._writer, name="local-store-writer")
        self._thread.start()
        self._ready.result(timeout=15)

    def _writer(self):
        connection = None
        try:
            connection = sqlite3.connect(self.path, isolation_level=None, timeout=10)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            self._transaction(connection, self._migrate)
            self._transaction(connection, self._recover_attempts)
            self._ready.set_result(None)
        except Exception as error:
            self._ready.set_exception(error)
            if connection:
                connection.close()
            return
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    return
                operation, future = item
                if not future.set_running_or_notify_cancel():
                    continue
                try:
                    future.set_result(self._transaction(connection, operation))
                except Exception as error:
                    future.set_exception(error)
        finally:
            connection.close()

    @staticmethod
    def _transaction(connection, operation):
        connection.execute("BEGIN IMMEDIATE")
        try:
            result = operation(connection)
            connection.commit()
            return result
        except BaseException:
            connection.rollback()
            raise

    @staticmethod
    def _migrate(connection):
        current = connection.execute("PRAGMA user_version").fetchone()[0]
        if current > SCHEMA_VERSION:
            raise AppError(ErrorCode.PROTOCOL_MISMATCH)
        migrations = Path(__file__).with_name("migrations")
        for version in range(current + 1, SCHEMA_VERSION + 1):
            file = next(migrations.glob(f"{version:03d}_*.sql"))
            for statement in file.read_text("utf-8").split(";"):
                if statement.strip():
                    connection.execute(statement)
            connection.execute(f"PRAGMA user_version={version}")

    def _recover_attempts(self, connection):
        rows = connection.execute("SELECT payload FROM job_attempts").fetchall()
        for row in rows:
            attempt = JobAttempt.model_validate_json(row[0])
            if attempt.state not in TERMINAL_STATES:
                interrupted = transition(attempt, JobState.INTERRUPTED, error_code="INTERRUPTED")
                self._save(
                    connection,
                    "job_attempts",
                    attempt.attempt_id,
                    interrupted.model_dump(mode="json"),
                    state=interrupted.state,
                )

    def _write(self, operation):
        future = Future()
        with self._gate:
            if self._closed:
                raise AppError(ErrorCode.INVALID_STATE)
            try:
                self._queue.put_nowait((operation, future))
            except queue.Full as error:
                raise AppError(ErrorCode.QUEUE_FULL) from error
        return future.result()

    @staticmethod
    def _save(connection, table, entity_id, payload, *, state=None):
        if table not in _TABLES:
            raise AppError(ErrorCode.INVALID_ARGUMENT)
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        old = connection.execute(
            f"SELECT version, payload FROM {table} WHERE entity_id=?",
            (entity_id,),
        ).fetchone()
        if old and old["payload"] == encoded:
            return old["version"]
        version = old["version"] + 1 if old else 1
        if table == "job_attempts":
            connection.execute(
                "INSERT INTO job_attempts VALUES(?,?,?,?) ON CONFLICT(entity_id) DO UPDATE SET "
                "version=excluded.version, payload=excluded.payload, state=excluded.state",
                (entity_id, version, encoded, state),
            )
        else:
            connection.execute(
                f"INSERT INTO {table} VALUES(?,?,?) ON CONFLICT(entity_id) DO UPDATE SET "
                "version=excluded.version, payload=excluded.payload",
                (entity_id, version, encoded),
            )
        connection.execute(
            "INSERT INTO outbox_events(entity_type,entity_id,version,payload,created_at) "
            "VALUES(?,?,?,?,?)",
            (table, entity_id, version, encoded, datetime.now(UTC).isoformat()),
        )
        return version

    def _get(self, table, entity_id):
        if table not in _TABLES:
            raise AppError(ErrorCode.INVALID_ARGUMENT)
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            row = connection.execute(
                f"SELECT payload FROM {table} WHERE entity_id=?",
                (entity_id,),
            ).fetchone()
            return json.loads(row[0]) if row else None

    def save_settings(self, settings: ConversionSettings) -> int:
        return self._write(
            lambda c: self._save(c, "settings", "current", settings.model_dump(mode="json"))
        )

    def get_settings(self) -> ConversionSettings | None:
        payload = self._get("settings", "current")
        return ConversionSettings.model_validate(payload) if payload else None

    def save_preset(self, preset_id: str, name: str, settings: ConversionSettings) -> int:
        payload = {
            "preset_id": preset_id,
            "name": name,
            "settings": settings.model_dump(mode="json"),
        }
        return self._write(lambda c: self._save(c, "presets", preset_id, payload))

    def get_preset(self, preset_id: str) -> dict | None:
        return self._get("presets", preset_id)

    def save_asset(self, asset: MediaAsset) -> int:
        return self._write(
            lambda c: self._save(c, "assets", asset.asset_id, asset.model_dump(mode="json"))
        )

    def get_asset(self, asset_id: str) -> MediaAsset | None:
        payload = self._get("assets", asset_id)
        return MediaAsset.model_validate(payload) if payload else None

    def _list(self, table):
        if table not in _TABLES:
            raise AppError(ErrorCode.INVALID_ARGUMENT)
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            if table == "assets":
                rows = connection.execute(
                    "SELECT payload FROM assets WHERE entity_id NOT IN "
                    "(SELECT asset_id FROM archived_assets) ORDER BY rowid"
                ).fetchall()
            else:
                rows = connection.execute(f"SELECT payload FROM {table} ORDER BY rowid").fetchall()
        return [json.loads(row[0]) for row in rows]

    def list_assets(self) -> list[MediaAsset]:
        return [MediaAsset.model_validate(item) for item in self._list("assets")]

    def save_import_root(self, root: ImportRoot) -> int:
        return self._write(
            lambda c: self._save(c, "import_roots", root.root_id, root.model_dump(mode="json"))
        )

    def get_import_root(self, root_id: str) -> ImportRoot | None:
        payload = self._get("import_roots", root_id)
        return ImportRoot.model_validate(payload) if payload else None

    def archive_asset(self, asset_id: str) -> None:
        self._write(
            lambda c: (
                c.execute("INSERT OR IGNORE INTO archived_assets VALUES(?)", (asset_id,)).rowcount
            )
        )

    def list_presets(self) -> list[dict]:
        return self._list("presets")

    def get_plan(self, plan_id: str) -> ConversionPlan | None:
        payload = self._get("conversion_plans", plan_id)
        return ConversionPlan.model_validate(payload) if payload else None

    def get_batch_command(self, command_id: str) -> dict | None:
        return self._get("batch_commands", command_id)

    def register_batch(
        self,
        command_id: str,
        batch_id: str,
        plans: tuple[ConversionPlan, ...],
        attempts: tuple[JobAttempt, ...],
    ) -> str:
        def operation(connection):
            existing = connection.execute(
                "SELECT payload FROM batch_commands WHERE entity_id=?", (command_id,)
            ).fetchone()
            if existing:
                return json.loads(existing[0])["batch_id"]
            if len(plans) != len(attempts):
                raise AppError(ErrorCode.INVALID_ARGUMENT)
            for plan, attempt in zip(plans, attempts, strict=True):
                if (
                    attempt.plan_id != plan.plan_id
                    or attempt.attempt_id != plan.attempt_id
                    or attempt.asset_id != plan.asset_id
                    or attempt.batch_id != batch_id
                ):
                    raise AppError(ErrorCode.INVALID_ARGUMENT)
                self._save(
                    connection, "conversion_plans", plan.plan_id, plan.model_dump(mode="json")
                )
                self._save(
                    connection,
                    "job_attempts",
                    attempt.attempt_id,
                    attempt.model_dump(mode="json"),
                    state=attempt.state,
                )
            self._save(
                connection,
                "batch_commands",
                command_id,
                {"batch_id": batch_id, "plan_ids": [plan.plan_id for plan in plans]},
            )
            return batch_id

        return self._write(operation)

    def list_attempts(self) -> list[JobAttempt]:
        return [JobAttempt.model_validate(item) for item in self._list("job_attempts")]

    def save_attempt(self, attempt: JobAttempt) -> int:
        def operation(connection):
            row = connection.execute(
                "SELECT payload FROM job_attempts WHERE entity_id=?",
                (attempt.attempt_id,),
            ).fetchone()
            if row:
                old = JobAttempt.model_validate_json(row[0])
                if old != attempt:
                    if old.state in TERMINAL_STATES:
                        raise AppError(ErrorCode.INVALID_STATE)
                    identifiers = ("attempt_id", "job_id", "batch_id", "asset_id", "plan_id")
                    if any(getattr(old, key) != getattr(attempt, key) for key in identifiers):
                        raise AppError(ErrorCode.INVALID_ARGUMENT)
                    if old.state != attempt.state:
                        transition(old, attempt.state)
            return self._save(
                connection,
                "job_attempts",
                attempt.attempt_id,
                attempt.model_dump(mode="json"),
                state=attempt.state,
            )

        return self._write(operation)

    def get_attempt(self, attempt_id: str) -> JobAttempt | None:
        payload = self._get("job_attempts", attempt_id)
        return JobAttempt.model_validate(payload) if payload else None

    def pending_events(self, limit: int = 100) -> list[OutboxEvent]:
        if not 1 <= limit <= 1000:
            raise AppError(ErrorCode.INVALID_ARGUMENT)
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT * FROM outbox_events WHERE synced_at IS NULL ORDER BY event_id LIMIT ?",
                (limit,),
            ).fetchall()
            return [OutboxEvent(**dict(row)) for row in rows]

    def acknowledge_event(self, event_id: int) -> None:
        self._write(
            lambda c: (
                c.execute(
                    "UPDATE outbox_events SET synced_at=? WHERE event_id=? AND synced_at IS NULL",
                    (datetime.now(UTC).isoformat(), event_id),
                ).rowcount
            )
        )

    def record_sync_failure(self, event_id: int, code: ErrorCode) -> None:
        self._write(
            lambda c: (
                c.execute(
                    "UPDATE outbox_events SET retry_count=retry_count+1,last_error_code=? "
                    "WHERE event_id=? AND synced_at IS NULL",
                    (ErrorCode(code).value, event_id),
                ).rowcount
            )
        )

    def close(self):
        with self._gate:
            if self._closed:
                return
            self._closed = True
        self._queue.put(None)
        self._thread.join(timeout=15)
        if self._thread.is_alive():
            raise AppError(ErrorCode.TIMEOUT)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
