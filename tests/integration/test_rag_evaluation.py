import hashlib
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def test_fixed_rag_report_has_real_stage_and_boundary_evidence():
    path = Path("artifacts/reports/rag-eval.json")
    if not path.exists():
        pytest.skip("run eval-rag first")
    result = json.loads(path.read_text("utf-8"))
    assert (
        result["dataset_sha256"]
        == hashlib.sha256(Path("knowledge/eval.jsonl").read_bytes()).hexdigest()
    )
    assert result["top5_hits_out_of_20"]["hybrid_rerank"] >= 17
    assert result["outside_insufficient"] == 5 and len(result["cases"]) == 25
    assert not result["threshold_tuned_on_dataset"] and not result["online_search_used"]
    cases = [
        json.loads(line) for line in Path("knowledge/eval.jsonl").read_text("utf-8").splitlines()
    ]
    assert result["human_review_complete"] == all(
        c["human_review_status"] == "confirmed" for c in cases
    )
    assert result["automatic_gate_passed"]
