import asyncio
import json
import time
from pathlib import Path

from media_converter.agent.deepseek_adapter import DeepSeekAdapter
from media_converter.agent.tool_dedup import ToolDedup
from media_converter.agent.tool_dispatcher import ToolDispatcher
from media_converter.agent.turn_runner import TurnRunner
from media_converter.common.errors import AppError, ErrorCode
from media_converter.mcp_client import MCPConnection
from media_converter.services.config import ConfigService
from media_converter.storage.conversations import ConversationStore
from media_converter.storage.mysql_sync import MySQLSync


class AgentService:
    def __init__(
        self, store, data_dir, emit=lambda event: None, *, adapter=None, mcp=None, proposals=None
    ):
        self.chats = ConversationStore(store)
        self.data_dir = Path(data_dir)
        self.emit = emit
        self.adapter = adapter or DeepSeekAdapter(ConfigService(data_dir))
        self.mcp = mcp or MCPConnection(data_dir)
        self.dispatcher, self.dedup = ToolDispatcher(), ToolDedup()
        self.proposals = proposals
        self.online_slots = asyncio.Semaphore(5)
        self.conversation_locks = {}
        self.tasks = {}
        self.closed = False
        self.cancelled = set()
        self.sync_task = None

    async def submit(self, conversation_id, text, settings, reference_ids=None):
        if self.closed:
            raise AppError(ErrorCode.INVALID_STATE)
        if sum(not task.done() for task in self.tasks.values()) >= 128:
            raise AppError(ErrorCode.QUEUE_FULL)
        turn = await asyncio.to_thread(
            self.chats.begin, conversation_id, text, settings, reference_ids
        )
        self.emit({"kind": "state", "context": turn.context, "state": "QUEUED"})
        self.tasks[turn.context.turn_id] = asyncio.create_task(self._run(turn))
        return turn

    async def _run(self, turn):
        context = turn.context
        lock = self.conversation_locks.setdefault(context.conversation_id, asyncio.Lock())
        runner = None
        try:
            async with asyncio.timeout(max(0, context.deadline_at - time.time())):
                async with lock, self.online_slots:
                    turn = turn.model_copy(update={"state": "RUNNING"})
                    await asyncio.to_thread(self.chats.save_turn, turn)
                    self.emit({"kind": "state", "context": context, "state": "RUNNING"})
                    runner = TurnRunner(
                        self.chats,
                        self.adapter,
                        self.mcp,
                        self.dispatcher,
                        self.dedup,
                        self.data_dir,
                        self.emit,
                        self.proposals,
                        cancelled=lambda: context.turn_id in self.cancelled or self.closed,
                    )
                    usage, models = await runner.execute(turn)
                    if context.turn_id in self.cancelled or self.closed:
                        raise asyncio.CancelledError
                    turn = turn.model_copy(
                        update={
                            "state": "SUCCEEDED",
                            "usage_json": json.dumps(usage),
                            "returned_models": models,
                        }
                    )
        except asyncio.CancelledError:
            turn = turn.model_copy(update={"state": "CANCELLED", "error_code": "CANCELLED"})
        except Exception as error:
            code = (
                error.info.code
                if isinstance(error, AppError)
                else ErrorCode.TIMEOUT
                if isinstance(error, TimeoutError)
                else ErrorCode.INTERNAL_ERROR
            )
            turn = turn.model_copy(update={"state": "FAILED", "error_code": code})
            await asyncio.to_thread(
                self.chats.append,
                context.conversation_id,
                context.turn_id,
                "assistant",
                "本轮未完成：" + str(code) + "。已保留获得的内容；可缩小问题或检查依赖后重试。",
            )
        if runner:
            turn = turn.model_copy(
                update={
                    "usage_json": json.dumps(getattr(runner, "last_usage", [])),
                    "returned_models": getattr(runner, "last_models", ()),
                }
            )
        await asyncio.to_thread(self.chats.save_turn, turn)
        self.emit(
            {
                "kind": "state",
                "context": context,
                "state": turn.state,
                "error_code": turn.error_code,
            }
        )
        return turn

    async def wait(self, turn_id):
        return await asyncio.shield(self.tasks[turn_id])

    async def cancel(self, turn_id):
        task = self.tasks.get(turn_id)
        if task and not task.done():
            self.cancelled.add(turn_id)
            task.cancel()
            await asyncio.wait([task], timeout=1)
            turn = await asyncio.to_thread(self.chats.turn, turn_id)
            if turn.state in {"QUEUED", "RUNNING"}:
                turn = turn.model_copy(update={"state": "CANCELLED", "error_code": "CANCELLED"})
                await asyncio.to_thread(self.chats.save_turn, turn)
                self.emit({"kind": "state", "context": turn.context, "state": "CANCELLED"})
            return True
        return False

    def start_sync(self):
        if self.sync_task is None and (self.data_dir / "mysql.json").is_file():
            self.sync_task = asyncio.create_task(self._sync_loop())

    async def _sync_loop(self):
        sync = MySQLSync(self.chats.store, self.chats.instance_id, self.data_dir)
        while not self.closed:
            try:
                await sync.sync_once()
            except AppError:
                pass
            await asyncio.sleep(5)

    async def close(self):
        self.closed = True
        tasks = list(self.tasks.values()) + ([self.sync_task] if self.sync_task else [])
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for turn_id in self.tasks:
            turn = await asyncio.to_thread(self.chats.turn, turn_id)
            if turn.state in {"QUEUED", "RUNNING"}:
                await asyncio.to_thread(
                    self.chats.save_turn,
                    turn.model_copy(update={"state": "CANCELLED", "error_code": "CANCELLED"}),
                )
        await self.dedup.close()
        await self.dispatcher.close()
        await self.mcp.close()
