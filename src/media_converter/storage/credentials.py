import ctypes
import getpass
import os
import re
import subprocess
from ctypes import wintypes
from pathlib import Path

from media_converter.common.context import new_id
from media_converter.common.errors import AppError, ErrorCode


class Blob(ctypes.Structure):
    _fields_ = [("length", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def protect(data: bytes, *, decrypt=False) -> bytes:
    if os.name != "nt":
        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, result = Blob(len(data), buffer), Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    if decrypt:
        ok = crypt.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)
        )
    else:
        ok = crypt.CryptProtectData(
            ctypes.byref(source), "media-converter", None, None, None, 1, ctypes.byref(result)
        )
    if not ok:
        raise AppError(ErrorCode.AUTH_FAILED)
    try:
        return ctypes.string_at(result.data, result.length)
    finally:
        ctypes.WinDLL("kernel32").LocalFree(result.data)


class CredentialStore:
    def __init__(self, directory: Path):
        self.directory = Path(directory).resolve()

    def _path(self, reference):
        if not re.fullmatch(r"[0-9a-f-]{36}", reference):
            raise AppError(ErrorCode.AUTH_FAILED)
        return self.directory / (reference + ".dpapi")

    def save(self, secret: str) -> str:
        if not secret or len(secret) > 16384:
            raise AppError(ErrorCode.INVALID_ARGUMENT)
        encrypted = protect(secret.encode("utf-8"))
        self.directory.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [
                "icacls",
                str(self.directory),
                "/inheritance:r",
                "/grant:r",
                f"{getpass.getuser()}:(OI)(CI)F",
            ],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
        if result.returncode:
            raise AppError(ErrorCode.ACCESS_DENIED)
        reference = new_id()
        self._path(reference).write_bytes(encrypted)
        return reference

    def read(self, reference: str | None) -> str:
        if reference is None:
            raise AppError(ErrorCode.AUTH_FAILED)
        try:
            return protect(self._path(reference).read_bytes(), decrypt=True).decode("utf-8")
        except (OSError, UnicodeError) as error:
            raise AppError(ErrorCode.AUTH_FAILED) from error

    def clear(self, reference: str | None):
        if reference:
            self._path(reference).unlink(missing_ok=True)
