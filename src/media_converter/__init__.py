"""Desktop media converter. AI dependencies are loaded only by their adapters."""

import sys

# CPython's optional WMI version probe can block indefinitely on Windows.
# platform falls back to native Windows/registry information without this module.
if sys.platform == "win32":
    sys.modules["_wmi"] = None
    if (platform_module := sys.modules.get("platform")) is not None:
        platform_module._wmi = None

__version__ = "0.1.0"
