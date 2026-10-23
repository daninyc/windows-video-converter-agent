import asyncio
import os
import signal
import time

import pytest

from media_converter.agent.models import Turn
from media_converter.common.errors import AppError, ErrorCode
from media_converter.mcp_client import MCPConnection
from media_converter.media.models import ConversionSettings
from media_converter.storage.conversations import ConversationStore
from media_converter.storage.local_store import LocalStore

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("in_flight", [False, True])
async def test_five_calls_after_real_process_death_reconnect_once(
    tmp_path, record_property, in_flight
):
    with LocalStore(tmp_path / "state.sqlite3") as store:
        chats = ConversationStore(store)
        turns = []
        for index in range(5):
            conversation = chats.create()
            source = tmp_path / f"{index}.txt"
            source.write_text(f"marker-{index}", encoding="utf-8")
            ref = chats.add_reference(conversation.conversation_id, "file", str(source))
            turn = chats.begin(conversation.conversation_id, "read", ConversionSettings())
            chats.save_turn(Turn(context=turn.context, state="RUNNING"))
            turns.append((turn.context, ref.reference_id))
        connection = MCPConnection(tmp_path)
        try:
            await connection.start()
            killed_pid = connection.server_pid
            if not in_flight:
                os.kill(killed_pid, signal.SIGTERM)
                await asyncio.sleep(0.2)
            tasks = [
                asyncio.create_task(
                    connection.call("read_local_file", {"file_ref_id": reference}, context)
                )
                for context, reference in turns
            ]
            if in_flight:
                asyncio.get_running_loop().call_soon(os.kill, killed_pid, signal.SIGTERM)
            results = await asyncio.wait_for(
                asyncio.gather(*tasks),
                20,
            )
            assert connection.starts == 2 and connection.server_pid != killed_pid
            assert [result["data"]["text"] for result in results] == [
                f"marker-{i}" for i in range(5)
            ]
            assert all(chats.turn(ctx.turn_id).state == "RUNNING" for ctx, _ in turns)
            record_property("transport_starts", connection.starts)
            record_property("read_only_retry_attempts", connection.retries)
        finally:
            await connection.close()
        assert not list((tmp_path / "runtime").glob("mcp-*.json"))


async def test_cancel_without_reply_and_close_do_not_restart(tmp_path):
    with LocalStore(tmp_path / "state.sqlite3") as store:
        chats = ConversationStore(store)
        conversation = chats.create()
        source = tmp_path / "note.txt"
        source.write_text("test", encoding="utf-8")
        ref = chats.add_reference(conversation.conversation_id, "file", str(source))
        turn = chats.begin(conversation.conversation_id, "read", ConversionSettings())
        chats.save_turn(Turn(context=turn.context, state="RUNNING"))
        connection = MCPConnection(tmp_path)
        await connection.start()
        original = connection.client.call_tool
        entered = asyncio.Event()

        async def wait_without_result(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()

        connection.client.call_tool = wait_without_result
        pending = asyncio.create_task(
            connection.call("read_local_file", {"file_ref_id": ref.reference_id}, turn.context)
        )
        await entered.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(pending, 1)
        connection.client.call_tool = original
        result = await connection.call(
            "read_local_file", {"file_ref_id": ref.reference_id}, turn.context
        )
        assert result["ok"] and connection.starts == 1
        expired = turn.context.model_copy(update={"deadline_at": time.time() - 1})
        with pytest.raises(AppError) as error:
            await connection.call("read_local_file", {"file_ref_id": ref.reference_id}, expired)
        assert error.value.info.code == ErrorCode.TIMEOUT
        await connection.close()
        with pytest.raises(AppError):
            await connection.start()
