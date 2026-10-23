"""Windows process sampling; shared local services are explicitly labelled."""

import ctypes
import os
import threading
import time
from ctypes import wintypes as w


class Entry(ctypes.Structure):
    _fields_ = [
        ("size", w.DWORD),
        ("usage", w.DWORD),
        ("pid", w.DWORD),
        ("heap", ctypes.c_size_t),
        ("module", w.DWORD),
        ("threads", w.DWORD),
        ("parent", w.DWORD),
        ("priority", w.LONG),
        ("flags", w.DWORD),
        ("name", w.WCHAR * 260),
    ]


class Memory(ctypes.Structure):
    _fields_ = [("size", w.DWORD), ("faults", w.DWORD)] + [
        (name, ctypes.c_size_t)
        for name in (
            "peak_rss",
            "rss",
            "peak_paged",
            "paged",
            "peak_nonpaged",
            "nonpaged",
            "page",
            "peak_page",
        )
    ]


def processes():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
    kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = [
        w.HANDLE,
        ctypes.POINTER(Entry),
    ]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    snap = kernel.CreateToolhelp32Snapshot(2, 0)
    result = []
    entry = Entry()
    entry.size = ctypes.sizeof(entry)
    try:
        valid = kernel.Process32FirstW(snap, ctypes.byref(entry))
        while valid:
            result.append((entry.pid, entry.parent, entry.name))
            valid = kernel.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snap)
    return result


def sample(pid):
    kernel, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
    kernel.OpenProcess.restype = w.HANDLE
    kernel.GetProcessTimes.argtypes = [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4
    kernel.CloseHandle.argtypes = [w.HANDLE]
    psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.POINTER(Memory), w.DWORD]
    handle = kernel.OpenProcess(0x410, False, pid)
    if not handle:
        return None
    try:
        times = [w.FILETIME() for _ in range(4)]
        mem = Memory()
        mem.size = ctypes.sizeof(mem)
        if not kernel.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
            return None
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(mem), mem.size):
            return None
        cpu = sum((t.dwHighDateTime << 32) + t.dwLowDateTime for t in times[2:]) / 1e7
        return cpu, mem.rss
    finally:
        kernel.CloseHandle(handle)


class ResourceMonitor:
    def __init__(self):
        self.stop = threading.Event()
        self.rows = {}
        self.peak_total_rss = 0
        self.thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self):
        self.started = time.monotonic()
        self.thread.start()
        return self

    def _run(self):
        while not self.stop.is_set():
            entries = processes()
            owned = {os.getpid()}
            for _ in range(8):
                owned.update(pid for pid, parent, _ in entries if parent in owned)
            total = 0
            for pid, _, name in entries:
                shared = name.lower() in {
                    "mysqld.exe",
                    "qdrant.exe",
                    "ollama.exe",
                    "ollama_llama_server.exe",
                }
                if pid not in owned and not shared:
                    continue
                value = sample(pid)
                if value is None:
                    continue
                cpu, rss = value
                row = self.rows.setdefault(
                    pid,
                    {
                        "pid": pid,
                        "name": name,
                        "shared_service": shared,
                        "first_cpu": cpu,
                        "cpu_seconds": 0,
                        "peak_rss_bytes": 0,
                    },
                )
                row["cpu_seconds"] = max(row["cpu_seconds"], cpu - row["first_cpu"])
                row["peak_rss_bytes"] = max(row["peak_rss_bytes"], rss)
                total += rss
            self.peak_total_rss = max(self.peak_total_rss, total)
            self.stop.wait(0.25)

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(timeout=2)

    def report(self):
        return {
            "interval_ms": 250,
            "wall_seconds": time.monotonic() - self.started,
            "peak_observed_total_rss_bytes": self.peak_total_rss,
            "note": (
                "Sampled CPU deltas; short-lived processes may be missed. "
                "Shared services include unrelated work."
            ),
            "processes": [
                {k: v for k, v in row.items() if k != "first_cpu"} for row in self.rows.values()
            ],
        }
