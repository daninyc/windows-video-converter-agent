import asyncio
import time

import pytest

from media_converter.agent.tool_dispatcher import ToolDispatcher
from media_converter.common.errors import AppError, ErrorCode

pytestmark = pytest.mark.unit


async def test_fair_categories_capacity_cancel_and_deadline():
    dispatcher = ToolDispatcher(global_limit=2, queue_limit=2, limits={"rag": 1, "sql": 1})
    gate = asyncio.Event()

    async def slow():
        await gate.wait()
        return "rag"

    first = asyncio.create_task(dispatcher.submit("rag", slow, time.time() + 5))
    await asyncio.sleep(0)
    waiting = [
        asyncio.create_task(dispatcher.submit("rag", slow, time.time() + 5)) for _ in range(2)
    ]
    await asyncio.sleep(0)
    with pytest.raises(AppError) as error:
        await dispatcher.submit("sql", slow, time.time() + 5)
    assert error.value.info.code == ErrorCode.QUEUE_FULL
    waiting[0].cancel()
    await asyncio.gather(waiting[0], return_exceptions=True)
    assert (
        await dispatcher.submit("sql", lambda: asyncio.sleep(0, result="sql"), time.time() + 1)
        == "sql"
    )
    with pytest.raises(AppError):
        await dispatcher.submit("sql", slow, time.time() - 1)
    gate.set()
    await asyncio.gather(first, waiting[1])
    assert dispatcher.metrics["peak_active"] <= 2
    await dispatcher.close()
