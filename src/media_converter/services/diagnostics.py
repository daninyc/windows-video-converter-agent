"""An export inventory, never an archive of the user's data directory."""

import hashlib
import importlib.metadata
import json
import os
import re
import zipfile
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from media_converter.common.logging import redact
from media_converter.storage.local_store import SCHEMA_VERSION

EVENTS = {
    "runtime.finished",
    "tool.finished",
    "conversion.state",
    "conversion.process_started",
    "conversion.process_exited",
    "conversion.state_unpersisted",
    "conversion.cleanup_failed",
}
IDS = {"trace_id", "conversation_id", "turn_id", "instance_id", "invocation_id", "task_id"}
FIELDS = {
    "tool_name",
    "state",
    "error_code",
    "cache_state",
    "queue_ms",
    "execution_ms",
    "retry_count",
    "exit_code",
    "attempt_id",
    "binary_sha256",
    "argument_hash",
}


class Diagnostics:
    def __init__(self, data_dir):
        self.root = Path(data_dir).resolve()

    def collect(self):
        versions = {}
        for package in ("media-converter", "PySide6", "mcp", "qdrant-client", "torch"):
            try:
                versions[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                versions[package] = "missing"
        records = deque(maxlen=1000)
        path = self.root / "events.jsonl"
        if path.is_file() and path.resolve().is_relative_to(self.root):
            # Bounded tail; never follow arbitrary paths supplied inside log fields.
            with path.open("rb") as stream:
                size = path.stat().st_size
                stream.seek(max(0, size - 2 * 1024**2))
                if size > 2 * 1024**2:
                    stream.readline()
                for line in stream:
                    if len(line) > 64000:
                        continue
                    try:
                        value = json.loads(line)
                        if value.get("event") not in EVENTS:
                            continue
                        item = {"event": value["event"]}
                        for key in IDS:
                            text = value.get(key)
                            if isinstance(text, str) and re.fullmatch(
                                r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", text
                            ):
                                item[key] = text
                        fields = value.get("fields", {})
                        item["fields"] = redact({k: fields[k] for k in FIELDS if k in fields})
                        records.append(item)
                    except (ValueError, TypeError, AttributeError):
                        continue
        context = {
            "schema_version": 1,
            "sqlite_schema": SCHEMA_VERSION,
            "platform": "Windows" if os.name == "nt" else "other",
            "generated_at": datetime.now(UTC).isoformat(),
            "versions": versions,
            "configuration_present": {
                name: (self.root / (name + ".json")).is_file()
                for name in ("ai-components", "mysql", "api")
            },
            "data_location_hash": hashlib.sha256(str(self.root).encode()).hexdigest(),
            "record_count": len(records),
            "scope": "versions, allowlisted log summaries, anonymous context; no source data",
        }
        return context, list(records)

    def export(self, destination):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        context, records = self.collect()
        stage = destination.with_name(".diagnostic-" + uuid4().hex + ".partial")
        try:
            with zipfile.ZipFile(stage, "x", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("context.json", json.dumps(context, ensure_ascii=False, indent=2))
                archive.writestr("events.jsonl", "\n".join(json.dumps(r) for r in records))
            # The user chooses the destination; never silently replace an existing export.
            os.link(stage, destination)
        finally:
            stage.unlink(missing_ok=True)
        return {"ok": True, "records": len(records), "files": ["context.json", "events.jsonl"]}
