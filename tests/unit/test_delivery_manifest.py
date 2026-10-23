import json
import re
import zipfile
from pathlib import Path

import pytest

from media_converter.devtools.build_windows import sha, source_manifest

pytestmark = pytest.mark.unit


def test_user_documents_and_local_links_exist():
    root = Path.cwd()
    for name in (
        "README.md",
        "docs/ACCEPTANCE.md",
        "docs/TEST_REPORT.md",
        "docs/THIRD_PARTY.md",
        "docs/SESSION_SUMMARY.md",
        "docs/RAG_REVIEW.md",
    ):
        file = root / name
        assert file.is_file(), name
        text = file.read_text("utf-8")
        for target in re.findall(r"\]\(([^)]+)\)", text):
            target = target.split("#", 1)[0].split(' "', 1)[0]
            if not target or re.match(r"[a-z]+://", target):
                continue
            assert (file.parent / target).exists(), (name, target)
    template = json.loads((root / "docs/manual-acceptance.template.json").read_text("utf-8"))
    assert template["desktop_passed"] is None and template["media_playback_passed"] is None


def test_delivery_archives_match_source_and_contain_no_user_state_or_weights():
    folder = Path("dist")
    report = folder / "BUILD_REPORT.json"
    if not report.exists():
        pytest.skip("build the candidate artifacts first")
    value = json.loads(report.read_text("utf-8"))
    assert value["release_ready"] is False
    assert len(value["artifacts"]) == 2
    current = source_manifest()["source_id"]
    for item in value["artifacts"]:
        archive = folder / item["file"]
        assert sha(archive) == item["sha256"]
        assert archive.stat().st_size == item["bytes"]
        assert item["source_id"] == current
        with zipfile.ZipFile(archive) as package:
            names = package.namelist()
            assert any(n.endswith("/THIRD_PARTY/Python-PSF.txt") for n in names)
            builds = [n for n in names if n.endswith("/BUILD.json")]
            assert len(builds) == 1
            manifest = json.loads(package.read(builds[0]))
            assert manifest["source_id"] == current and manifest["release_ready"] is False
            assert all(
                Path(n).name not in {"api.json", "mysql.json", "state.sqlite3"} for n in names
            )
            assert not any(n.endswith((".dpapi", ".gguf", ".safetensors")) for n in names)
            if item["file"] == "MediaConverter-Windows-x64.zip":
                assert not any("/_internal/torch/" in n for n in names)


def test_delivered_source_has_no_provider_key_literal():
    for folder in (Path("src"), Path("packaging")):
        for file in folder.rglob("*"):
            if not file.is_file() or file.suffix not in {".py", ".spec", ".json"}:
                continue
            text = file.read_text("utf-8")
            assert not re.search(r"sk-[A-Za-z0-9]{24,}", text), file
