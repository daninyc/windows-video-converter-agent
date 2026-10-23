import asyncio
import json
from pathlib import Path

from media_converter.common.errors import AppError, ErrorCode
from media_converter.rag.embedding import EmbeddingService
from media_converter.rag.index_store import IndexStore
from media_converter.storage.conversations import ConversationStore
from media_converter.storage.local_store import LocalStore
from media_converter.storage.mysql_sync import MySQLSync, initialize_mysql


async def configure_ai(data_dir, environment_root):
    root = Path(environment_root).resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    model_path = root / "models/reranker"
    if not model_path.is_dir():
        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
    identity = await EmbeddingService("http://127.0.0.1:11434").identity()
    config = {
        "schema_version": 1,
        "ollama_url": "http://127.0.0.1:11434",
        "qdrant_url": "http://127.0.0.1:6333",
        "embedding_model": identity["model"],
        "embedding_digest": identity["digest"],
        "reranker_path": str(model_path),
        "reranker_revision": manifest["reranker"]["revision"],
        "reranker_files": manifest["reranker"]["files"],
        "relevance_threshold": 0.5,
    }
    target = Path(data_dir) / "ai-components.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "configuration": str(target),
        "existing_components": True,
        "downloaded": False,
    }


async def sync_mysql(data_dir):
    with LocalStore(Path(data_dir) / "state.sqlite3") as store:
        chats = ConversationStore(store)
        sync = MySQLSync(store, chats.instance_id, data_dir)
        total = 0
        while total < 10000 and store.pending_events():
            total += await sync.sync_once()
        return {"ok": True, "synced_events": total, "more_pending": bool(store.pending_events())}


def run_command(args):
    root = Path(args.data_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if args.command == "configure-ai":
        result = asyncio.run(configure_ai(root, args.environment_root))
    elif args.command == "knowledge-build":
        result = {"ok": True, **asyncio.run(IndexStore(root).build(args.root))}
    elif args.command == "init-agent-db":
        import sys

        if not args.stdin_credentials:
            raise AppError(ErrorCode.AUTH_FAILED)
        credentials = json.load(sys.stdin)
        result = {"ok": True, **initialize_mysql(root, credentials["root"], args.root)}
    else:
        result = asyncio.run(sync_mysql(root))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result
