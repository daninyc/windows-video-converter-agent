import asyncio
import io
import json
from pathlib import Path

import pytest

from media_converter.common.context import CallContext
from media_converter.common.errors import AppError, ErrorCode, normalize_error, result_envelope
from media_converter.common.logging import JsonlLogger

pytestmark = pytest.mark.unit


def test_errors_are_failures_and_cancellation_propagates():
    context = CallContext().new_turn("conversation").new_invocation()
    for code in ErrorCode:
        result = result_envelope(context, error=AppError(code), data="must not leak")
        assert not result["ok"] and result["data"] is None
        assert result["error"]["suggested_action"]
    assert normalize_error(TimeoutError()).info.retryable
    with pytest.raises(asyncio.CancelledError):
        result_envelope(context, error=asyncio.CancelledError())
    assert result_envelope(context, data=[])["ok"]


def test_nested_credentials_exception_urls_and_paths_are_redacted(capsys):
    context = CallContext().new_turn("conversation").new_invocation()
    stream = io.StringIO()
    logger = JsonlLogger(stream)
    logger.event(
        "tool.finished",
        context,
        tool_name="rag_search",
        queue_ms=12,
        args={
            "api_key": "SENTINEL_API_KEY",
            "nested": [{"password": "SENTINEL_PASSWORD"}],
            "url": "https://user:SENTINEL_PASSWORD@host/?key=SENTINEL_API_KEY",
            "path": Path("D:/private/SENTINEL_PATH.txt"),
            "body": "SENTINEL_BODY",
            "SENTINEL_IN_FIELD_NAME": "value",
            "tool_name": "SENTINEL_TOOL_NAME",
            "state": "SENTINEL_STATE",
        },
        exception=ValueError("SENTINEL_API_KEY in D:/private/SENTINEL_PATH.txt"),
    )
    output = stream.getvalue()
    assert "SENTINEL" not in output
    event = json.loads(output)
    assert event["trace_id"] == context.trace_id
    assert event["fields"]["tool_name"] == "rag_search"
    assert not capsys.readouterr().out


def test_redaction_fails_closed(monkeypatch):
    import media_converter.common.logging as module

    stream = io.StringIO()
    monkeypatch.setattr(module, "redact", lambda *a: 1 / 0)
    context = CallContext()
    JsonlLogger(stream).event("test", context, password="DO_NOT_PRINT")
    assert json.loads(stream.getvalue()) == {
        "event": "log_redaction_failed",
        "trace_id": context.trace_id,
    }


def test_log_write_failure_does_not_fall_back_to_protocol_stdout(capsys):
    class Unwritable:
        def write(self, value):
            raise OSError("injected full disk")

    logger = JsonlLogger(Unwritable())
    logger.event("test", CallContext(), body="SENTINEL_SECRET")
    assert logger.write_failed and not capsys.readouterr().out
