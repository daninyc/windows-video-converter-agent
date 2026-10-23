import asyncio
import json

import pytest

from media_converter.agent.deepseek_adapter import ModelResponse
from media_converter.agent.service import AgentService
from media_converter.media.models import ConversionSettings
from media_converter.storage.local_store import LocalStore

pytestmark = pytest.mark.unit


class MCPSubstitute:
    def __init__(self):
        self.calls = []
        self.arguments = []

    async def model_tools(self):
        return []

    async def call(self, name, args, context, invocation_id):
        self.calls.append(name)
        self.arguments.append(args)
        if name == "rag_search":
            return {"ok": True, "data": {"evidence_sufficient": False}, "sources": []}
        return {"ok": False, "data": None, "sources": [], "error": {"code": "AUTH_FAILED"}}

    async def close(self):
        pass


async def test_insufficient_evidence_triggers_mcp_search_and_stores_pairs(tmp_path):
    class Provider:
        calls = 0

        async def respond(self, items, tools, on_delta, **kwargs):
            self.calls += 1
            if self.calls == 1:
                output = {
                    "type": "function_call",
                    "call_id": "rag",
                    "name": "rag_search",
                    "arguments": '{"query":"MP4"}',
                }
                return ModelResponse(
                    "",
                    (
                        {
                            "type": "reasoning",
                            "content": [{"type": "reasoning_text", "text": "opaque"}],
                        },
                        output,
                    ),
                    ({"call_id": "rag", "name": "rag_search", "arguments": {"query": "MP4"}},),
                    None,
                    "simulated",
                )
            assert any(
                i.get("type") == "function_call_output" and i["call_id"].startswith("host-search")
                for i in items
            )
            types = [i.get("type") for i in items if i.get("type")]
            assert types == [
                "reasoning",
                "function_call",
                "function_call",
                "function_call_output",
                "function_call_output",
            ]
            assert sum(i.get("type") == "reasoning" for i in items) == 1
            return ModelResponse(
                "目前无法确认",
                (
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "目前无法确认"}],
                    },
                ),
                (),
                None,
                "simulated",
            )

    with LocalStore(tmp_path / "state.sqlite3") as local:
        mcp = MCPSubstitute()
        service = AgentService(local, tmp_path, adapter=Provider(), mcp=mcp)
        try:
            conversation = service.chats.create()
            turn = await service.submit(
                conversation.conversation_id, "FFmpeg 支持 .xyzvideo 吗？", ConversionSettings()
            )
            result = await service.wait(turn.context.turn_id)
            assert result.state == "SUCCEEDED" and mcp.calls == ["rag_search", "search_web"]
            assert ".xyzvideo" in mcp.arguments[-1]["query"]
            assert json.loads(result.usage_json) == [None, None]
        finally:
            await service.close()


@pytest.mark.parametrize("per_round,model_rounds,tool_calls", [(1, 8, 8), (3, 6, 15), (17, 1, 0)])
async def test_simulated_budgets_count_cached_calls(tmp_path, per_round, model_rounds, tool_calls):
    class Provider:
        calls = 0

        async def respond(self, *args, **kwargs):
            self.calls += 1
            calls = tuple(
                {"call_id": f"{self.calls}-{i}", "name": "lookup_technical_rules", "arguments": {}}
                for i in range(per_round)
            )
            output = tuple({"type": "function_call", **call, "arguments": "{}"} for call in calls)
            return ModelResponse("", output, calls, None, "simulated")

    class SuccessfulMCP(MCPSubstitute):
        async def call(self, name, args, context, invocation_id):
            self.calls.append(name)
            return {"ok": True, "data": {}, "sources": []}

    with LocalStore(tmp_path / "state.sqlite3") as local:
        provider, mcp = Provider(), SuccessfulMCP()
        service = AgentService(local, tmp_path, adapter=provider, mcp=mcp)
        try:
            conversation = service.chats.create()
            turn = await service.submit(conversation.conversation_id, "规则", ConversionSettings())
            result = await service.wait(turn.context.turn_id)
            assert result.state == "FAILED" and result.error_code == "TURN_LIMIT_REACHED"
            assert provider.calls == model_rounds
            invocations = service.chats._rows("SELECT payload FROM tool_invocations")
            assert len(invocations) == tool_calls
            assert len(mcp.calls) == (1 if tool_calls else 0)
            assert all(json.loads(row[0])["state"] == "SUCCEEDED" for row in invocations)
        finally:
            await service.close()


async def test_simulated_parallel_branches_are_bounded_and_results_paired(tmp_path):
    class Provider:
        calls = 0

        async def respond(self, items, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                calls = tuple(
                    {
                        "call_id": str(i),
                        "name": "lookup_technical_rules",
                        "arguments": {"codec": str(i)},
                    }
                    for i in range(8)
                )
                output = tuple(
                    {"type": "function_call", **call, "arguments": json.dumps(call["arguments"])}
                    for call in calls
                )
                return ModelResponse("", output, calls, None, "simulated")
            outputs = [item for item in items if item.get("type") == "function_call_output"]
            assert {item["call_id"] for item in outputs} == {str(i) for i in range(8)}
            for item in outputs:
                assert json.loads(item["output"])["data"]["codec"] == item["call_id"]
            return ModelResponse("完成", (), (), None, "simulated")

    class ParallelMCP(MCPSubstitute):
        active = 0
        peak = 0

        async def call(self, name, args, context, invocation_id):
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                await asyncio.sleep(0.01 * (8 - int(args["codec"])))
                return {"ok": True, "data": args, "sources": []}
            finally:
                self.active -= 1

    with LocalStore(tmp_path / "state.sqlite3") as local:
        mcp = ParallelMCP()
        service = AgentService(local, tmp_path, adapter=Provider(), mcp=mcp)
        try:
            conversation = service.chats.create()
            turn = await service.submit(conversation.conversation_id, "格式", ConversionSettings())
            assert (await service.wait(turn.context.turn_id)).state == "SUCCEEDED"
            assert mcp.peak == 4 and mcp.active == 0
        finally:
            await service.close()


async def test_queued_cancellation_is_terminal_and_same_conversation_serial(tmp_path):
    class Provider:
        active = 0
        peak = 0

        async def respond(self, *args, **kwargs):
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                await asyncio.Event().wait()
            finally:
                self.active -= 1

    with LocalStore(tmp_path / "state.sqlite3") as local:
        provider = Provider()
        service = AgentService(local, tmp_path, adapter=provider, mcp=MCPSubstitute())
        try:
            conversation = service.chats.create()
            first = await service.submit(
                conversation.conversation_id, "first", ConversionSettings()
            )
            second = await service.submit(
                conversation.conversation_id, "second", ConversionSettings()
            )
            await service.cancel(second.context.turn_id)
            assert service.chats.turn(second.context.turn_id).state == "CANCELLED"
            await asyncio.sleep(0.02)
            await service.cancel(first.context.turn_id)
            assert provider.peak <= 1
            assert service.chats.turn(first.context.turn_id).state == "CANCELLED"
        finally:
            await service.close()
