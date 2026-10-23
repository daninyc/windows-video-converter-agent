import asyncio
import hashlib
import json
import shutil

import pytest

from media_converter.common.errors import AppError
from media_converter.config import application_root
from media_converter.rag.embedding import EmbeddingService
from media_converter.rag.index_store import IndexStore

pytestmark = pytest.mark.integration


async def test_real_index_reuse_and_failed_build_preserves_active(ai_source, tmp_path):
    shutil.copy(ai_source / "ai-components.json", tmp_path / "ai-components.json")
    (tmp_path / "knowledge").mkdir()
    shutil.copy(ai_source / "knowledge/active.json", tmp_path / "knowledge/active.json")
    index = IndexStore(tmp_path)
    before = index.active()
    result = await index.build(application_root() / "knowledge")
    assert (
        result["reused"] and result["collection"] == before["collection"] and result["count"] == 20
    )
    config = json.loads((tmp_path / "ai-components.json").read_text())
    config["embedding_digest"] = "wrong-model-digest"
    (tmp_path / "ai-components.json").write_text(json.dumps(config))
    with pytest.raises(AppError):
        await index.build(application_root() / "knowledge")
    assert index.active() == before


async def test_real_switch_and_cancel_keeps_pinned_version(ai_source, tmp_path, monkeypatch):
    from qdrant_client import AsyncQdrantClient

    config = json.loads((ai_source / "ai-components.json").read_text())
    (tmp_path / "ai-components.json").write_text(json.dumps(config))
    (tmp_path / "knowledge").mkdir()
    shutil.copy(ai_source / "knowledge/active.json", tmp_path / "knowledge/active.json")
    corpus = tmp_path / "corpus"
    shutil.copytree(application_root() / "knowledge", corpus)

    def revise(note):
        with (corpus / "application.md").open("a", encoding="utf-8") as stream:
            stream.write(note)
        manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
        manifest["documents"][0]["content_sha256"] = hashlib.sha256(
            (corpus / "application.md").read_bytes()
        ).hexdigest()
        (corpus / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )

    revise("\n测试副本用于验证版本切换，不写入生产知识库。\n")
    index = IndexStore(tmp_path)
    old = index.active()
    client = AsyncQdrantClient(url=config["qdrant_url"], timeout=30)
    new = None
    try:
        new = await index.build(corpus)
        assert new["knowledge_version"] != old["knowledge_version"]
        assert (await client.count(old["collection"], exact=True)).count == 20
        assert (await client.count(new["collection"], exact=True)).count == 20
        baseline = {c.name for c in (await client.get_collections()).collections}
        revise("\n另一测试版本将在完成前取消。\n")
        entered = asyncio.Event()
        original = EmbeddingService.vectors

        async def pause(service, texts, **kwargs):
            values = await original(service, texts, **kwargs)
            entered.set()
            await asyncio.Event().wait()
            return values

        monkeypatch.setattr(EmbeddingService, "vectors", pause)
        task = asyncio.create_task(index.build(corpus))
        await asyncio.wait_for(entered.wait(), timeout=120)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert index.active()["collection"] == new["collection"]
        assert {c.name for c in (await client.get_collections()).collections} == baseline
    finally:
        if new and new["collection"] != old["collection"]:
            await client.delete_collection(new["collection"])
        await client.close()
