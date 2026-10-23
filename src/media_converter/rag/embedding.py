import asyncio
import math
from contextlib import nullcontext

from media_converter.common.errors import AppError, ErrorCode


class EmbeddingService:
    def __init__(self, url, model="bge-m3:latest", expected_digest=None, *, client=None):
        self.url, self.model, self.expected_digest = url.rstrip("/"), model, expected_digest
        self.slots = asyncio.Semaphore(1)
        self.client = client

    async def identity(self, *, tokenizer=False):
        import httpx

        try:
            async with (
                nullcontext(self.client)
                if self.client
                else httpx.AsyncClient(trust_env=False, timeout=30)
            ) as client:
                tags = await client.get(self.url + "/api/tags")
                tags.raise_for_status()
                entry = next((m for m in tags.json()["models"] if m["name"] == self.model), None)
                if not entry or self.expected_digest and entry["digest"] != self.expected_digest:
                    raise AppError(ErrorCode.PROTOCOL_MISMATCH)
                result = {"model": self.model, "digest": entry["digest"]}
                if tokenizer:
                    show = await client.post(
                        self.url + "/api/show", json={"model": self.model, "verbose": True}
                    )
                    show.raise_for_status()
                    result["model_info"] = show.json()["model_info"]
                return result
        except httpx.HTTPError as error:
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE) from error

    async def vectors(self, texts, *, dimensions=1024):
        import httpx

        async with self.slots:
            await self.identity()
            try:
                async with (
                    nullcontext(self.client)
                    if self.client
                    else httpx.AsyncClient(trust_env=False, timeout=120)
                ) as client:
                    response = await client.post(
                        self.url + "/api/embed",
                        json={
                            "model": self.model,
                            "input": texts,
                            "truncate": False,
                            "keep_alive": "5m",
                            "options": {"num_thread": 4},
                        },
                    )
                    response.raise_for_status()
                vectors = response.json()["embeddings"]
                if len(vectors) != len(texts) or any(
                    len(v) != dimensions or not all(math.isfinite(x) for x in v) for v in vectors
                ):
                    raise AppError(ErrorCode.PROTOCOL_MISMATCH)
                return vectors
            except httpx.TimeoutException as error:
                raise AppError(ErrorCode.TIMEOUT) from error
            except (httpx.HTTPError, KeyError, ValueError) as error:
                raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE) from error
