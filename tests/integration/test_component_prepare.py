import asyncio
import hashlib
import json
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from media_converter.common.errors import AppError
from media_converter.services.component_manifest import Artifact, inventory
from media_converter.services.downloads import Downloader
from media_converter.services.preparer import SetupService

pytestmark = pytest.mark.integration


@pytest.fixture
def server():
    payload = b"controlled-component" * 100000
    ranges = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            start = int(self.headers.get("Range", "bytes=0-").split("=")[1].split("-")[0])
            ranges.append(start)
            self.send_response(206 if start else 200)
            self.send_header("Content-Length", str(len(payload) - start))
            self.send_header("ETag", '"fixed"')
            if start:
                self.send_header(
                    "Content-Range", f"bytes {start}-{len(payload) - 1}/{len(payload)}"
                )
            self.end_headers()
            try:
                self.wfile.write(payload[start:])
            except (ConnectionError, OSError):
                pass

        def log_message(self, *args):
            pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=http.serve_forever)
    worker.start()
    item = Artifact(
        "sample",
        "1",
        f"http://127.0.0.1:{http.server_port}/sample",
        hashlib.sha256(payload).hexdigest(),
        len(payload),
        "sample.bin",
        "MIT",
    )
    try:
        yield item, ranges
    finally:
        http.shutdown()
        worker.join()
        http.server_close()


async def test_cancel_resume_verify_install_reuse_and_tamper(tmp_path, server):
    item, ranges = server
    downloader = Downloader(tmp_path)
    cancelled = False

    def progress(event):
        nonlocal cancelled
        if event["state"] == "downloading":
            cancelled = True

    with pytest.raises(asyncio.CancelledError):
        await downloader.install(item, cancel=lambda: cancelled, emit=progress)
    assert list((tmp_path / "downloads").glob("*.partial"))
    assert not (tmp_path / "components/sample.bin").exists()
    path = await downloader.install(item)
    assert ranges[0] == 0 and ranges[1] > 0
    assert await downloader.install(item) == path and len(ranges) == 2
    path.write_bytes(b"tampered")
    with pytest.raises(AppError):
        await downloader.install(item)


async def test_wrong_hash_never_installs(tmp_path, server):
    item, _ = server
    with pytest.raises(AppError):
        await Downloader(tmp_path).install(replace(item, digest="0" * 64))
    assert not (tmp_path / "components/sample.bin").exists()


async def test_commit_interrupted_before_rename_resumes_without_download(
    tmp_path, server, monkeypatch
):
    import os

    item, ranges = server
    original = os.rename

    def interrupted(*args):
        raise OSError("controlled interruption before commit")

    monkeypatch.setattr(os, "rename", interrupted)
    with pytest.raises(AppError):
        await Downloader(tmp_path).install(item)
    assert not (tmp_path / "components/sample.bin").exists()
    monkeypatch.setattr(os, "rename", original)
    assert (await Downloader(tmp_path).install(item)).exists()
    assert len(ranges) == 1


async def test_install_disk_full_is_actionable(tmp_path, server, monkeypatch):
    import errno
    import shutil

    item, _ = server

    def full(*args):
        raise OSError(errno.ENOSPC, "controlled disk full")

    monkeypatch.setattr(shutil, "copyfile", full)
    with pytest.raises(AppError) as error:
        await Downloader(tmp_path).install(item)
    assert error.value.info.code == "DISK_FULL"
    assert not (tmp_path / "components/sample.bin").exists()


async def test_transient_windows_lock_during_commit_is_retried(tmp_path, server, monkeypatch):
    import os

    item, _ = server
    original, calls = os.rename, []

    def locked(*args):
        calls.append(True)
        if len(calls) < 3:
            error = PermissionError("controlled Windows sharing conflict")
            error.winerror = 32
            raise error
        return original(*args)

    monkeypatch.setattr(os, "rename", locked)
    assert (await Downloader(tmp_path).install(item)).exists()
    assert len(calls) == 3


async def test_real_official_qdrant_archive_and_repeat(tmp_path):
    # Real archive previously downloaded from the pinned official GitHub release, not a fixture.
    item = next(a for a in inventory() if a.name == "qdrant")
    source = Path("environment/downloads/qdrant.zip").resolve()
    result = await Downloader(tmp_path).install(item, cached=source)
    assert list(result.rglob("qdrant.exe"))
    assert await Downloader(tmp_path).install(item) == result
    marker = json.loads((tmp_path / "components/installed/qdrant.json").read_text("utf-8"))
    assert marker["source"] == item.url and marker["digest"] == item.digest


async def test_missing_release_worker_is_explicit(tmp_path, monkeypatch):
    import sys

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    events = []
    service = SetupService(tmp_path)
    with pytest.raises(AppError):
        await service.prepare(emit=events.append)
    assert any(e["component"] == "ai-worker" and e["state"] == "missing" for e in events)
    assert not (tmp_path / "downloads").exists()
