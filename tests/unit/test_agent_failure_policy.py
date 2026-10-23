import asyncio

import httpx
import pytest

from media_converter.agent.deepseek_adapter import DeepSeekAdapter, ModelResponse
from media_converter.agent.service import AgentService
from media_converter.common.errors import AppError, ErrorCode
from media_converter.media.models import ConversionSettings
from media_converter.services.config import APIConfig, ConfigService
from media_converter.storage.local_store import LocalStore
from tests.unit.test_agent_turn import MCPSubstitute

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "status,code",
    [(401, ErrorCode.AUTH_FAILED), (402, ErrorCode.QUOTA_EXHAUSTED), (429, ErrorCode.RATE_LIMITED)],
)
async def test_simulated_http_error_not_replayed_and_version_gate(status, code, tmp_path):
    config = ConfigService(tmp_path)
    config.save(APIConfig(base_url="https://simulated.invalid"), "sentinel-test-key")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, json={"error": "simulated"})

    adapter = DeepSeekAdapter(config, transport=httpx.MockTransport(handler))
    for _ in range(2):
        with pytest.raises(AppError) as error:
            await adapter.respond([], [])
        assert error.value.info.code == code
    assert len(requests) == (2 if status == 429 else 1)
    config.save(config.load(), "new-sentinel-test-key")
    with pytest.raises(AppError):
        await adapter.respond([], [])
    assert len(requests) == (3 if status == 429 else 2)


async def test_cancelled_provider_late_text_and_proposal_are_discarded(tmp_path):
    entered = asyncio.Event()
    events = []

    class ResistsOnce:
        async def respond(self, items, tools, on_delta, **kwargs):
            entered.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                await asyncio.sleep(0.02)
            on_delta("LATE-TEXT-MUST-NOT-APPEAR")
            return ModelResponse("LATE-TEXT-MUST-NOT-APPEAR", (), (), None, "simulated")

    class NoProposal:
        def from_answer(self, *args):
            pytest.fail("Cancelled response must not produce a proposal")

    with LocalStore(tmp_path / "state.sqlite3") as store:
        service = AgentService(
            store,
            tmp_path,
            events.append,
            adapter=ResistsOnce(),
            mcp=MCPSubstitute(),
            proposals=NoProposal(),
        )
        try:
            chat = service.chats.create()
            turn = await service.submit(chat.conversation_id, "question", ConversionSettings())
            await entered.wait()
            assert await service.cancel(turn.context.turn_id)
            result = await service.wait(turn.context.turn_id)
            assert result.state == "CANCELLED"
            assert not any(e["kind"] in {"delta", "proposal"} for e in events)
            assert all(
                "LATE-TEXT" not in m.text for m in service.chats.messages(chat.conversation_id)
            )
        finally:
            await service.close()
