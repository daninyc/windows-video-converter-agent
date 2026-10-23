"""Use Python's native Windows metadata fallback in our frozen/build processes."""
import sys

if sys.platform == "win32":
    sys.modules["_wmi"] = None
    if (platform_module := sys.modules.get("platform")) is not None:
        platform_module._wmi = None
