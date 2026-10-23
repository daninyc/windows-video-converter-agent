import asyncio
import time
from collections import deque
from dataclasses import dataclass

from media_converter.common.errors import AppError, ErrorCode


@dataclass
class Pending:
    category: str
    factory: object
    deadline: float
    enqueued: float
    future: asyncio.Future


class ToolDispatcher:
    def __init__(self, *, global_limit=16, queue_limit=128, limits=None):
        self.limits = limits or {"rag": 1, "sql": 4, "file": 2, "search": 2}
        self.global_limit, self.queue_limit = global_limit, queue_limit
        self.queues = {key: deque() for key in self.limits}
        self.rotation = deque(self.limits)
        self.active = dict.fromkeys(self.limits, 0)
        self.tasks = set()
        self.metrics = {
            "submitted": 0,
            "executed": 0,
            "peak_active": 0,
            "peak_queue": 0,
            "rejected": 0,
            "category_peak": dict.fromkeys(self.limits, 0),
        }
        self.closed = False

    async def submit(self, category, factory, deadline):
        if self.closed or category not in self.queues:
            raise AppError(ErrorCode.INVALID_STATE)
        if sum(map(len, self.queues.values())) >= self.queue_limit:
            self.metrics["rejected"] += 1
            raise AppError(ErrorCode.QUEUE_FULL)
        future = asyncio.get_running_loop().create_future()
        pending = Pending(category, factory, deadline, time.time(), future)
        self.queues[category].append(pending)
        self.metrics["submitted"] += 1
        self.metrics["peak_queue"] = max(
            self.metrics["peak_queue"], sum(map(len, self.queues.values()))
        )
        self._pump()

        def expire_queue():
            if pending in self.queues[category]:
                self.queues[category].remove(pending)
                if not future.done():
                    future.set_exception(AppError(ErrorCode.TIMEOUT))
                self._pump()

        queue_timer = asyncio.get_running_loop().call_later(120, expire_queue)
        try:
            async with asyncio.timeout(max(0, deadline - time.time())):
                return await future
        except TimeoutError as error:
            raise AppError(ErrorCode.TIMEOUT) from error
        finally:
            queue_timer.cancel()
            if pending in self.queues[category]:
                self.queues[category].remove(pending)
            self._pump()

    def _pump(self):
        while sum(self.active.values()) < self.global_limit:
            selected = None
            for _ in range(len(self.rotation)):
                category = self.rotation[0]
                self.rotation.rotate(-1)
                if self.queues[category] and self.active[category] < self.limits[category]:
                    selected = self.queues[category].popleft()
                    break
            if selected is None:
                return
            if selected.future.done():
                continue
            if min(selected.deadline, selected.enqueued + 120) <= time.time():
                selected.future.set_exception(AppError(ErrorCode.TIMEOUT))
                continue
            self.active[selected.category] += 1
            self.metrics["category_peak"][selected.category] = max(
                self.metrics["category_peak"][selected.category], self.active[selected.category]
            )
            self.metrics["peak_active"] = max(
                self.metrics["peak_active"], sum(self.active.values())
            )
            task = asyncio.create_task(self._run(selected))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

    async def _run(self, pending):
        worker = asyncio.create_task(pending.factory())
        pending.future.add_done_callback(lambda f: worker.cancel() if f.cancelled() else None)
        self.metrics["executed"] += 1
        try:
            tool_limit = {"rag": 120, "sql": 10, "file": 30, "search": 20}.get(
                pending.category, 120
            )
            async with asyncio.timeout(max(0, min(tool_limit, pending.deadline - time.time()))):
                value = await worker
            if not pending.future.done():
                pending.future.set_result(value)
        except asyncio.CancelledError:
            pending.future.cancel()
        except Exception as error:
            if not pending.future.done():
                pending.future.set_exception(
                    AppError(ErrorCode.TIMEOUT) if isinstance(error, TimeoutError) else error
                )
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
            self.active[pending.category] -= 1
            self._pump()

    async def close(self):
        self.closed = True
        for queue in self.queues.values():
            for pending in queue:
                pending.future.cancel()
            queue.clear()
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
