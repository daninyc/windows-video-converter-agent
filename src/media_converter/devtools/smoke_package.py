import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

from media_converter.config import application_root
from media_converter.devtools.build_windows import sha
from media_converter.services.downloads import safe_extract


def smoke(package, output, without_dev_path=True):
    root = application_root() / "artifacts/package-smoke" / uuid4().hex
    safe_extract(package, root, limit=4 * 1024**3)
    exe = root / "MediaConverter/MediaConverter.exe"
    env = dict(os.environ)
    for name in (
        "PYTHONPATH",
        "PYTHONHOME",
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "QT_PLUGIN_PATH",
        "QT_QPA_PLATFORM_PLUGIN_PATH",
        "OLLAMA_MODELS",
    ):
        env.pop(name, None)
    env["PATH"] = os.pathsep.join(
        [str(Path(os.environ["SystemRoot"]) / "System32"), os.environ["SystemRoot"]]
    )
    temporary = root / "tmp"
    temporary.mkdir()
    env.update(
        TEMP=str(temporary),
        TMP=str(temporary),
        HF_HOME=str(root / "cache/hf"),
        TORCH_HOME=str(root / "cache/torch"),
    )
    source = application_root() / "artifacts/fixtures/media/中文 空格/基础.mp4"
    copied = root / "input.mp4"
    copied.write_bytes(source.read_bytes())
    report = root / "probe.json"
    result = subprocess.run(
        [
            str(exe),
            "--package-smoke",
            "--source",
            str(copied),
            "--data-dir",
            str(root / "data"),
            "--output",
            str(report),
        ],
        env=env,
        cwd=root,
        timeout=180,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    value = json.loads(report.read_text("utf-8")) if report.exists() else {"ok": False}
    value.update(
        package_sha256=sha(package),
        exit_code=result.returncode,
        without_dev_path=without_dev_path,
        method="fresh extraction on development host; not clean Windows",
    )
    value["ok"] = bool(
        value["ok"]
        and result.returncode == 0
        and value.get("frozen")
        and value.get("qt_platform") == "windows"
        and not value.get("torch_loaded")
    )
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, indent=2, ensure_ascii=False), "utf-8")
    return value
