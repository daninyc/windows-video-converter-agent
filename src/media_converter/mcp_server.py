import argparse
import asyncio
import json
import os
from pathlib import Path

from media_converter.storage.conversations import ConversationReader
from media_converter.tools.registry import ToolRegistry


async def serve(data_dir, components_dir=None):
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import CallToolResult, ListToolsResult, TextContent

    key = bytes.fromhex(os.environ.pop("MEDIA_CONVERTER_MCP_KEY"))
    instance = os.environ.pop("MEDIA_CONVERTER_MCP_INSTANCE")
    host_pid = int(os.environ.pop("MEDIA_CONVERTER_MCP_HOST"))
    lease = data_dir / "runtime" / f"mcp-{instance}.json"
    lease.parent.mkdir(parents=True, exist_ok=True)
    with lease.open("x", encoding="utf-8") as file:
        # Windows venv may insert a Python redirector between the Host and the server.
        json.dump(
            {
                "instance": instance,
                "pid": os.getpid(),
                "parent_pid": os.getppid(),
                "host_pid": host_pid,
            },
            file,
        )
    registry = ToolRegistry(
        components_dir or data_dir, ConversationReader(data_dir / "state.sqlite3"), key
    )

    async def list_tools(context, parameters):
        return ListToolsResult(tools=registry.catalog())

    async def call_tool(context, parameters):
        value = await registry.call(parameters.name, parameters.arguments or {}, context.meta or {})
        return CallToolResult(
            content=[TextContent(text=json.dumps(value, ensure_ascii=False))],
            structuredContent=value,
            isError=not value["ok"],
        )

    server = Server(
        "media-converter",
        version="0.1.0",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        get_tool_input_schema=lambda name: next(
            (t.input_schema for t in registry.catalog() if t.name == name), None
        ),
    )
    try:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        await registry.close()
        lease.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--components-dir", type=Path)
    args = parser.parse_args()
    asyncio.run(serve(args.data_dir.resolve(), args.components_dir))


if __name__ == "__main__":
    main()
