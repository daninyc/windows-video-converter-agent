import argparse
import asyncio
import json
import sys
from pathlib import Path


def main():
    # JSON subprocess pipes use UTF-8 even on a Chinese Windows code page.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    kind = sys.argv.pop(1)
    if kind == "mcp":
        from media_converter.mcp_server import main

        main()
    elif kind == "reranker":
        from media_converter.rag.reranker_worker import main

        main()
    elif kind == "document":
        from media_converter.tools.document_worker import main

        main()
    elif kind in {"index", "doctor"}:
        parser = argparse.ArgumentParser()
        parser.add_argument("--data-dir", required=True, type=Path)
        parser.add_argument("--root", type=Path)
        args = parser.parse_args()
        if kind == "index":
            from media_converter.rag.index_store import IndexStore

            result = asyncio.run(IndexStore(args.data_dir).build(args.root))
        else:
            from media_converter.services.health import HealthService

            result = asyncio.run(HealthService(args.data_dir).inspect())
        print(json.dumps(result, ensure_ascii=False), flush=True)
    else:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
