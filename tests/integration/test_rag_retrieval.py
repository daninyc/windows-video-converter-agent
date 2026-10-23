import json

import pytest

from media_converter.rag.index_store import IndexStore
from media_converter.rag.retrieval import retrieve

pytestmark = pytest.mark.integration


async def test_real_two_branches_and_fusion_versions(ai_source, record_property):
    config = json.loads((ai_source / "ai-components.json").read_text())
    active = IndexStore(ai_source).active()
    fused, stages = await retrieve(config, active, "libx264 mov_text -map 字幕")
    assert stages["dense"]["ok"] and stages["lexical"]["ok"]
    assert stages["dense"]["count"] and stages["lexical"]["count"]
    assert all(c["knowledge_version"] == active["knowledge_version"] for c in fused)
    assert any(c["dense_rank"] and c["lexical_rank"] for c in fused)
    record_property("retrieval_stages", json.dumps(stages))
