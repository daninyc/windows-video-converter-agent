import asyncio
import time

from media_converter.common.errors import AppError, ErrorCode
from media_converter.rag.embedding import EmbeddingService
from media_converter.rag.ingest import lexical


def reciprocal_rank_fusion(dense, lexical_results, *, k=60, limit=20):
    candidates = {}
    for branch, points in (("dense", dense), ("lexical", lexical_results)):
        for rank, point in enumerate(points, 1):
            payload = point.payload
            value = candidates.setdefault(
                payload["chunk_id"],
                {**payload, "fusion_score": 0.0, "dense_rank": None, "lexical_rank": None},
            )
            value[branch + "_rank"] = rank
            value["fusion_score"] += 1 / (k + rank)
    return sorted(candidates.values(), key=lambda c: (-c["fusion_score"], c["chunk_id"]))[:limit]


async def retrieve(config, active, query, *, embedding=None, client=None):
    from qdrant_client import AsyncQdrantClient, models

    started = time.perf_counter()
    embedding = embedding or EmbeddingService(
        config["ollama_url"], active["embedding_model"], active["embedding_digest"]
    )
    vector = (await embedding.vectors([query]))[0]
    owned = client is None
    client = client or AsyncQdrantClient(url=config["qdrant_url"], cloud_inference=True, timeout=30)
    try:
        results = await asyncio.gather(
            client.query_points(
                active["collection"], query=vector, using="dense", limit=20, with_payload=True
            ),
            client.query_points(
                active["collection"],
                query=models.Document(
                    text=lexical(query), model="qdrant/bm25", options={"tokenizer": "multilingual"}
                ),
                using="lexical",
                limit=20,
                with_payload=True,
            ),
            return_exceptions=True,
        )
    finally:
        if owned:
            await client.close()
    stages, branches = {}, []
    for name, result in zip(("dense", "lexical"), results, strict=True):
        points = [] if isinstance(result, BaseException) else result.points
        if any(p.payload.get("knowledge_version") != active["knowledge_version"] for p in points):
            raise AppError(ErrorCode.PROTOCOL_MISMATCH)
        stages[name] = {
            "ok": not isinstance(result, BaseException),
            "count": len(points),
            "chunk_ids": [p.payload["chunk_id"] for p in points],
        }
        branches.append(points)
    if not any(stage["ok"] for stage in stages.values()):
        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
    fused = reciprocal_rank_fusion(*branches)
    stages["fusion"] = {
        "method": "RRF",
        "k": 60,
        "count": len(fused),
        "seconds": time.perf_counter() - started,
    }
    return fused, stages
