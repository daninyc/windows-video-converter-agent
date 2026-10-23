"""Real packaged host -> packaged worker -> private native services; no Python in PATH."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from media_converter.devtools.build_windows import sha
from media_converter.services.downloads import safe_extract

pytestmark = pytest.mark.integration


def test_frozen_host_prepares_and_checks_private_ai_from_verified_local_cache():
    root = Path.cwd()
    packages = root / "dist"
    if not (packages / "MediaConverter-AI-manifest.json").exists():
        pytest.skip("build both packages first")
    staging = root / "artifacts/package-ai" / uuid4().hex
    safe_extract(packages / "MediaConverter-Windows-x64.zip", staging, limit=4 * 1024**3)
    host = staging / "MediaConverter"
    for name in ("MediaConverter-AI-manifest.json", "MediaConverter-AI-Windows-x64.zip"):
        shutil.copy2(packages / name, host / name)
    # This native MySQL build cannot initialize a Chinese storage path on the test host.
    # Keep the app data path ASCII; media/document input paths remain independent.
    # Qdrant's native Gridstore also requires a short storage root on this Windows host.
    data = root / "artifacts" / ("rv-" + uuid4().hex[:8])
    data.mkdir()
    report = staging / "prepare.json"
    temp = staging / "tmp"
    temp.mkdir()
    env = dict(os.environ)
    for key in (
        "PYTHONPATH",
        "PYTHONHOME",
        "CONDA_PREFIX",
        "VIRTUAL_ENV",
        "QT_PLUGIN_PATH",
        "QT_QPA_PLATFORM_PLUGIN_PATH",
        "OLLAMA_MODELS",
    ):
        env.pop(key, None)
    env.update(
        PATH=os.environ["SystemRoot"] + ";" + os.environ["SystemRoot"] + "/System32",
        TEMP=str(temp),
        TMP=str(temp),
    )
    completed = subprocess.run(
        [
            str(host / "MediaConverter.exe"),
            "--devtools",
            "prepare",
            "--components",
            "ai",
            "--mode",
            "private",
            "--environment-root",
            str(root / "environment"),
            "--data-dir",
            str(data),
            "--output",
            str(report),
        ],
        cwd=staging,
        env=env,
        timeout=1200,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    result = json.loads(report.read_text("utf-8")) if report.exists() else {"ok": False}
    result.update(
        {
            "exit_code": completed.returncode,
            "packaged_host": str(host / "MediaConverter.exe"),
            "packaged_data": str(data),
            "without_dev_path": True,
            "core_sha256": sha(packages / "MediaConverter-Windows-x64.zip"),
            "tools_sha256": sha(packages / "MediaConverter-AI-Windows-x64.zip"),
            "verified_model_cache_reused": True,
            "clean_windows": False,
            "native_mysql_unicode_data_directory_verified": False,
        }
    )
    destination = root / "artifacts/reports/ai-package.json"
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    assert completed.returncode == 0 and result["ok"], result
    assert {r["component"] for r in result["checks"] if r["ok"]} == {
        "video",
        "mcp",
        "knowledge",
        "mysql",
        "files",
    }
    assert (data / "components/installed/ai-tools.json").is_file()
    assert not list((data / "runtime/services").glob("*.json"))
