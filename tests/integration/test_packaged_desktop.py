import ctypes
import json
import os
import subprocess
import time
from ctypes import wintypes as w
from pathlib import Path
from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration


def test_normal_frozen_entry_displays_main_window_and_closes_its_children(qapp):
    root = Path.cwd()
    exe = root / "dist/unpacked/MediaConverter/MediaConverter.exe"
    if not exe.is_file():
        pytest.skip("build the core first")
    data = root / "artifacts/packaged-desktop" / uuid4().hex
    data.mkdir(parents=True)
    env = dict(os.environ)
    for name in ("PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH", "CONDA_PREFIX", "VIRTUAL_ENV"):
        env.pop(name, None)
    env.update(
        PATH=os.environ["SystemRoot"] + ";" + os.environ["SystemRoot"] + "/System32",
        TEMP=str(data),
        TMP=str(data),
    )
    process = subprocess.Popen([str(exe), "--data-dir", str(data)], cwd=data, env=env)
    user = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    user.EnumWindows.argtypes = [callback_type, w.LPARAM]
    user.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
    user.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
    user.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    found = []

    @callback_type
    def visit(handle, unused):
        pid = w.DWORD()
        user.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        title = ctypes.create_unicode_buffer(260)
        user.GetWindowTextW(handle, title, 260)
        if pid.value == process.pid and title.value == "视频转换器":
            found.append(handle)
        return True

    try:
        until = time.monotonic() + 30
        while time.monotonic() < until and process.poll() is None and not found:
            user.EnumWindows(visit, 0)
            time.sleep(0.1)
        assert found, "frozen main window missing or process exited"
        time.sleep(2)
        qapp.processEvents()
        image = qapp.primaryScreen().grabWindow(int(found[0]))
        assert not image.isNull() and image.width() >= 1080
        picture = root / "artifacts/ui/packaged-desktop.png"
        picture.parent.mkdir(parents=True, exist_ok=True)
        assert image.save(str(picture))
        user.PostMessageW(found[0], 0x0010, 0, 0)
        assert process.wait(timeout=25) == 0
        evidence = {
            "ok": True,
            "without_dev_path": True,
            "entry": "normal application",
            "executable": str(exe),
            "data_dir": str(data),
            "screenshot": str(picture),
        }
        (root / "artifacts/reports/packaged-desktop.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), "utf-8"
        )
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
