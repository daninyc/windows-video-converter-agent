import asyncio
import time

import pytest

from media_converter.agent.tool_dedup import ToolDedup

pytestmark = pytest.mark.unit


async def test_shared_cancellation_versions_cache_and_failure():
    dedup, gate, runs = ToolDedup(capacity=1), asyncio.Event(), []

    async def backend():
        runs.append(True)
        await gate.wait()
        return {"ok": True, "data": {"x": 1}}

    a = asyncio.create_task(dedup.call("v1", backend, time.time() + 5))
    b = asyncio.create_task(dedup.call("v1", backend, time.time() + 5))
    await asyncio.sleep(0.02)
    a.cancel()
    await asyncio.gather(a, return_exceptions=True)
    gate.set()
    value, state = await b
    assert value["ok"] and state == "merged" and len(runs) == 1
    assert (await dedup.call("v1", backend, time.time() + 5))[1] == "hit"
    await dedup.call("v2", backend, time.time() + 5)
    assert "v1" not in dedup.cache
    await dedup.call("bad", lambda: asyncio.sleep(0, result={"ok": False}), time.time() + 5)
    assert "bad" not in dedup.cache
    await dedup.close()
