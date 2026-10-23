import asyncio
import os
import time
from pathlib import Path


def filesystem_path(path):
    """Use Windows extended paths for validated component I/O, without changing OS policy."""
    text = os.path.abspath(path)
    if os.name == "nt" and not text.startswith("\\\\?\\"):
        text = "\\\\?\\UNC\\" + text[2:] if text.startswith("\\\\") else "\\\\?\\" + text
    return Path(text)


async def sharing_retry(action, *, timeout=3):
    """Bounded retry for Windows sharing/access races; never change permissions or targets."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            return action()
        except PermissionError as error:
            if getattr(error, "winerror", None) not in {5, 32, 33} or time.monotonic() >= deadline:
                raise
            await asyncio.sleep(0.05)
