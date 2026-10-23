import json
from types import SimpleNamespace

import pytest

from media_converter.agent.deepseek_adapter import ModelResponse
from media_converter.agent.service import AgentService
from media_converter.agent.turn_runner import evidence_search_query, needs_evidence_search
from media_converter.common.errors import ErrorCode
from media_converter.media.models import ConversionSettings
from media_converter.storage.local_store import LocalStore

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("tool", ["rag_search", "lookup_technical_rules"])
@pytest.mark.parametrize(
    "code",
    [
        ErrorCode.DEPENDENCY_UNAVAILABLE,
        ErrorCode.TIMEOUT,
        ErrorCode.RATE_LIMITED,
        ErrorCode.QUEUE_FULL,
        ErrorCode.MCP_DISCONNECTED,
        ErrorCode.PROCESS_FAILED,
    ],
)
def test_recoverable_technical_evidence_failures_allow_search(tool, code):
    assert needs_evidence_search(tool, {"ok": False, "error": {"code": code}})


@pytest.mark.parametrize("tool", ["rag_search", "lookup_technical_rules"])
@pytest.mark.parametrize(
    "code",
    [
        ErrorCode.ACCESS_DENIED,
        ErrorCode.INVALID_ARGUMENT,
        ErrorCode.FILE_CHANGED,
        ErrorCode.AUTH_FAILED,
        ErrorCode.QUOTA_EXHAUSTED,
        ErrorCode.PROTOCOL_MISMATCH,
    ],
)
def test_argument_permission_and_terminal_errors_do_not_start_search(tool, code):
    assert not needs_evidence_search(tool, {"ok": False, "error": {"code": code}})


@pytest.mark.parametrize(
    "tool", ["read_local_file", "list_conversion_presets", "query_conversion_history", "search_web"]
)
def test_other_tool_results_never_trigger_host_evidence_search(tool):
    assert not needs_evidence_search(
        tool, {"ok": False, "error": {"code": ErrorCode.DEPENDENCY_UNAVAILABLE}}
    )
    assert not needs_evidence_search(
        tool, {"ok": True, "data": {"evidence_sufficient": False, "conflict": True}}
    )


@pytest.mark.parametrize(
    ("tool", "data", "expected"),
    [
        ("rag_search", {"evidence_sufficient": False}, True),
        ("rag_search", {"evidence_sufficient": True}, False),
        ("lookup_technical_rules", {"conflict": True}, True),
        ("lookup_technical_rules", {"rules": []}, False),
        ("lookup_technical_rules", {"rules": [{"rule_id": "mp4"}]}, False),
        ("lookup_technical_rules", {}, False),
    ],
)
def test_only_insufficient_or_conflicting_technical_evidence_triggers_search(tool, data, expected):
    assert needs_evidence_search(tool, {"ok": True, "data": data}) is expected


def test_unknown_standalone_extension_survives_without_local_or_credential_data():
    context = SimpleNamespace(
        references=(
            SimpleNamespace(
                label="private.xyzvideo", resolved_path=r"D:\private\private.xyzvideo", kind="file"
            ),
        )
    )
    question = (
        r"FFmpeg 请检查 D:\private\private.xyzvideo 和 private.xyzvideo；"
        r"另一个未知扩展名 .xyzvideo 是否支持？password=.dontsend token='.secretext'"
    )
    query = evidence_search_query(question, context)
    assert ".xyzvideo" in query and "FFmpeg" in query
    assert not any(value in query for value in ("private", "D:", "dontsend", "secretext"))


@pytest.mark.parametrize(
    "private_text",
    [
        r"C:\private\name.xyzvideo",
        r"\\server\private\name.xyzvideo",
        "/home/private/.xyzvideo",
        "https://example.com/.xyzvideo",
        "private.xyzvideo",
        ".xyzvideo-long",
        ".xyzvideo/child",
        "password=.xyzvideo",
        "API_KEY='.xyzvideo'",
        "Bearer .xyzvideo",
    ],
)
def test_extension_is_not_extracted_from_a_path_filename_or_credential(private_text):
    query = evidence_search_query("FFmpeg " + private_text, SimpleNamespace(references=()))
    assert ".xyzvideo" not in query


def test_an_authorized_dot_filename_is_not_used_as_a_technical_extension():
    context = SimpleNamespace(
        references=(SimpleNamespace(label=".txt", resolved_path=None, kind="file"),)
    )
    query = evidence_search_query("FFmpeg 查看授权文件 .txt", context)
    assert ".txt" not in query


def test_query_stays_within_search_limits_for_many_standalone_extensions():
    question = "FFmpeg " + " ".join(f".unknown{index}" for index in range(50))
    query = evidence_search_query(question, SimpleNamespace(references=()))
    assert len(query) <= 128 and ".unknown" in query


async def test_wrong_source_id_can_be_corrected_without_automatic_web_search(tmp_path):
    class Provider:
        reference_id = ""
        calls = 0

        async def respond(self, items, *args, **kwargs):
            self.calls += 1
            if self.calls == 3:
                return ModelResponse("已读取 correct-marker", (), (), None, "simulated")
            if self.calls == 2:
                outputs = [item for item in items if item.get("type") == "function_call_output"]
                assert len(outputs) == 1
                assert json.loads(outputs[0]["output"])["error"]["code"] == "ACCESS_DENIED"
            call = {
                "call_id": f"read-{self.calls}",
                "name": "read_local_file",
                "arguments": {
                    "file_ref_id": "src-citation-not-an-authorization"
                    if self.calls == 1
                    else self.reference_id
                },
            }
            return ModelResponse(
                "",
                ({"type": "function_call", **call, "arguments": json.dumps(call["arguments"])},),
                (call,),
                None,
                "simulated",
            )

    class MCP:
        calls = []

        async def model_tools(self):
            return []

        async def call(self, name, args, context, invocation_id):
            self.calls.append(name)
            assert name == "read_local_file"
            return {"ok": True, "data": {"text": "correct-marker"}, "sources": []}

        async def close(self):
            pass

    note = tmp_path / "private.txt"
    note.write_text("correct-marker", encoding="utf-8")
    with LocalStore(tmp_path / "state.sqlite3") as store:
        provider, mcp = Provider(), MCP()
        agent = AgentService(store, tmp_path, adapter=provider, mcp=mcp)
        try:
            chat = agent.chats.create()
            reference = agent.chats.add_reference(chat.conversation_id, "file", str(note))
            provider.reference_id = reference.reference_id
            submitted = await agent.submit(
                chat.conversation_id, "读取本轮文件", ConversionSettings()
            )
            result = await agent.wait(submitted.context.turn_id)
            assert result.state == "SUCCEEDED"
            assert mcp.calls == ["read_local_file"] and provider.calls == 3
            invocations = [
                json.loads(row[0])
                for row in agent.chats._rows("SELECT payload FROM tool_invocations")
            ]
            assert [call["state"] for call in invocations] == ["FAILED", "SUCCEEDED"]
        finally:
            await agent.close()
