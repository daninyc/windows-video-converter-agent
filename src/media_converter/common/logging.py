import hashlib
import json
import re
import sys
import threading
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from media_converter.common.context import CallContext
from media_converter.common.errors import ErrorCode

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,79}\Z")
_UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
_SAFE_VALUES = {
    "tool_name": {
        "rag_search",
        "lookup_technical_rules",
        "list_conversion_presets",
        "query_conversion_history",
        "read_local_file",
        "search_web",
    },
    "state": {
        "succeeded",
        "failed",
        "cancelled",
        "queued",
        "running",
        "QUEUED",
        "PREPARING",
        "NEEDS_CONFIRMATION",
        "READY",
        "RUNNING",
        "VERIFYING",
        "CANCELLING",
        "SUCCEEDED",
        "FAILED",
        "CANCELLED",
        "INTERRUPTED",
    },
    "cache_state": {"hit", "miss", "merged", "bypass"},
    "error_code": {code.value for code in ErrorCode},
    "code": {code.value for code in ErrorCode},
}
_SAFE_KEYS = {
    "instance_id",
    "trace_id",
    "conversation_id",
    "turn_id",
    "invocation_id",
    "task_id",
    "tool_name",
    "state",
    "cache_state",
    "error_code",
    "code",
    "queue_ms",
    "execution_ms",
    "retry_count",
    "args",
    "exception",
    "argument_hash",
    "scope_hash",
    "reference_version",
    "pid",
    "started_at",
    "exit_code",
    "attempt_id",
    "binary_sha256",
    "stderr",
}
_PRIVATE = re.compile(r"key|secret|password|credential|token|authorization|body|content|text", re.I)


def summary(value: str) -> dict:
    return {"sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(), "chars": len(value)}


def redact(value, key: str = ""):
    if _PRIVATE.search(key):
        return "[redacted]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, dict):
        # Arbitrary dictionary keys may themselves contain paths, credentials or document text.
        return {
            k if k in _SAFE_KEYS else "field_" + str(i): redact(v, str(k))
            for i, (k, v) in enumerate(value.items())
        }
    if isinstance(value, (list, tuple)):
        return [redact(item, key) for item in value]
    if isinstance(value, BaseException):
        return {"exception_type": type(value).__name__, "detail": summary(str(value))}
    if isinstance(value, Path):
        return "[private path]"
    if isinstance(value, str):
        if key in {"argument_hash", "scope_hash", "binary_sha256"} and re.fullmatch(
            r"[0-9a-f]{64}", value
        ):
            return value
        if (key.endswith("_id") and _UUID.fullmatch(value)) or value in _SAFE_VALUES.get(key, ()):
            return value
        return summary(value)
    return "[unsupported value]"


class JsonlLogger:
    def __init__(self, stream: TextIO | None = None):
        self.stream = stream if stream is not None else sys.stderr
        self._lock = threading.Lock()
        self.write_failed = False

    def event(self, event: str, context: CallContext, **fields) -> None:
        try:
            record = {
                "time": datetime.now(UTC).isoformat(),
                "event": event if _IDENTIFIER.fullmatch(event) else "invalid_event_name",
                **redact(asdict(context)),
                "fields": redact(fields),
            }
            line = json.dumps(record, ensure_ascii=False, allow_nan=False)
        except Exception:
            # Fail closed: never log repr(fields) or the exception that defeated redaction.
            trace_id = getattr(context, "trace_id", None)
            safe_trace = (
                trace_id if isinstance(trace_id, str) and _UUID.fullmatch(trace_id) else None
            )
            line = json.dumps({"event": "log_redaction_failed", "trace_id": safe_trace})
        with self._lock:
            try:
                self.stream.write(line + "\n")
                self.stream.flush()
            except (OSError, ValueError):
                self.write_failed = True
