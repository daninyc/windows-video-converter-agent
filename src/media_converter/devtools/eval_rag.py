import hashlib
import json
import time
from pathlib import Path

from media_converter.rag.index_store import IndexStore
from media_converter.rag.retrieval import retrieve
from media_converter.rag.service import Reranker
from media_converter.services.config import read_ai_components


async def evaluate(dataset, data_dir, output):
    dataset = Path(dataset)
    cases = [json.loads(line) for line in dataset.read_text("utf-8").splitlines() if line.strip()]
    assert len(cases) == 25 and sum(c["answerable"] for c in cases) == 20
    before = hashlib.sha256(dataset.read_bytes()).hexdigest()
    config = read_ai_components(data_dir)
    active = IndexStore(data_dir).active()
    reranker = Reranker(config)
    rows = []
    try:
        for case in cases:
            started = time.perf_counter()
            fused, stages = await retrieve(config, active, case["question"])
            ranked, rerank = await reranker.score(case["question"], fused)
            branches = {
                "dense": sorted(
                    [c for c in fused if c["dense_rank"]], key=lambda c: c["dense_rank"]
                ),
                "lexical": sorted(
                    [c for c in fused if c["lexical_rank"]], key=lambda c: c["lexical_rank"]
                ),
                "hybrid": fused,
                "hybrid_rerank": ranked,
            }

            def candidate(c):
                value = {
                    k: c.get(k)
                    for k in (
                        "chunk_id",
                        "document_id",
                        "section_id",
                        "section",
                        "source_path",
                        "source_url",
                        "rerank_score",
                    )
                }
                value.update(
                    {
                        key: c["source"].get(key)
                        for key in ("source_path", "source_url", "evidence_path")
                    }
                )
                return value

            def hit(values, case=case):
                return any(
                    c["document_id"] in case["expected_document_ids"]
                    and c["section_id"] in case["expected_sections"]
                    for c in values[:5]
                )

            rows.append(
                {
                    **case,
                    "candidates": {k: [candidate(c) for c in v[:5]] for k, v in branches.items()},
                    "top5_hit": {k: hit(v) for k, v in branches.items()},
                    "evidence_sufficient": bool(
                        ranked
                        and ranked[0]["rerank_score"] >= config.get("relevance_threshold", 0.5)
                    ),
                    "stages": {**stages, "rerank": rerank},
                    "seconds": time.perf_counter() - started,
                }
            )
    finally:
        await reranker.close()
    assert before == hashlib.sha256(dataset.read_bytes()).hexdigest()
    scores = {
        k: sum(r["top5_hit"][k] for r in rows if r["answerable"])
        for k in ("dense", "lexical", "hybrid", "hybrid_rerank")
    }
    outside = [r for r in rows if not r["answerable"]]
    result = {
        "profile": "fixed-rag-evaluation",
        "dataset_sha256": before,
        "knowledge_version": active["knowledge_version"],
        "embedding_digest": active["embedding_digest"],
        "reranker_revision": config["reranker_revision"],
        "top5_hits_out_of_20": scores,
        "outside_insufficient": sum(not r["evidence_sufficient"] for r in outside),
        "automatic_gate_passed": scores["hybrid_rerank"] >= 17
        and all(not r["evidence_sufficient"] for r in outside),
        "human_review_complete": all(c["human_review_status"] == "confirmed" for c in cases),
        "threshold_tuned_on_dataset": False,
        "online_search_used": False,
        "cases": rows,
    }
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False), "utf-8")
    return result
