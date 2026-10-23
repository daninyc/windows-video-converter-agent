from types import SimpleNamespace

import pytest

from media_converter.rag.retrieval import reciprocal_rank_fusion

pytestmark = pytest.mark.unit


def test_rrf_retains_independent_ranks_and_deduplicates():
    def p(key):
        return SimpleNamespace(payload={"chunk_id": key})

    rows = reciprocal_rank_fusion([p("a"), p("b")], [p("b"), p("c")])
    assert [row["chunk_id"] for row in rows] == ["b", "a", "c"]
    assert rows[0]["dense_rank"] == 2 and rows[0]["lexical_rank"] == 1
