import json
import time

import pytest

from media_converter.config import application_root
from media_converter.rag.service import RAGService

pytestmark = pytest.mark.integration


async def test_real_complete_rag_cpu_worker_cold_warm_and_close(ai_source, record_property):
    service = RAGService(ai_source)
    started = time.perf_counter()
    try:
        cold = await service.search("本应用 MP4 默认的视频和音频编码是什么？")
        cold_seconds = time.perf_counter() - started
        started = time.perf_counter()
        warm = await service.search("WebM 使用什么音频编码？")
        warm_seconds = time.perf_counter() - started
        assert not cold["limited"] and cold["chunks"][0]["section_id"] == "mp4"
        assert cold["retrieval_stages"]["rerank"]["executed"]
        assert (
            warm["retrieval_stages"]["rerank"]["worker_pid"]
            == cold["retrieval_stages"]["rerank"]["worker_pid"]
        )
        previous_pid = service.reranker.process.pid
        service.reranker.process.kill()
        await service.reranker.process.wait()
        recovered, recovery = await service.reranker.score("MP4 编码", cold["chunks"][:2])
        assert recovered and recovery["executed"] and recovery["worker_pid"] != previous_pid
        assert service.index.active()["knowledge_version"] == cold["knowledge_version"]
        evidence = {
            "cold_seconds": cold_seconds,
            "warm_seconds": warm_seconds,
            "cold": cold,
            "warm": warm,
            "worker_crash_recovery": recovery,
        }
        path = application_root() / "artifacts/reports/agent-rag-acceptance.json"
        path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
        record_property("evidence", str(path))
    finally:
        await service.close()
    assert service.reranker.process is None
