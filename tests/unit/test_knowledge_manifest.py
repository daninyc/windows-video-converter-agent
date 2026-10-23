import hashlib
import json

import pytest

from media_converter.config import application_root

pytestmark = pytest.mark.unit


def test_knowledge_provenance_and_frozen_evaluation_structure():
    root = application_root() / "knowledge"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    sections = set()
    for document in manifest["documents"]:
        raw = (root / document["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == document["content_sha256"]
        assert document["license"] and document["reviewed_at"]
        for section in document["sections"]:
            assert section["id"] not in sections
            sections.add(section["id"])
            assert (application_root() / section["source_path"].split("#")[0]).is_file()
    rows = [
        json.loads(line) for line in (root / "eval.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len({row["id"] for row in rows}) == len(rows)
    assert sum(r["answerable"] for r in rows) >= 20
    assert sum(not r["answerable"] for r in rows) >= 5
    assert all(r["frozen_before_retrieval"] and r["human_review_status"] == "pending" for r in rows)
    assert all(set(r["expected_sections"]) <= sections for r in rows)
