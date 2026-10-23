import asyncio
import time

import pytest

from media_converter.agent.models import TurnContext
from media_converter.common.context import new_id
from media_converter.common.errors import AppError
from media_converter.mcp_client import MCPConnection


async def test_incompatible_protocol_is_terminal_without_automatic_reconnect(tmp_path, monkeypatch):
    import mcp

    entries, exits = [], []

    class IncompatiblePeer:
        protocol_version = "incompatible-test-protocol"

        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            entries.append(True)
            return self

        async def __aexit__(self, *args):
            exits.append(True)

    monkeypatch.setattr(mcp, "Client", IncompatiblePeer)
    connection = MCPConnection(tmp_path)
    context = TurnContext(
        conversation_id=new_id(),
        instance_id=new_id(),
        settings_version=1,
        settings_json="{}",
        deadline_at=time.time() + 10,
        scope_version="test",
    )
    try:
        with pytest.raises(AppError) as error:
            await connection.call("list_conversion_presets", {}, context)
        assert error.value.info.code == "PROTOCOL_MISMATCH"
        assert len(entries) == len(exits) == 1 and connection.retries == 0
    finally:
        await connection.close()


async def test_cancel_one_startup_subscriber_does_not_cancel_shared_owner(tmp_path, monkeypatch):
    connection = MCPConnection(tmp_path)
    gate, started = asyncio.Event(), asyncio.Event()
    owners = []

    async def own(ready, stop):
        owners.append(True)
        started.set()
        await gate.wait()
        ready.set_result(None)
        await stop.wait()

    monkeypatch.setattr(connection, "_own", own)
    first = asyncio.create_task(connection.start())
    await started.wait()
    second = asyncio.create_task(connection.start())
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert not connection.ready.cancelled()
    gate.set()
    await second
    await connection.close()
    assert len(owners) == 1 and connection.owner.done()
