import subprocess
import sys
from pathlib import Path

import pytest

from media_converter.common.errors import AppError
from media_converter.services.process_manager import (
    ProcessManager,
    process_identity,
    terminate_recorded_tree,
)

pytestmark = pytest.mark.unit


async def test_native_timeout_fallback_stops_only_recorded_tree(tmp_path, monkeypatch):
    parent = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import subprocess,sys,time;"
            "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
            "print(p.pid,flush=True);time.sleep(60)",
        ],
        stdout=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time;time.sleep(60)"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        child_pid = int(parent.stdout.readline())
        identity = process_identity(parent.pid)
        assert identity and process_identity(child_pid)
        with pytest.raises(AppError):
            terminate_recorded_tree({**identity, "created": identity["created"] + 1})
        assert parent.poll() is None and unrelated.poll() is None
        manager = ProcessManager(tmp_path)
        monkeypatch.setattr(manager, "inspect", lambda name: identity)
        marker = manager.record_path("owned")
        marker.parent.mkdir(parents=True)
        marker.write_text("{}", "utf-8")

        def hung_taskkill(*args, **kwargs):
            raise subprocess.TimeoutExpired("taskkill", 10)

        monkeypatch.setattr(
            "media_converter.services.process_manager.subprocess.run", hung_taskkill
        )
        assert await manager.stop("owned")
        parent.wait(timeout=5)
        assert process_identity(child_pid) is None
        assert unrelated.poll() is None and not marker.exists()
    finally:
        for process in [parent, unrelated]:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
        parent.stdout.close()


def test_source_startup_avoids_optional_wmi_probe():
    assert sys.modules.get("_wmi") is None
    import platform

    assert platform.machine()
    assert Path("packaging/windows_no_wmi.py").is_file()
