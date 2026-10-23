"""Real stdio/backend load; injected faults are kept out of throughput measurements."""

import asyncio
import hashlib
import json
import os
import signal
import time
from collections import Counter
from pathlib import Path
from uuid import uuid4

from media_converter.agent.models import Turn
from media_converter.agent.tool_dedup import ToolDedup, cache_key
from media_converter.agent.tool_dispatcher import ToolDispatcher
from media_converter.common.errors import AppError, ErrorCode
from media_converter.mcp_client import MCPConnection
from media_converter.media.models import ConversionSettings
from media_converter.rag.index_store import IndexStore
from media_converter.storage.conversations import ConversationStore
from media_converter.storage.local_store import LocalStore


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))] if ordered else 0


def write_report(path, result):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")


async def short_corpus(source, root):
    """Use the agreed short-data load, keeping the application knowledge index untouched."""
    import shutil

    shutil.copy2(source / "ai-components.json", root / "ai-components.json")
    shutil.copy2(source / "mysql.json", root / "mysql.json")
    shutil.copytree(source / "private", root / "private", dirs_exist_ok=True)
    kb = root / "corpus"
    kb.mkdir()
    text = (
        "# 压测专用真实短资料\n\n## MP4\nMP4 默认采用 H.264 视频和 AAC 音频。\n\n"
        "## MKV\nMKV 可保留多条音频及兼容字幕轨道。\n\n"
        "## 输出\n输出文件重名时自动编号，不覆盖来源。\n"
    )
    (kb / "short.md").write_text(text, "utf-8")
    manifest = {
        "version": "load-short-v1",
        "documents": [
            {
                "document_id": "short",
                "path": "short.md",
                "license": "Original test text",
                "content_sha256": hashlib.sha256((kb / "short.md").read_bytes()).hexdigest(),
                "sections": [
                    {"id": str(i), "heading": h, "source_path": "SPEC.md", "source_url": None}
                    for i, h in enumerate(("MP4", "MKV", "输出"))
                ],
            }
        ],
    }
    (kb / "manifest.json").write_text(json.dumps(manifest), "utf-8")
    return await IndexStore(root).build(kb)


async def faults(connection, context, reference):
    rows = []
    arguments = {"file_ref_id": reference}
    # Kill only the child whose identity was established by this test connection.
    killed = connection.server_pid
    os.kill(killed, signal.SIGTERM)
    await asyncio.sleep(0.2)
    starts = connection.starts
    recovered = await asyncio.gather(
        *[connection.call("read_local_file", arguments, context) for _ in range(5)]
    )
    rows.append(
        {
            "case": "real_process_death",
            "injected": True,
            "passed": all(r["ok"] for r in recovered) and connection.starts == starts + 1,
            "old_pid": killed,
            "new_pid": connection.server_pid,
        }
    )
    expired = context.model_copy(update={"deadline_at": time.time() - 1})
    try:
        await connection.call("read_local_file", arguments, expired)
        timed_out = False
    except AppError as error:
        timed_out = error.info.code == ErrorCode.TIMEOUT
    rows.append({"case": "deadline", "injected": True, "passed": timed_out})
    dispatcher = ToolDispatcher(global_limit=1, queue_limit=1, limits={"file": 1})
    entered, gate = asyncio.Event(), asyncio.Event()

    async def held():
        entered.set()
        await gate.wait()
        return await connection.call("read_local_file", arguments, context)

    first = asyncio.create_task(dispatcher.submit("file", held, time.time() + 30))
    await entered.wait()
    second = asyncio.create_task(dispatcher.submit("file", held, time.time() + 30))
    await asyncio.sleep(0)
    try:
        await dispatcher.submit("file", held, time.time() + 30)
        full = False
    except AppError as error:
        full = error.info.code == ErrorCode.QUEUE_FULL
    second.cancel()
    await asyncio.gather(second, return_exceptions=True)
    gate.set()
    value = await first
    rows.append(
        {
            "case": "queue_full_and_queued_cancel",
            "injected": True,
            "passed": full and value["ok"] and second.cancelled(),
        }
    )
    await dispatcher.close()
    dedup = ToolDedup()
    gate.clear()
    entered.clear()
    one = asyncio.create_task(dedup.call("shared", held, time.time() + 30))
    await entered.wait()
    two = asyncio.create_task(dedup.call("shared", held, time.time() + 30))
    await asyncio.sleep(0)
    one.cancel()
    await asyncio.gather(one, return_exceptions=True)
    gate.set()
    value, state = await two
    rows.append(
        {
            "case": "one_subscriber_cancel",
            "injected": True,
            "passed": value["ok"] and state == "merged" and dedup.backend_executions == 1,
        }
    )
    await dedup.close()
    gate.clear()
    entered.clear()
    dispatcher = ToolDispatcher()
    task = asyncio.create_task(dispatcher.submit("file", held, time.time() + 30))
    await entered.wait()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await dispatcher.close()
    rows.append(
        {
            "case": "inflight_cancel",
            "injected": True,
            "passed": task.cancelled() and not dispatcher.tasks,
        }
    )
    dispatcher = ToolDispatcher()
    try:
        await dispatcher.submit("file", held, time.time() + 0.1)
        expired_wait = False
    except AppError as error:
        expired_wait = error.info.code == ErrorCode.TIMEOUT
    await dispatcher.close()
    rows.append({"case": "execution_timeout", "injected": True, "passed": expired_wait})
    bad = await connection.call("read_local_file", {"file_ref_id": "unauthorized"}, context)
    rows.append(
        {
            "case": "unauthorized_reference",
            "injected": False,
            "passed": not bad["ok"] and bad["error"]["code"] == "ACCESS_DENIED",
        }
    )
    return rows


async def benchmark(data_dir, output, *, rounds=3, concurrent=100, with_faults=False):
    if rounds != 3 or concurrent != 100:
        raise AppError(ErrorCode.INVALID_ARGUMENT)
    source = Path(data_dir).resolve()
    root = Path("artifacts/mcp-load") / uuid4().hex
    root = root.resolve()
    root.mkdir(parents=True)
    active = await short_corpus(source, root)
    report = {
        "profile": "mixed",
        "rounds": [],
        "online_called": False,
        "real_backends": True,
        "corpus": {
            "chunks": active["count"],
            "version": active["knowledge_version"],
            "kind": "three original short sections",
        },
    }
    with LocalStore(root / "state.sqlite3") as store:
        chats = ConversationStore(store)
        connection = MCPConnection(root)
        contexts, refs = [], []
        for i in range(5):
            chat = chats.create(f"load-{i}")
            note = root / f"scope-{i}.txt"
            note.write_text(f"scope-{i}:" + "abcdefghijklmnopqrstuvwxyz" * 50, "utf-8")
            ref = chats.add_reference(chat.conversation_id, "file", str(note))
            turn = chats.begin(chat.conversation_id, "load", ConversionSettings())
            turn = turn.model_copy(
                update={
                    "context": turn.context.model_copy(update={"deadline_at": time.time() + 1200})
                }
            )
            chats.save_turn(Turn(context=turn.context, state="RUNNING"))
            contexts.append(turn.context)
            refs.append(ref.reference_id)
        try:
            await connection.start()
            # Warm actual model before measuring queue latency, record the cold time separately.
            cold = time.monotonic()
            warm = await connection.call("rag_search", {"query": "MP4 默认编码"}, contexts[0])
            if not warm["ok"] or warm["data"]["limited"]:
                raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
            report["cold_warmup_seconds"] = time.monotonic() - cold
            for round_no in range(rounds):
                dispatcher, dedup = ToolDispatcher(), ToolDedup()
                barrier = asyncio.Event()
                rows = []
                requests = []
                for category, total, unique in (("rag", 40, 32), ("sql", 30, 24), ("file", 30, 24)):
                    base = []
                    for n in range(unique):
                        scope = n % 5
                        name, args = {
                            "rag": (
                                "rag_search",
                                {"query": f"MP4 默认编码 {round_no}-{n}", "top_k": 1},
                            ),
                            "sql": ("lookup_technical_rules", {"limit": n + 1}),
                            "file": ("read_local_file", {"file_ref_id": refs[scope], "offset": n}),
                        }[category]
                        base.append((category, name, args, contexts[scope]))
                    requests.extend(base + base[: total - unique])

                async def submit(
                    index, request, dispatcher=dispatcher, dedup=dedup, rows=rows, barrier=barrier
                ):
                    category, name, args, ctx = request
                    await barrier.wait()
                    began = time.monotonic()
                    admitted = None
                    invocation = uuid4().hex

                    async def execute():
                        nonlocal admitted
                        admitted = time.monotonic()
                        result = await connection.call(name, args, ctx, invocation)
                        meta = result["meta"]
                        assert meta["conversation_id"] == ctx.conversation_id
                        assert (
                            meta["turn_id"] == ctx.turn_id and meta["invocation_id"] == invocation
                        )
                        return result

                    try:
                        value, state = await dedup.call(
                            cache_key(ctx, name, args, active["knowledge_version"]),
                            lambda: dispatcher.submit(category, execute, ctx.deadline_at),
                            ctx.deadline_at,
                        )
                        ok, code = value["ok"], value.get("error")
                        if category == "file" and ok:
                            scope = contexts.index(ctx)
                            expected = (f"scope-{scope}:" + "abcdefghijklmnopqrstuvwxyz" * 50)[
                                args["offset"] :
                            ]
                            ok = value["data"]["text"] == expected
                    except Exception as error:
                        ok, code, state = False, str(error), "error"
                    rows.append(
                        {
                            "index": index,
                            "category": category,
                            "ok": ok,
                            "cache_state": state,
                            "error": code,
                            "queue_ms": None if admitted is None else (admitted - began) * 1000,
                            "end_to_end_ms": (time.monotonic() - began) * 1000,
                        }
                    )

                tasks = [asyncio.create_task(submit(i, r)) for i, r in enumerate(requests)]
                before = connection.starts, connection.retries
                barrier.set()
                await asyncio.wait_for(asyncio.gather(*tasks), 240)
                elapsed = [r["end_to_end_ms"] for r in rows]
                report["rounds"].append(
                    {
                        "round": round_no + 1,
                        "submitted": len(rows),
                        "successes": sum(r["ok"] for r in rows),
                        "mix": dict(Counter(r["category"] for r in rows)),
                        "dedup": dict(Counter(r["cache_state"] for r in rows)),
                        "backend_executions": dedup.backend_executions,
                        "dispatcher": dispatcher.metrics,
                        "connection_starts": connection.starts - before[0],
                        "retries": connection.retries - before[1],
                        "p50_ms": percentile(elapsed, 0.5),
                        "p95_ms": percentile(elapsed, 0.95),
                        "calls": sorted(rows, key=lambda r: r["index"]),
                    }
                )
                write_report(output, report)
                await dedup.close()
                await dispatcher.close()
            report["faults"] = await faults(connection, contexts[0], refs[0]) if with_faults else []
        finally:
            await connection.close()
            from qdrant_client import AsyncQdrantClient

            from media_converter.services.config import read_ai_components

            client = AsyncQdrantClient(url=read_ai_components(root)["qdrant_url"])
            await client.delete_collection(active["collection"])
            await client.close()
    report["ok"] = all(
        r["successes"] == 100 and r["backend_executions"] == 80 for r in report["rounds"]
    ) and all(r["passed"] for r in report["faults"])
    write_report(output, report)
    return report
