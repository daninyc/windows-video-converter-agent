import json
import zipfile

import pytest

from media_converter.common.context import CallContext
from media_converter.common.logging import JsonlLogger
from media_converter.services.diagnostics import Diagnostics


def test_export_whitelist_excludes_sentinels_database_documents_and_paths(tmp_path):
    sentinel = "SENTINEL_PRIVATE_KEY_DO_NOT_EXPORT"
    path = r"C:\Users\private-person\secret-video.mp4"
    (tmp_path / "private").mkdir()
    for name in (
        "api.json",
        "state.sqlite3",
        "private/credential.bin",
        "original.txt",
        "movie.mp4",
    ):
        (tmp_path / name).write_text(sentinel + path, "utf-8")
    with (tmp_path / "events.jsonl").open("w", encoding="utf-8") as stream:
        JsonlLogger(stream).event(
            "tool.finished",
            CallContext(),
            tool_name="rag_search",
            state="succeeded",
            execution_ms=10,
            secret=sentinel,
            document=sentinel,
            path=path,
        )
        stream.write(
            json.dumps(
                {
                    "event": "tool.finished",
                    "trace_id": path,
                    "fields": {
                        "tool_name": sentinel,
                        "state": path,
                        "error_code": sentinel,
                        sentinel: path,
                        "args": {"api_key": sentinel},
                        "unknown": path,
                    },
                }
            )
            + "\n"
        )
        stream.write(json.dumps({"event": sentinel, "fields": {"state": sentinel}}) + "\n")
        stream.write("broken json\n")
    output = tmp_path / "export.zip"
    result = Diagnostics(tmp_path).export(output)
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {"context.json", "events.jsonl"}
        content = "\n".join(archive.read(n).decode() for n in archive.namelist())
        assert sentinel not in content and path not in content and str(tmp_path) not in content
        assert "rag_search" in content and "execution_ms" in content
    assert result["records"] == 2
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        Diagnostics(tmp_path).export(output)
    assert output.read_bytes() == before and not list(tmp_path.glob("*.partial"))


def test_export_handles_missing_log_and_bounds_tail(tmp_path):
    service = Diagnostics(tmp_path)
    assert service.collect()[1] == []
    with (tmp_path / "events.jsonl").open("w", encoding="utf-8") as stream:
        for _ in range(1200):
            stream.write('{"event":"runtime.finished","fields":{"state":"failed"}}\n')
    assert len(service.collect()[1]) == 1000
