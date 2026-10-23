import asyncio
import threading
from collections.abc import Callable, Coroutine
from concurrent.futures import CancelledError, Future
from dataclasses import dataclass
from typing import Any, Literal

from media_converter.common.context import CallContext, new_id
from media_converter.common.errors import AppError, ErrorCode, ErrorInfo, normalize_error


@dataclass(frozen=True)
class RuntimeEvent:
    task_id: str
    context: CallContext
    state: Literal["succeeded", "failed", "cancelled"]
    data: Any = None
    error: ErrorInfo | None = None


class AsyncRuntime:
    """Factories run on this loop; create network clients inside those factories, never on Qt."""

    def __init__(self, on_event: Callable[[RuntimeEvent], None]):
        self._on_event = on_event
        self._gate = threading.RLock()
        self._handles: dict[str, tuple[Future, CallContext]] = {}
        self._closed = False
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="media-async-runtime")
        self._thread.start()
        if not self._ready.wait(5):
            raise AppError(ErrorCode.TIMEOUT)

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    async def _invoke(self, factory):
        return await factory()

    def submit(self, factory: Callable[[], Coroutine], context: CallContext | None = None) -> str:
        with self._gate:
            if self._closed:
                raise AppError(ErrorCode.INVALID_STATE)
            task_id = new_id()
            future = asyncio.run_coroutine_threadsafe(self._invoke(factory), self._loop)
            self._handles[task_id] = (future, context or CallContext())
            future.add_done_callback(lambda completed: self._finished(task_id, completed))
            return task_id

    def _finished(self, task_id, future):
        with self._gate:
            handle = self._handles.pop(task_id, None)
        if handle is None:
            return
        _, context = handle
        try:
            event = RuntimeEvent(task_id, context, "succeeded", data=future.result())
        except CancelledError:
            event = RuntimeEvent(task_id, context, "cancelled")
        except Exception as error:
            event = RuntimeEvent(task_id, context, "failed", error=normalize_error(error).info)
        self._on_event(event)

    def cancel(self, task_id: str) -> bool:
        with self._gate:
            handle = self._handles.get(task_id)
            return handle[0].cancel() if handle else False

    @staticmethod
    async def run_blocking(function, *args):
        # Cancelling an await cannot stop native threads; callers must bound I/O or use a process.
        return await asyncio.to_thread(function, *args)

    async def _shutdown(self, before_close=None):
        if before_close is not None:
            await before_close()
        current = asyncio.current_task()
        pending = [task for task in asyncio.all_tasks() if task is not current]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await self._loop.shutdown_asyncgens()
        await self._loop.shutdown_default_executor(timeout=5)

    def close(self, before_close=None):
        with self._gate:
            if self._closed:
                return
            self._closed = True
            shutdown = asyncio.run_coroutine_threadsafe(self._shutdown(before_close), self._loop)
        try:
            shutdown.result(timeout=10)
        except TimeoutError as error:
            raise AppError(ErrorCode.TIMEOUT) from error
        finally:
            if shutdown.done():
                self._loop.call_soon_threadsafe(self._loop.stop)
                self._thread.join(timeout=5)
        if self._thread.is_alive():
            raise AppError(ErrorCode.TIMEOUT)
