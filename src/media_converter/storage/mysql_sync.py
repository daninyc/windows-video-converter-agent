import asyncio
import json
import secrets
from pathlib import Path

from media_converter.common.errors import AppError, ErrorCode
from media_converter.storage.credentials import CredentialStore

DATABASE = "video_converter_app"


def mysql_config(data_dir, role):
    try:
        config = json.loads((Path(data_dir) / "mysql.json").read_text(encoding="utf-8"))
        if config["database"] != DATABASE or config["host"] != "127.0.0.1":
            raise AppError(ErrorCode.ACCESS_DENIED)
        return {
            "host": config["host"],
            "port": config["port"],
            "database": DATABASE,
            "user": config[role]["user"],
            "password": CredentialStore(Path(data_dir) / "private").read(
                config[role]["credential_ref"]
            ),
            "connection_timeout": 5,
            "read_timeout": 10,
            "write_timeout": 10,
            "use_pure": True,
        }
    except (OSError, ValueError, KeyError) as error:
        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE) from error


def initialize_mysql(data_dir, admin_password, rules_root, *, port=3307):
    from media_converter.storage.mysql_driver import connector

    data_dir = Path(data_dir)
    config_path = data_dir / "mysql.json"
    private = CredentialStore(data_dir / "private")
    with connector.connect(
        host="127.0.0.1",
        port=port,
        user="root",
        password=admin_password,
        connection_timeout=10,
        use_pure=True,
    ) as connection:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s", (DATABASE,)
        )
        exists = cursor.fetchone() is not None
        if exists:
            try:
                cursor.execute(f"SELECT value FROM {DATABASE}.project_meta WHERE name='owner'")
                if cursor.fetchone() != ("media-converter",):
                    raise AppError(ErrorCode.ACCESS_DENIED)
            except connector.Error as error:
                raise AppError(ErrorCode.ACCESS_DENIED) from error
        else:
            cursor.execute(f"CREATE DATABASE {DATABASE} CHARACTER SET utf8mb4")
        cursor.execute(f"USE {DATABASE}")
        sql = (Path(__file__).with_name("mysql_migrations") / "001_project.sql").read_text(
            encoding="utf-8"
        )
        for statement in sql.split(";"):
            if statement.strip():
                cursor.execute(statement)
        cursor.execute("INSERT IGNORE INTO project_meta VALUES('owner','media-converter')")
        connection.commit()
        if not config_path.exists():
            config = {"schema_version": 1, "host": "127.0.0.1", "port": port, "database": DATABASE}
            for role, username in (("reader", "vc_app_reader_v1"), ("sync", "vc_app_sync_v1")):
                cursor.execute(
                    "SELECT COUNT(*) FROM mysql.user WHERE User=%s AND Host='127.0.0.1'",
                    (username,),
                )
                if cursor.fetchone()[0]:
                    raise AppError(ErrorCode.ACCESS_DENIED)
                password = secrets.token_urlsafe(32)
                cursor.execute(
                    f"CREATE USER '{username}'@'127.0.0.1' IDENTIFIED BY %s", (password,)
                )
                reference = private.save(password)
                config[role] = {"user": username, "credential_ref": reference}
                tables = (
                    ("technical_rules", "presets", "conversion_attempts", "sync_state")
                    if role == "reader"
                    else ("presets", "conversion_attempts", "sync_events", "sync_state")
                )
                privileges = "SELECT" if role == "reader" else "SELECT,INSERT,UPDATE"
                for table in tables:
                    cursor.execute(
                        f"GRANT {privileges} ON {DATABASE}.{table} TO '{username}'@'127.0.0.1'"
                    )
            config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        rules = json.loads((Path(rules_root) / "rules.json").read_text(encoding="utf-8"))
        for rule in rules:
            cursor.execute(
                "INSERT INTO technical_rules VALUES(%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE "
                "rule_kind=IF(VALUES(version)>=version,VALUES(rule_kind),rule_kind),"
                "format_name=IF(VALUES(version)>=version,VALUES(format_name),format_name),"
                "codec=IF(VALUES(version)>=version,VALUES(codec),codec),"
                "error_code=IF(VALUES(version)>=version,VALUES(error_code),error_code),"
                "rule_json=IF(VALUES(version)>=version,VALUES(rule_json),rule_json),"
                "source_ref=IF(VALUES(version)>=version,VALUES(source_ref),source_ref),"
                "version=GREATEST(version,VALUES(version))",
                (
                    rule["rule_id"],
                    rule["rule_kind"],
                    rule.get("format"),
                    rule.get("codec"),
                    rule.get("error_code"),
                    rule["version"],
                    json.dumps(rule["source_ref"], ensure_ascii=False),
                    json.dumps(rule, ensure_ascii=False),
                ),
            )
        connection.commit()
    return {"database": DATABASE, "rules": len(rules), "credentials": "DPAPI references only"}


class MySQLSync:
    def __init__(self, store, instance_id, data_dir):
        self.store, self.instance_id, self.data_dir = store, instance_id, Path(data_dir)
        self.slots = asyncio.Semaphore(1)

    def _apply(self, event):
        from media_converter.storage.mysql_driver import connector

        with connector.connect(**mysql_config(self.data_dir, "sync")) as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT event_id FROM sync_events WHERE instance_id=%s AND event_id=%s",
                (self.instance_id, event.event_id),
            )
            if cursor.fetchone():
                return
            payload = json.loads(event.payload) if isinstance(event.payload, str) else event.payload
            if event.entity_type == "presets":
                settings = payload["settings"]
                cursor.execute(
                    "INSERT INTO presets VALUES(%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE "
                    "name=IF(VALUES(version)>=version,VALUES(name),name),container=IF(VALUES(version)>=version,VALUES(container),container),settings_json=IF(VALUES(version)>=version,VALUES(settings_json),settings_json),version=GREATEST(version,VALUES(version))",
                    (
                        self.instance_id,
                        event.entity_id,
                        event.version,
                        payload["name"],
                        settings["container"],
                        json.dumps(settings, ensure_ascii=False),
                    ),
                )
            elif event.entity_type == "job_attempts":
                # Keep raw paths in SQLite; project safe fields to the query database.
                payload.pop("output_path", None)
                plan = self.store.get_plan(payload["plan_id"])
                if plan:
                    settings = plan.settings_snapshot.model_dump(mode="json")
                    settings.pop("output_dir", None)
                    payload["settings"] = settings
                cursor.execute(
                    "INSERT INTO conversion_attempts VALUES(%s,%s,%s,%s,%s,%s,%s) "
                    "ON DUPLICATE KEY UPDATE "
                    "status=IF(VALUES(version)>=version,VALUES(status),status),payload=IF(VALUES(version)>=version,VALUES(payload),payload),updated_at=IF(VALUES(version)>=version,VALUES(updated_at),updated_at),version=GREATEST(version,VALUES(version))",
                    (
                        self.instance_id,
                        event.entity_id,
                        payload["asset_id"],
                        payload["state"],
                        event.version,
                        json.dumps(payload, ensure_ascii=False),
                        event.created_at,
                    ),
                )
            cursor.execute(
                "INSERT INTO sync_events VALUES(%s,%s)", (self.instance_id, event.event_id)
            )
            cursor.execute(
                "INSERT INTO sync_state VALUES(%s,%s,%s) ON DUPLICATE KEY UPDATE "
                "data_time=IF(VALUES(watermark)>=watermark,VALUES(data_time),data_time),"
                "watermark=GREATEST(watermark,VALUES(watermark))",
                (self.instance_id, event.event_id, event.created_at),
            )
            connection.commit()

    async def sync_once(self):
        async with self.slots:
            events = await asyncio.to_thread(self.store.pending_events, 100)
            count = 0
            for event in events:
                try:
                    await asyncio.to_thread(self._apply, event)
                    await asyncio.to_thread(self.store.acknowledge_event, event.event_id)
                    count += 1
                except Exception as error:
                    await asyncio.to_thread(
                        self.store.record_sync_failure,
                        event.event_id,
                        ErrorCode.DEPENDENCY_UNAVAILABLE,
                    )
                    raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE) from error
            return count
