import asyncio
import json
import os
import secrets
import time
from pathlib import Path

from media_converter.agent.mcp_context import signed_metadata
from media_converter.common.context import new_id
from media_converter.common.errors import AppError, ErrorCode


def connection_error(error):
    if isinstance(error, AppError):
        return error
    for child in getattr(error, "exceptions", ()):
        found = connection_error(child)
        if found.info.code != ErrorCode.MCP_DISCONNECTED:
            return found
    return AppError(ErrorCode.MCP_DISCONNECTED)


class MCPConnection:
    """One owner per transport; read-only disconnects may retry once."""

    def __init__(self, data_dir, *, components_dir=None):
        self.data_dir = Path(data_dir).resolve()
        self.components_dir = Path(components_dir).resolve() if components_dir else self.data_dir
        self.key = secrets.token_bytes(32)
        self.client = self.owner = self.ready = None
        self.start_lock = asyncio.Lock()
        self.close_event = asyncio.Event()
        self.tools = []
        self.protocol_version = self.server_pid = None
        self.starts = self.retries = 0
        self.closed = False
        self.active = set()

    async def start(self):
        async with self.start_lock:
            if self.closed:
                raise AppError(ErrorCode.MCP_DISCONNECTED)
            if self.owner and not self.owner.done() and not self.close_event.is_set():
                ready = self.ready
            else:
                if self.owner:
                    await asyncio.gather(self.owner, return_exceptions=True)
                self.ready = ready = asyncio.get_running_loop().create_future()
                self.close_event = asyncio.Event()
                self.owner = asyncio.create_task(self._own(ready, self.close_event))
        # One cancelled caller must not cancel a startup shared by other callers.
        async with asyncio.timeout(20):
            await asyncio.shield(ready)

    async def _own(self, ready, stop):
        try:
            from mcp import Client, StdioServerParameters
        except ImportError as error:
            self.last_failure = error
            ready.set_exception(AppError(ErrorCode.DEPENDENCY_UNAVAILABLE))
            return

        marker = new_id()
        lease = self.data_dir / "runtime" / f"mcp-{marker}.json"
        environment = dict(os.environ)
        for name, relative in {
            "TEMP": "tmp",
            "TMP": "tmp",
            "HF_HOME": "cache/huggingface",
            "HF_HUB_CACHE": "cache/huggingface/hub",
            "TORCH_HOME": "cache/torch",
            "XDG_CACHE_HOME": "cache",
        }.items():
            folder = self.components_dir / relative
            folder.mkdir(parents=True, exist_ok=True)
            environment[name] = str(folder)
        environment["HF_HUB_DISABLE_TELEMETRY"] = "1"
        environment["MEDIA_CONVERTER_MCP_KEY"] = self.key.hex()
        environment["MEDIA_CONVERTER_MCP_INSTANCE"] = marker
        environment["MEDIA_CONVERTER_MCP_HOST"] = str(os.getpid())
        from media_converter.worker_runtime import worker_command

        try:
            command = worker_command("mcp", self.components_dir)
        except AppError as error:
            ready.set_exception(error)
            return
        parameters = StdioServerParameters(
            command=command[0],
            args=[
                *command[1:],
                "--data-dir",
                str(self.data_dir),
                "--components-dir",
                str(self.components_dir),
            ],
            env=environment,
            cwd=self.data_dir,
        )
        client = None
        try:
            async with Client(parameters, read_timeout_seconds=125) as client:
                if client.protocol_version != "2026-07-28":
                    raise AppError(ErrorCode.PROTOCOL_MISMATCH)
                listed = await client.list_tools()
                identity = json.loads(lease.read_text(encoding="utf-8"))
                if identity["instance"] != marker or identity["host_pid"] != os.getpid():
                    raise AppError(ErrorCode.ACCESS_DENIED)
                self.server_pid = identity["pid"]
                self.client, self.tools = client, listed.tools
                self.protocol_version = client.protocol_version
                self.starts += 1
                if not ready.done():
                    ready.set_result(None)
                await stop.wait()
        except BaseException as error:
            self.last_failure = error
            if not ready.done():
                ready.set_exception(connection_error(error))
        finally:
            if self.client is client:
                self.client = None
                self.server_pid = None
            lease.unlink(missing_ok=True)

    async def _discard(self, client):
        async with self.start_lock:
            if self.client is client:
                self.close_event.set()
                if self.owner:
                    await asyncio.gather(self.owner, return_exceptions=True)

    async def call(self, name, arguments, context, invocation_id=None):
        try:
            from mcp.shared.exceptions import MCPError
            from mcp_types import CONNECTION_CLOSED, REQUEST_TIMEOUT
        except ImportError as error:
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE) from error

        from media_converter.tools.schemas import SCHEMAS

        if name not in SCHEMAS:
            raise AppError(ErrorCode.INVALID_ARGUMENT)
        metadata = signed_metadata(self.key, context, invocation_id or new_id(), name, arguments)
        task = asyncio.current_task()
        self.active.add(task)
        try:
            async with asyncio.timeout(max(0, context.deadline_at - time.time())):
                for attempt in range(2):
                    client = None
                    try:
                        await self.start()
                        client = self.client
                        if client is None:
                            raise AppError(ErrorCode.MCP_DISCONNECTED)
                        result = await client.call_tool(name, arguments, meta=metadata)
                        data = result.structured_content
                        if not isinstance(data, dict) or not isinstance(data.get("ok"), bool):
                            raise AppError(ErrorCode.PROTOCOL_MISMATCH)
                        return data
                    except asyncio.CancelledError:
                        raise
                    except MCPError as error:
                        if error.code == REQUEST_TIMEOUT:
                            raise AppError(ErrorCode.TIMEOUT) from error
                        if error.code != CONNECTION_CLOSED:
                            raise AppError(ErrorCode.PROTOCOL_MISMATCH) from error
                    except AppError as error:
                        if error.info.code != ErrorCode.MCP_DISCONNECTED:
                            raise
                    except Exception:
                        pass
                    if client is not None:
                        await self._discard(client)
                    if attempt or self.closed:
                        raise AppError(ErrorCode.MCP_DISCONNECTED)
                    self.retries += 1
                    await asyncio.sleep(0.05)
        except TimeoutError as error:
            raise AppError(ErrorCode.TIMEOUT) from error
        finally:
            self.active.discard(task)

    async def model_tools(self):
        await self.start()
        return [
            {
                "type": "function",
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            }
            for t in self.tools
        ]

    async def close(self):
        self.closed = True
        tasks = [task for task in self.active if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        async with self.start_lock:
            self.close_event.set()
            if self.owner:
                await asyncio.gather(self.owner, return_exceptions=True)
