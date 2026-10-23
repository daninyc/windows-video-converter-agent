import asyncio
import json

import pytest

from media_converter.agent.deepseek_adapter import ModelResponse
from media_converter.agent.service import AgentService
from media_converter.media.models import ConversionSettings
from media_converter.storage.local_store import LocalStore

pytestmark = pytest.mark.integration


class SimulatedProvider:
    """Explicit model substitute; every tool call still crosses the real stdio process."""

    def __init__(self):
        self.references = {}
        self.active = 0
        self.peak = 0
        self.requests = []

    async def respond(self, items, tools, on_delta, **kwargs):
        question = next(item["content"] for item in reversed(items) if item.get("role") == "user")
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(0.01)
        finally:
            self.active -= 1
        self.requests.append((question, items))
        output = next(
            (item for item in reversed(items) if item.get("type") == "function_call_output"), None
        )
        if output is None or output["call_id"] != question:
            call = {
                "type": "function_call",
                "name": "read_local_file",
                "call_id": question,
                "arguments": json.dumps(
                    {"file_ref_id": self.references[question], "max_chars": 100}
                ),
            }
            return ModelResponse(
                "",
                (call,),
                (
                    {
                        "name": call["name"],
                        "call_id": question,
                        "arguments": json.loads(call["arguments"]),
                    },
                ),
                {"input_tokens": 10, "output_tokens": 5},
                "simulated-provider",
            )
        data = json.loads(output["output"])
        assert data["ok"] and question in data["data"]["text"]
        text = "已读取 " + question
        on_delta(text)
        return ModelResponse(
            text,
            (
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text}],
                },
            ),
            (),
            {"input_tokens": 20, "output_tokens": 4},
            "simulated-provider",
        )


async def test_five_conversations_real_mcp_no_cross_pairing(tmp_path, record_property):
    provider = SimulatedProvider()
    with LocalStore(tmp_path / "state.sqlite3") as store:
        service = AgentService(store, tmp_path, adapter=provider)
        turns = []
        try:
            for index in range(5):
                question = f"session-{index}"
                file = tmp_path / f"{index}.txt"
                file.write_text(question, encoding="utf-8")
                conversation = service.chats.create(question)
                reference = service.chats.add_reference(
                    conversation.conversation_id, "file", str(file)
                )
                provider.references[question] = reference.reference_id
                turns.append(
                    await service.submit(
                        conversation.conversation_id, question, ConversionSettings()
                    )
                )
            results = await asyncio.gather(*(service.wait(t.context.turn_id) for t in turns))
            assert all(r.state == "SUCCEEDED" for r in results)
            assert provider.peak <= 5 and service.mcp.starts == 1
            for index, turn in enumerate(turns):
                messages = service.chats.messages(turn.context.conversation_id)
                assert messages[-1].text == f"已读取 session-{index}"
                assert json.loads(results[index].usage_json)[0]["input_tokens"] == 10
            record_property("provider", "simulated; real stdio MCP and local file parser")
            record_property("actual_protocol", str(service.mcp.protocol_version))
        finally:
            await service.close()
