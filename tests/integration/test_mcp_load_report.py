import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.stress]


def test_real_load_counts_limits_pairing_and_fault_terminals():
    path = Path("artifacts/reports/mcp-real-local.json")
    if not path.exists():
        pytest.skip("run real-local benchmark first")
    result = json.loads(path.read_text("utf-8"))
    assert result["ok"] and result["real_backends"] and not result["online_called"]
    assert len(result["rounds"]) == 3
    for row in result["rounds"]:
        assert row["submitted"] == row["successes"] == 100
        assert row["mix"] == {"rag": 40, "sql": 30, "file": 30}
        assert row["backend_executions"] == row["dispatcher"]["executed"] == 80
        assert sum(row["dedup"].values()) == 100
        assert row["dedup"].get("merged", 0) + row["dedup"].get("hit", 0) == 20
        assert row["dispatcher"]["peak_active"] <= 16
        assert row["dispatcher"]["peak_queue"] <= 128
        for category, limit in {"rag": 1, "sql": 4, "file": 2, "search": 2}.items():
            assert row["dispatcher"]["category_peak"][category] <= limit
        assert row["connection_starts"] == row["retries"] == 0
    assert all(row["passed"] for row in result["faults"])
    assert result["resources"]["peak_observed_total_rss_bytes"] > 0
