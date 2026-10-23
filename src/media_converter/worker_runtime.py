"""One command policy for source execution and separately packaged AI workers."""

import json
import sys
from pathlib import Path

from media_converter.common.errors import AppError, ErrorCode
from media_converter.config import application_root

MODULES = {
    "mcp": "media_converter.mcp_server",
    "reranker": "media_converter.rag.reranker_worker",
    "document": "media_converter.tools.document_worker",
}


def installed_worker(data_dir):
    root = Path(data_dir).resolve()
    exe = root / "components/tools/MediaConverterTools/MediaConverterTools.exe"
    marker = root / "components/installed/ai-tools.json"
    if not exe.is_file() or not marker.is_file():
        return None
    from media_converter.services.downloads import sha256_file

    try:
        files = json.loads(marker.read_text("utf-8"))["files"]
        if files["MediaConverterTools/MediaConverterTools.exe"] != sha256_file(exe):
            raise AppError(ErrorCode.FILE_CHANGED)
    except (OSError, KeyError, ValueError) as error:
        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE) from error
    return exe


def worker_command(kind, data_dir=None):
    if not getattr(sys, "frozen", False):
        return [sys.executable, "-m", MODULES[kind]]
    if Path(sys.executable).stem == "MediaConverterTools":
        return [sys.executable, kind]
    exe = installed_worker(data_dir or application_root() / "data")
    if not exe:
        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
    return [str(exe), kind]


async def build_index(data_dir, knowledge_root):
    if not getattr(sys, "frozen", False) or Path(sys.executable).stem == "MediaConverterTools":
        from media_converter.rag.index_store import IndexStore

        return await IndexStore(data_dir).build(knowledge_root)
    from media_converter.common.process import capture_process

    exe = installed_worker(data_dir)
    if not exe:
        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
    output = await capture_process(
        exe, ["index", "--data-dir", str(data_dir), "--root", str(knowledge_root)], timeout=900
    )
    return json.loads(output)
