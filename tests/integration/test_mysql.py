import asyncio
import shutil

import pytest

from media_converter.agent.models import Turn
from media_converter.common.errors import AppError
from media_converter.mcp_client import MCPConnection
from media_converter.media.models import ConversionSettings
from media_converter.storage.conversations import ConversationStore
from media_converter.storage.local_store import LocalStore
from media_converter.storage.mysql_sync import MySQLSync, mysql_config

pytestmark = pytest.mark.integration


async def test_real_sync_idempotence_and_query_permissions(ai_source, tmp_path):
    import mysql.connector

    shutil.copy(ai_source / "mysql.json", tmp_path / "mysql.json")
    shutil.copytree(ai_source / "private", tmp_path / "private")
    with LocalStore(tmp_path / "state.sqlite3") as store:
        chats = ConversationStore(store)
        conversation = chats.create()
        store.save_preset("preset", "中文 preset", ConversionSettings())
        event = store.pending_events()[0]
        sync = MySQLSync(store, chats.instance_id, tmp_path)
        assert await sync.sync_once() == 1
        await __import__("asyncio").to_thread(sync._apply, event)
        turn = chats.begin(conversation.conversation_id, "查询", ConversionSettings())
        chats.save_turn(Turn(context=turn.context, state="RUNNING"))
        mcp = MCPConnection(tmp_path)
        try:
            presets = await mcp.call("list_conversion_presets", {}, turn.context)
            assert presets["ok"] and len(presets["data"]["presets"]) == 1
            rules = await mcp.call("lookup_technical_rules", {"codec": "mov_text"}, turn.context)
            assert rules["ok"] and rules["data"]["rules"]
            injection = await mcp.call(
                "lookup_technical_rules", {"codec": "' OR 1=1 --"}, turn.context
            )
            assert injection["ok"] and not injection["data"]["rules"]
            history = await mcp.call("query_conversion_history", {}, turn.context)
            assert history["ok"] and not history["data"]["attempts"]
            with mysql.connector.connect(**mysql_config(tmp_path, "reader")) as connection:
                cursor = connection.cursor()
                for sql in (
                    "DELETE FROM presets WHERE preset_id='never'",
                    "SELECT * FROM video_converter_env.environment_probe",
                ):
                    with pytest.raises(mysql.connector.Error):
                        cursor.execute(sql)
        finally:
            await mcp.close()


async def test_real_commit_before_local_ack_replays_and_old_version_cannot_overwrite(
    ai_source, tmp_path, monkeypatch
):
    import mysql.connector

    shutil.copy(ai_source / "mysql.json", tmp_path / "mysql.json")
    shutil.copytree(ai_source / "private", tmp_path / "private")
    with LocalStore(tmp_path / "state.sqlite3") as store:
        chats = ConversationStore(store)
        store.save_preset("replay", "旧预设", ConversionSettings())
        old_event = store.pending_events()[0]
        store.save_preset("replay", "新预设", ConversionSettings(container="webm"))
        new_event = store.pending_events()[-1]
        sync = MySQLSync(store, chats.instance_id, tmp_path)
        await asyncio.to_thread(sync._apply, new_event)

        original_ack = store.acknowledge_event

        def interrupted_ack(event_id):
            raise OSError("simulated interruption after target commit")

        monkeypatch.setattr(store, "acknowledge_event", interrupted_ack)
        with pytest.raises(AppError):
            await sync.sync_once()
        assert len(store.pending_events()) == 2
        monkeypatch.setattr(store, "acknowledge_event", original_ack)
        assert await sync.sync_once() == 2 and not store.pending_events()
        await asyncio.to_thread(sync._apply, old_event)
        with mysql.connector.connect(**mysql_config(tmp_path, "reader")) as connection:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT name,container,version FROM presets WHERE instance_id=%s AND preset_id=%s",
                (chats.instance_id, "replay"),
            )
            assert cursor.fetchone() == ("新预设", "webm", new_event.version)
