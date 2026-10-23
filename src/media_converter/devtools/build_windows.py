import hashlib
import importlib.metadata as metadata
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from media_converter.config import AppPaths, application_root
from media_converter.media.toolchain import inspect_toolchain


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_manifest():
    root = application_root()
    paths = []
    for folder in ("src", "packaging", "knowledge"):
        paths += [
            p
            for p in (root / folder).rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
        ]
    paths += list(root.glob("requirements-*.lock")) + [root / "pyproject.toml"]
    files = {p.relative_to(root).as_posix(): sha(p) for p in sorted(paths)}
    identity = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return {"source_id": identity, "files": files}


def licenses(target, *, tools=False):
    directory = target / "THIRD_PARTY"
    directory.mkdir(exist_ok=True)
    inventory = []
    # Distribution metadata contains upstream texts, not guessed license labels.
    for dist in metadata.distributions():
        name = dist.metadata.get("Name", "")
        if not tools and name.lower() in {
            "torch",
            "transformers",
            "sentence-transformers",
            "scipy",
            "scikit-learn",
            "numpy",
            "pandas",
        }:
            continue
        entries = []
        for entry in dist.files or []:
            if ".dist-info/" in str(entry).replace("\\", "/") and any(
                part in entry.name.lower() for part in ("license", "copying", "notice", "authors")
            ):
                src = Path(dist.locate_file(entry))
                if src.is_file():
                    relative = str(entry).replace("\\", "/").split(".dist-info/", 1)[1]
                    dest = directory / name / relative
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if not dest.exists():
                        shutil.copy2(src, dest)
                    entries.append(dest.relative_to(target).as_posix())
        inventory.append(
            {
                "name": name,
                "version": dist.version,
                "license": dist.metadata.get("License-Expression") or dist.metadata.get("License"),
                "texts": entries,
            }
        )
    python_license = Path(sys.base_prefix) / "LICENSE_PYTHON.txt"
    if python_license.exists():
        shutil.copy2(python_license, directory / "Python-PSF.txt")
    natives = []
    for record in (Path(sys.base_prefix) / "conda-meta").glob("*.json"):
        value = json.loads(record.read_text("utf-8"))
        if value.get("name") not in {
            "python",
            "expat",
            "libffi",
            "openssl",
            "bzip2",
            "xz",
            "sqlite",
        }:
            continue
        source = Path(value.get("link", {}).get("source", "")) / "info/licenses"
        destination = directory / "native" / value["name"]
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        natives.append(
            {
                "name": value["name"],
                "version": value.get("version"),
                "license_from_installed_metadata": value.get("license"),
                "url": value.get("url"),
                "sha256": value.get("sha256"),
                "texts_present": destination.is_dir(),
            }
        )
    (target / "THIRD_PARTY.json").write_text(
        json.dumps(
            {
                "scope": "Build-environment superset; not all listed packages are bundled.",
                "legal_review_complete": False,
                "distributions": inventory,
                "native_runtime": natives,
            },
            indent=2,
            ensure_ascii=False,
        ),
        "utf-8",
    )


def zip_folder(folder, destination):
    with zipfile.ZipFile(
        destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=5
    ) as archive:
        for file in sorted(folder.rglob("*")):
            if file.is_file():
                archive.write(file, file.relative_to(folder.parent).as_posix())


def build(output, data_dir, components="all"):
    root = application_root()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    work = root / "artifacts/build"
    work.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    bootstrap = work / "bootstrap"
    bootstrap.mkdir(exist_ok=True)
    shutil.copy2(root / "packaging/windows_no_wmi.py", bootstrap / "sitecustomize.py")
    env["PYTHONPATH"] = str(bootstrap) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    env["PATH"] = os.pathsep.join(
        [
            str(Path(sys.executable).parent),
            str(Path(sys.base_prefix)),
            str(Path(os.environ["SystemRoot"]) / "System32"),
            os.environ["SystemRoot"],
        ]
    )
    env["PYINSTALLER_CONFIG_DIR"] = str(work / "cache")
    results = []
    for kind in [components] if components in {"core", "tools"} else ["core", "tools"]:
        source = source_manifest()
        name = "MediaConverter" if kind == "core" else "MediaConverterTools"
        log = work / (kind + ".log")
        with log.open("w", encoding="utf-8") as stream:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "PyInstaller",
                    "--noconfirm",
                    "--clean",
                    "--distpath",
                    str(output / "unpacked"),
                    "--workpath",
                    str(work / kind),
                    str(root / "packaging" / f"{kind}.spec"),
                ],
                cwd=root,
                env=env,
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=True,
            )
        folder = output / "unpacked" / name
        if source_manifest() != source:
            raise RuntimeError("Source changed during build; rebuild before testing or publishing")
        licenses(folder, tools=kind == "tools")
        if kind == "core":
            binaries = inspect_toolchain(AppPaths(Path(data_dir)))
            (folder / "bin").mkdir(exist_ok=True)
            for binary in (binaries.ffmpeg.path, binaries.ffprobe.path):
                shutil.copy2(binary, folder / "bin" / binary.name)
            shutil.copy2(
                binaries.ffmpeg.path.parent.parent / "LICENSE",
                folder / "THIRD_PARTY/FFmpeg-LICENSE",
            )
            shutil.copytree(root / "knowledge", folder / "knowledge", dirs_exist_ok=True)
        manifest = {
            **source,
            "component": kind,
            "version": "0.1.0-rc1",
            "release_ready": False,
            "release_blockers": [
                "human acceptance",
                "clean Windows",
                "live API acceptance",
                "distribution license C05 and corresponding source inventory",
            ],
        }
        (folder / "BUILD.json").write_text(json.dumps(manifest, indent=2), "utf-8")
        zip_name = (
            "MediaConverter-Windows-x64.zip"
            if kind == "core"
            else "MediaConverter-AI-Windows-x64.zip"
        )
        archive = output / zip_name
        zip_folder(folder, archive)
        results.append(
            {
                "file": zip_name,
                "sha256": sha(archive),
                "bytes": archive.stat().st_size,
                "source_id": manifest["source_id"],
            }
        )
        if kind == "tools":
            from dataclasses import asdict

            from media_converter.services.component_manifest import Artifact

            # Adjacent-only until a real Release URL exists. Never invent a public download URL.
            item = Artifact(
                "ai-tools",
                manifest["source_id"],
                "",
                sha(archive),
                archive.stat().st_size,
                "tools",
                "see THIRD_PARTY.json",
                archive=True,
                expanded_limit=sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
                + 1024**2,
                adjacent_only=True,
            )
            (output / "MediaConverter-AI-manifest.json").write_text(
                json.dumps({"artifact": asdict(item), "adjacent_only": True}, indent=2), "utf-8"
            )
    (output / "SHA256SUMS.txt").write_text(
        "\n".join(r["sha256"] + "  " + r["file"] for r in results) + "\n", "utf-8"
    )
    (output / "BUILD_REPORT.json").write_text(
        json.dumps({"artifacts": results, "release_ready": False}, indent=2), "utf-8"
    )
    return {"ok": True, "artifacts": results, "release_ready": False}
