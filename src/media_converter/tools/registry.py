import asyncio
import time

from pydantic import ValidationError

from media_converter.agent.mcp_context import validate_metadata
from media_converter.common.context import CallContext
from media_converter.common.errors import AppError, ErrorCode, result_envelope
from media_converter.common.logging import JsonlLogger
from media_converter.services.config import ConfigService
from media_converter.tools.local_files import LocalFiles
from media_converter.tools.schemas import DESCRIPTIONS, SCHEMAS
from media_converter.tools.web_search import WebSearch


class ToolRegistry:
    def __init__(self, data_dir, reader, key, *, logger=None):
        self.data_dir, self.reader, self.key = data_dir, reader, key
        self.logger = logger or JsonlLogger()
        self.files = LocalFiles(reader.path)
        self.web = WebSearch(ConfigService(data_dir))
        self.rag = None
        self.mysql = None

    def catalog(self):
        from mcp.types import Tool

        return [
            Tool(
                name=name,
                description=DESCRIPTIONS[name],
                inputSchema=model.model_json_schema(),
                outputSchema={
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                },
            )
            for name, model in SCHEMAS.items()
        ]

    async def call(self, name, arguments, meta):
        call_context = CallContext()
        started = time.monotonic()
        try:
            if name not in SCHEMAS:
                raise AppError(ErrorCode.INVALID_ARGUMENT)
            context, invocation_id = validate_metadata(self.key, self.reader, meta, name, arguments)
            call_context = CallContext(
                instance_id=context.instance_id,
                conversation_id=context.conversation_id,
                turn_id=context.turn_id,
                trace_id=context.trace_id,
                invocation_id=invocation_id,
            )
            parsed = SCHEMAS[name].model_validate(arguments)
            async with asyncio.timeout(max(0, context.deadline_at - time.time())):
                if name == "read_local_file":
                    data = await self.files.read(parsed, context)
                    sources = [
                        {
                            "file_ref_id": parsed.file_ref_id,
                            "locations": [p["location"] for p in data["locations"]],
                        }
                    ]
                elif name == "search_web":
                    data = await self.web.search(parsed, context)
                    sources = data["results"]
                elif name == "rag_search":
                    if self.rag is None:
                        from media_converter.rag.service import RAGService

                        self.rag = RAGService(self.data_dir)
                    data = await self.rag.search(parsed.query, parsed.top_k)
                    sources = [item["source"] for item in data["chunks"]]
                else:
                    if self.mysql is None:
                        from media_converter.tools.mysql_queries import MySQLQueries

                        self.mysql = MySQLQueries(self.data_dir, self.reader)
                    data = await self.mysql.query(name, parsed, context)
                    sources = data.get("sources", [])
            envelope = result_envelope(
                call_context,
                data=data,
                sources=tuple(sources),
                data_version=data.get("knowledge_version"),
            )
        except ValidationError:
            envelope = result_envelope(call_context, error=AppError(ErrorCode.INVALID_ARGUMENT))
        except Exception as error:
            envelope = result_envelope(call_context, error=error)
        self.logger.event(
            "tool.finished",
            call_context,
            tool_name=name,
            state="succeeded" if envelope["ok"] else "failed",
            execution_ms=round((time.monotonic() - started) * 1000),
            error_code=envelope["error"]["code"] if envelope["error"] else None,
        )
        return envelope

    async def close(self):
        await self.files.close()
        if self.rag:
            await self.rag.close()
        if self.mysql:
            await self.mysql.close()
