import asyncio
import importlib.metadata
import tempfile
import time
from pathlib import Path

from media_converter.agent.models import Turn
from media_converter.common.errors import AppError, ErrorCode, normalize_error
from media_converter.config import AppPaths
from media_converter.mcp_client import MCPConnection
from media_converter.media.models import ConversionSettings
from media_converter.media.toolchain import inspect_toolchain
from media_converter.storage.conversations import ConversationStore
from media_converter.storage.local_store import LocalStore


class HealthService:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir).resolve()

    async def inspect(self, *, require="all-local", emit=lambda value: None):
        results = []

        async def check(name, factory):
            started = time.monotonic()
            emit({"component": name, "state": "checking"})
            try:
                async with asyncio.timeout(180):
                    detail = await factory()
                result = {"component": name, "ok": True, "detail": detail}
            except Exception as error:
                info = normalize_error(error).info
                result = {
                    "component": name,
                    "ok": False,
                    "error_code": info.code,
                    "message": info.message,
                    "action": info.suggested_action,
                }
            result["seconds"] = round(time.monotonic() - started, 3)
            results.append(result)
            emit(result)

        async def core():
            snapshot = await asyncio.to_thread(inspect_toolchain, AppPaths(self.data_dir))
            snapshot.require_ready()
            return {"ffmpeg": snapshot.ffmpeg_version, "ffprobe": snapshot.ffprobe_version}

        await check("video", core)
        if require == "core":
            return {"ok": all(r["ok"] for r in results), "checks": results, "online_called": False}
        (self.data_dir / "doctor").mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="check-", dir=self.data_dir / "doctor") as folder:
            root = Path(folder)
            note = root / "probe.txt"
            note.write_text("doctor-authorized-text", encoding="utf-8")
            with LocalStore(root / "state.sqlite3") as store:
                chats = ConversationStore(store)
                chat = chats.create("依赖健康检查")
                ref = chats.add_reference(chat.conversation_id, "file", str(note))
                turn = chats.begin(chat.conversation_id, "本地健康检查", ConversionSettings())
                chats.save_turn(Turn(context=turn.context, state="RUNNING"))
                connection = MCPConnection(root, components_dir=self.data_dir)

                async def catalog():
                    from media_converter.tools.schemas import SCHEMAS

                    tools = await connection.model_tools()
                    if {t["name"] for t in tools} != set(SCHEMAS):
                        raise AppError(ErrorCode.PROTOCOL_MISMATCH)
                    return {
                        "protocol": connection.protocol_version,
                        "sdk": importlib.metadata.version("mcp"),
                        "tools": sorted(t["name"] for t in tools),
                    }

                async def tool(name, arguments):
                    result = await connection.call(name, arguments, turn.context)
                    if not result["ok"]:
                        raise AppError(ErrorCode(result["error"]["code"]))
                    return result["data"]

                async def rag():
                    value = await tool(
                        "rag_search", {"query": "本应用 MP4 默认视频音频编码", "top_k": 1}
                    )
                    stages = value["retrieval_stages"]
                    if (
                        value["limited"]
                        or not all(stages[k]["ok"] for k in ("dense", "lexical"))
                        or not stages["rerank"].get("executed")
                    ):
                        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
                    from media_converter.rag.index_store import IndexStore
                    from media_converter.services.config import read_ai_components

                    config = read_ai_components(self.data_dir)
                    active = IndexStore(self.data_dir).active()
                    return {
                        "knowledge_version": value["knowledge_version"],
                        "stages": stages,
                        "embedding_model": config["embedding_model"],
                        "embedding_digest": config["embedding_digest"],
                        "dimensions": active["dimensions"],
                        "tokenizer_hash": active["tokenizer_hash"],
                    }

                async def sql():
                    value = await tool("lookup_technical_rules", {})
                    from media_converter.storage.mysql_driver import connector
                    from media_converter.storage.mysql_sync import mysql_config

                    def permissions():
                        with connector.connect(**mysql_config(self.data_dir, "reader")) as db:
                            cursor = db.cursor()
                            cursor.execute("SHOW GRANTS")
                            grants = [row[0].upper() for row in cursor.fetchall()]
                            if any(
                                word in grant
                                for grant in grants
                                for word in (
                                    "ALL PRIVILEGES",
                                    "INSERT",
                                    "UPDATE",
                                    "DELETE",
                                    "CREATE",
                                    " FILE ",
                                    "GRANT OPTION",
                                )
                            ):
                                raise AppError(ErrorCode.ACCESS_DENIED)
                            cursor.execute("SELECT VERSION()")
                            return cursor.fetchone()[0]

                    version = await asyncio.to_thread(permissions)
                    return {
                        "readonly": True,
                        "rules": len(value["rules"]),
                        "server_version": version,
                    }

                async def file():
                    value = await tool("read_local_file", {"file_ref_id": ref.reference_id})
                    if value["text"] != "doctor-authorized-text":
                        raise AppError(ErrorCode.PROTOCOL_MISMATCH)
                    return {"authorized_text": True}

                try:
                    await check("mcp", catalog)
                    await check("knowledge", rag)
                    await check("mysql", sql)
                    await check("files", file)
                finally:
                    await connection.close()
        return {"ok": all(r["ok"] for r in results), "checks": results, "online_called": False}
