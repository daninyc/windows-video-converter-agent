"""Windows-only private service ownership. Never stop a process by name or port alone."""

import asyncio
import ctypes
import json
import os
import re
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

from media_converter.common.errors import AppError, ErrorCode


def process_identity(pid):
    if os.name != "nt":
        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    handle = kernel.OpenProcess(0x1000, False, int(pid))
    if not handle:
        if ctypes.get_last_error() in {87, 1168}:
            return None
        raise AppError(ErrorCode.ACCESS_DENIED)
    try:
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
            return None
        times = [wintypes.FILETIME() for _ in range(4)]
        name, length = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)) or not (
            kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(length))
        ):
            raise AppError(ErrorCode.ACCESS_DENIED)
        return {
            "pid": int(pid),
            "executable": str(Path(name.value).resolve()),
            "created": (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime,
        }
    finally:
        kernel.CloseHandle(handle)


def listener_pid(port):
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise AppError(ErrorCode.INVALID_ARGUMENT)
    import socket

    class Row(ctypes.Structure):
        _fields_ = [
            (name, wintypes.DWORD)
            for name in (
                "state",
                "local_address",
                "local_port",
                "remote_address",
                "remote_port",
                "pid",
            )
        ]

    api = ctypes.WinDLL("iphlpapi").GetExtendedTcpTable
    size = wintypes.DWORD()
    api(None, ctypes.byref(size), False, 2, 3, 0)
    for _ in range(3):
        buffer = ctypes.create_string_buffer(size.value)
        result = api(buffer, ctypes.byref(size), False, 2, 3, 0)
        if result == 122:
            continue
        if result:
            raise AppError(ErrorCode.PROCESS_FAILED)
        count = wintypes.DWORD.from_buffer(buffer).value
        for index in range(count):
            row = Row.from_buffer(buffer, 4 + index * ctypes.sizeof(Row))
            if socket.ntohs(row.local_port & 0xFFFF) == port:
                return row.pid
        return None
    raise AppError(ErrorCode.PROCESS_FAILED)


def process_parents():
    class Entry(ctypes.Structure):
        _fields_ = [
            ("size", wintypes.DWORD),
            ("usage", wintypes.DWORD),
            ("pid", wintypes.DWORD),
            ("heap", ctypes.c_size_t),
            ("module", wintypes.DWORD),
            ("threads", wintypes.DWORD),
            ("parent", wintypes.DWORD),
            ("priority", wintypes.LONG),
            ("flags", wintypes.DWORD),
            ("exe", wintypes.WCHAR * 260),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise AppError(ErrorCode.ACCESS_DENIED)
    parents = {}
    try:
        entry = Entry()
        entry.size = ctypes.sizeof(entry)
        valid = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while valid:
            parents[entry.pid] = entry.parent
            valid = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    return parents


def is_descendant(pid, launcher):
    parents = process_parents()
    for _ in range(8):
        if pid == launcher:
            return True
        value = parents.get(int(pid))
        if not value:
            return False
        pid = int(value)
    return False


def terminate_recorded_tree(record):
    """Native fallback when taskkill itself hangs; bind every kill to creation time."""
    expected = {k: record[k] for k in ("pid", "executable", "created")}
    if process_identity(record["pid"]) != expected:
        raise AppError(ErrorCode.ACCESS_DENIED)
    parents = process_parents()
    identities = []
    for pid in parents:
        ancestor = pid
        for depth in range(len(parents) + 1):
            if ancestor == record["pid"]:
                identity = process_identity(pid)
                if identity and identity["created"] >= record["created"]:
                    identities.append((depth, identity))
                break
            ancestor = parents.get(ancestor)
            if not ancestor:
                break
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    for _depth, identity in sorted(identities, key=lambda pair: -pair[0]):
        handle = kernel.OpenProcess(0x1001, False, identity["pid"])
        if not handle:
            if process_identity(identity["pid"]) is None:
                continue
            raise AppError(ErrorCode.ACCESS_DENIED)
        try:
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                raise AppError(ErrorCode.ACCESS_DENIED)
            created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
            if created != identity["created"]:
                raise AppError(ErrorCode.ACCESS_DENIED)
            if not kernel.TerminateProcess(handle, 1) and process_identity(identity["pid"]):
                raise AppError(ErrorCode.PROCESS_FAILED)
        finally:
            kernel.CloseHandle(handle)


class ProcessManager:
    def __init__(self, data_dir):
        self.root = Path(data_dir).resolve()
        self.directory = self.root / "runtime/services"
        self.lock = asyncio.Lock()
        self.children = {}
        self.notify = lambda event: None

    def record_path(self, name):
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,30}", name):
            raise AppError(ErrorCode.INVALID_ARGUMENT)
        target = self.directory / (name + ".json")
        if not target.resolve().is_relative_to(self.root):
            raise AppError(ErrorCode.ACCESS_DENIED)
        return target

    def inspect(self, name):
        path = self.record_path(name)
        if not path.exists():
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
        current = process_identity(record["pid"])
        if current is None:
            return None
        if any(current[field] != record[field] for field in ("pid", "created", "executable")):
            raise AppError(ErrorCode.ACCESS_DENIED)
        return record

    async def start(self, name, executable, args, port, *, environment=None, timeout=40):
        async with self.lock:
            existing = await asyncio.to_thread(self.inspect, name)
            if existing:
                if (
                    existing["port"] != port
                    or Path(existing["executable"]) != Path(executable).resolve()
                ):
                    raise AppError(ErrorCode.ACCESS_DENIED)
                return {**existing, "reused": True}
            if await asyncio.to_thread(listener_pid, port):
                self.notify(
                    {
                        "component": name,
                        "state": "blocked",
                        "message": f"端口 {port} 已由其他服务使用。",
                        "action": "请关闭冲突服务后重试，或选择复用已有服务；不会自动结束该进程。",
                    }
                )
                raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
            path = self.record_path(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            logs = self.root / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            child_env = {
                **os.environ,
                "TEMP": str(self.root / "tmp"),
                "TMP": str(self.root / "tmp"),
                **(environment or {}),
            }
            (self.root / "tmp").mkdir(exist_ok=True)
            with (
                (logs / f"{name}.out.log").open("ab") as out,
                (logs / f"{name}.err.log").open("ab") as err,
            ):
                process = subprocess.Popen(
                    [str(Path(executable).resolve()), *map(str, args)],
                    cwd=self.root,
                    env=child_env,
                    stdin=subprocess.DEVNULL,
                    stdout=out,
                    stderr=err,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            self.children[name] = process
            try:
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    pid = await asyncio.to_thread(listener_pid, port)
                    if pid and await asyncio.to_thread(is_descendant, pid, process.pid):
                        identity = await asyncio.to_thread(process_identity, pid)
                        if (
                            not identity
                            or Path(identity["executable"]) != Path(executable).resolve()
                        ):
                            raise AppError(ErrorCode.ACCESS_DENIED)
                        record = {
                            **identity,
                            "launcher_pid": process.pid,
                            "port": port,
                            "name": name,
                            "ownership": "private",
                        }
                        path.write_text(json.dumps(record, indent=2), encoding="utf-8")
                        return {**record, "reused": False}
                    if process.poll() is not None:
                        raise AppError(ErrorCode.PROCESS_FAILED)
                    await asyncio.sleep(0.2)
                raise AppError(ErrorCode.TIMEOUT)
            except BaseException:
                if process.poll() is None:
                    await asyncio.to_thread(
                        subprocess.run,
                        ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        timeout=10,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    await asyncio.to_thread(process.wait, 5)
                raise

    async def stop(self, name, *, shutdown=None):
        async with self.lock:
            record = await asyncio.to_thread(self.inspect, name)
            if not record:
                return False
            if shutdown:
                await shutdown()
            else:
                # Recheck immediately before terminating the recorded process tree.
                if await asyncio.to_thread(process_identity, record["pid"]) != {
                    k: record[k] for k in ("pid", "executable", "created")
                }:
                    raise AppError(ErrorCode.ACCESS_DENIED)
                try:
                    result = await asyncio.to_thread(
                        subprocess.run,
                        ["taskkill.exe", "/PID", str(record["pid"]), "/T", "/F"],
                        capture_output=True,
                        timeout=10,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                except subprocess.TimeoutExpired:
                    if await asyncio.to_thread(process_identity, record["pid"]):
                        await asyncio.to_thread(terminate_recorded_tree, record)
                else:
                    if result.returncode and await asyncio.to_thread(
                        process_identity, record["pid"]
                    ):
                        raise AppError(ErrorCode.PROCESS_FAILED)
            deadline = time.monotonic() + 15
            while await asyncio.to_thread(process_identity, record["pid"]):
                if time.monotonic() > deadline:
                    raise AppError(ErrorCode.TIMEOUT)
                await asyncio.sleep(0.1)
            self.record_path(name).unlink(missing_ok=True)
            child = self.children.pop(name, None)
            if child:
                await asyncio.to_thread(child.wait, 5)
            return True
