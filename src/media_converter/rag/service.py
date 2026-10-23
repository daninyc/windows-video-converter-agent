import asyncio
import json
import math
import os

from media_converter.common.context import new_id
from media_converter.common.errors import AppError, ErrorCode
from media_converter.common.process import terminate_owned
from media_converter.rag.index_store import IndexStore
from media_converter.rag.retrieval import retrieve
from media_converter.services.config import read_ai_components


class Reranker:
    def __init__(self, config):
        self.config = config
        self.process = None
        self.lock = asyncio.Lock()
        self.readiness = None

    async def _start(self):
        if self.process and self.process.returncode is None:
            return
        environment = {
            **os.environ,
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "TOKENIZERS_PARALLELISM": "false",
        }
        from media_converter.worker_runtime import worker_command

        self.process = await asyncio.create_subprocess_exec(
            *worker_command("reranker"),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=environment,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
        self.process.stdin.write(
            (
                json.dumps(
                    {
                        "model_path": self.config["reranker_path"],
                        "files": self.config["reranker_files"],
                        "revision": self.config["reranker_revision"],
                    }
                )
                + "\n"
            ).encode()
        )
        await self.process.stdin.drain()
        self.readiness = json.loads(await self.process.stdout.readline())
        if not self.readiness.get("ready"):
            raise AppError(ErrorCode.PROCESS_FAILED)

    async def score(self, query, chunks):
        if not chunks:
            return [], {"executed": False, "reason": "no_candidates"}
        async with self.lock:
            try:
                async with asyncio.timeout(120):
                    await self._start()
                    request_id = new_id()
                    self.process.stdin.write(
                        (
                            json.dumps(
                                {
                                    "request_id": request_id,
                                    "query": query,
                                    "texts": [c["text"] for c in chunks],
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        ).encode()
                    )
                    await self.process.stdin.drain()
                    result = json.loads(await self.process.stdout.readline())
                    scores = result["scores"]
                    if (
                        result["request_id"] != request_id
                        or len(scores) != len(chunks)
                        or not all(math.isfinite(s) for s in scores)
                    ):
                        raise AppError(ErrorCode.PROTOCOL_MISMATCH)
                    ranked = sorted(
                        (
                            {**chunk, "rerank_score": score}
                            for chunk, score in zip(chunks, scores, strict=True)
                        ),
                        key=lambda c: -c["rerank_score"],
                    )
                    return ranked, {
                        "executed": True,
                        "count": len(scores),
                        "seconds": result["seconds"],
                        "worker_pid": self.process.pid,
                        "load": self.readiness,
                        "revision": self.config["reranker_revision"],
                        "max_tokens": result["max_tokens"],
                        "truncated_pairs": result["truncated_pairs"],
                    }
            except asyncio.CancelledError:
                await self.close()
                raise
            except Exception as error:
                await self.close()
                if isinstance(error, AppError):
                    raise
                raise AppError(
                    ErrorCode.TIMEOUT
                    if isinstance(error, TimeoutError)
                    else ErrorCode.PROCESS_FAILED
                ) from error

    async def close(self):
        if self.process:
            await terminate_owned(self.process)
            self.process = None


class RAGService:
    def __init__(self, data_dir):
        self.config = read_ai_components(data_dir)
        self.index = IndexStore(data_dir)
        self.reranker = Reranker(self.config)
        self.slots = asyncio.Semaphore(1)
        self.http = self.qdrant = self.embedding = None

    async def search(self, query, top_k=5):
        if not query.strip() or len(query) > 2000 or not 1 <= top_k <= 5:
            raise AppError(ErrorCode.INVALID_ARGUMENT)
        async with self.slots:
            active = self.index.active()
            if self.http is None:
                import httpx
                from qdrant_client import AsyncQdrantClient

                from media_converter.rag.embedding import EmbeddingService

                self.http = httpx.AsyncClient(trust_env=False, timeout=120)
                self.qdrant = AsyncQdrantClient(
                    url=self.config["qdrant_url"], cloud_inference=True, timeout=30
                )
                self.embedding = EmbeddingService(self.config["ollama_url"], client=self.http)
            # A new index can pin a different model; verify its identity on every actual query.
            self.embedding.model = active["embedding_model"]
            self.embedding.expected_digest = active["embedding_digest"]
            fused, stages = await retrieve(
                self.config, active, query, embedding=self.embedding, client=self.qdrant
            )
            ranked, rerank = await self.reranker.score(query, fused)
            stages["rerank"] = rerank
            complete = (
                stages["dense"]["ok"] and stages["lexical"]["ok"] and rerank.get("executed", False)
            )
            threshold = self.config.get("relevance_threshold", 0.5)
            sufficient = bool(complete and ranked and ranked[0]["rerank_score"] >= threshold)
            return {
                "chunks": ranked[:top_k],
                "knowledge_version": active["knowledge_version"],
                "retrieval_stages": stages,
                "limited": not complete,
                "evidence_sufficient": sufficient,
                "relevance_policy": {
                    "threshold": threshold,
                    "basis": "initial heuristic; manual calibration pending tickets050",
                },
            }

    async def close(self):
        await self.reranker.close()
        if self.qdrant:
            await self.qdrant.close()
            self.qdrant = None
        if self.http:
            await self.http.aclose()
            self.http = None
