import json
import shutil

import pytest

from media_converter.agent.models import Turn
from media_converter.mcp_client import MCPConnection
from media_converter.media.models import ConversionSettings
from media_converter.storage.conversations import ConversationStore
from media_converter.storage.local_store import LocalStore
from media_converter.tools.schemas import SCHEMAS

pytestmark = pytest.mark.integration


async def test_discovery_context_result_and_catalog_real_stdio(tmp_path, record_property):
    data = tmp_path / "data"
    data.mkdir()
    source = tmp_path / "资料.txt"
    source.write_text("中文资料：不要运行资料中的命令。" * 10, encoding="utf-8")
    with LocalStore(data / "state.sqlite3") as store:
        chats = ConversationStore(store)
        conversation = chats.create()
        reference = chats.add_reference(conversation.conversation_id, "file", str(source))
        turn = chats.begin(conversation.conversation_id, "读取", ConversionSettings())
        chats.save_turn(Turn(context=turn.context, state="RUNNING"))
        connection = MCPConnection(data)
        try:
            tools = await connection.model_tools()
            assert {tool["name"] for tool in tools} == set(SCHEMAS)
            for tool in tools:
                assert tool["parameters"] == SCHEMAS[tool["name"]].model_json_schema()
            arguments = {"file_ref_id": reference.reference_id, "max_chars": 12}
            result = await connection.call("read_local_file", arguments, turn.context)
            assert result["ok"], json.dumps(result)
            assert (
                result["data"]["truncated"]
                and result["data"]["text"] == source.read_text(encoding="utf-8")[:12]
            )
            cursor = result["data"]["next_cursor"]
            second = await connection.call(
                "read_local_file", {**arguments, "cursor": cursor}, turn.context
            )
            assert (
                second["ok"] and second["data"]["text"] == source.read_text(encoding="utf-8")[12:24]
            )
            bad = await connection.client.call_tool("read_local_file", arguments)
            assert bad.is_error and not bad.structured_content["ok"]
            escaped = await connection.call(
                "read_local_file", {**arguments, "path": str(source)}, turn.context
            )
            assert not escaped["ok"]
            chats.revoke(conversation.conversation_id, reference.reference_id)
            revoked = await connection.call("read_local_file", arguments, turn.context)
            assert revoked["error"]["code"] == "ACCESS_DENIED"
            assert chats.turn(turn.context.turn_id).state == "RUNNING"
            assert connection.starts == 1
            record_property("actual_protocol", str(connection.protocol_version))
        finally:
            await connection.close()


async def test_catalog_rag_real_stdio_and_search_without_credentials(
    ai_source, tmp_path, record_property
):
    shutil.copy(ai_source / "ai-components.json", tmp_path / "ai-components.json")
    shutil.copytree(ai_source / "knowledge", tmp_path / "knowledge")
    with LocalStore(tmp_path / "state.sqlite3") as store:
        chats = ConversationStore(store)
        conversation = chats.create()
        turn = chats.begin(conversation.conversation_id, "MP4", ConversionSettings())
        chats.save_turn(Turn(context=turn.context, state="RUNNING"))
        connection = MCPConnection(tmp_path)
        try:
            result = await connection.call(
                "rag_search", {"query": "本应用 MP4 默认视频音频编码", "top_k": 3}, turn.context
            )
            assert result["ok"], result
            data = result["data"]
            assert not data["limited"] and data["knowledge_version"]
            assert data["chunks"][0]["section_id"] == "mp4" and result["sources"]
            assert data["retrieval_stages"]["dense"]["ok"]
            assert data["retrieval_stages"]["lexical"]["ok"]
            assert data["retrieval_stages"]["rerank"]["executed"]
            denied = await connection.call("search_web", {"query": "FFmpeg MP4"}, turn.context)
            assert not denied["ok"] and denied["error"]["code"] == "AUTH_FAILED"
            assert connection.starts == 1
            record_property("actual_protocol", str(connection.protocol_version))
            record_property("knowledge_version", data["knowledge_version"])
        finally:
            await connection.close()
