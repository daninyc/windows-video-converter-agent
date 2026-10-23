import asyncio
import hashlib
import json
import os
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from media_converter.common.errors import AppError, ErrorCode
from media_converter.rag.embedding import EmbeddingService
from media_converter.rag.ingest import CHUNK_VERSION, actual_tokenizer, lexical, load_chunks
from media_converter.services.config import read_ai_components


class IndexStore:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.active_path = self.data_dir / "knowledge/active.json"

    def active(self):
        try:
            value = json.loads(self.active_path.read_text(encoding="utf-8"))
            if value["chunk_version"] != CHUNK_VERSION or value["dimensions"] != 1024:
                raise AppError(ErrorCode.PROTOCOL_MISMATCH)
            return value
        except (OSError, KeyError, ValueError) as error:
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE) from error

    async def build(self, root):
        from qdrant_client import AsyncQdrantClient, models

        config = read_ai_components(self.data_dir)
        embedding = EmbeddingService(
            config["ollama_url"], config["embedding_model"], config["embedding_digest"]
        )
        identity = await embedding.identity(tokenizer=True)
        tokenizer, tokenizer_hash = await asyncio.to_thread(
            actual_tokenizer, identity["model_info"]
        )
        manifest, chunks = await asyncio.to_thread(load_chunks, root, tokenizer)
        version = hashlib.sha256(
            json.dumps(
                {
                    "chunks": chunks,
                    "model": identity["digest"],
                    "tokenizer": tokenizer_hash,
                    "chunk_version": CHUNK_VERSION,
                },
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        client = AsyncQdrantClient(url=config["qdrant_url"], cloud_inference=True, timeout=30)
        collection = "vc_kb_" + version[:16] + "_" + uuid4().hex[:8]
        created, published = False, False
        try:
            if self.active_path.exists():
                current = self.active()
                if current["knowledge_version"] == version and (
                    await client.count(current["collection"], exact=True)
                ).count == len(chunks):
                    return {**current, "reused": True}
            await client.create_collection(
                collection,
                vectors_config={
                    "dense": models.VectorParams(size=1024, distance=models.Distance.COSINE)
                },
                sparse_vectors_config={
                    "lexical": models.SparseVectorParams(modifier=models.Modifier.IDF)
                },
            )
            created = True
            for start in range(0, len(chunks), 8):
                batch = chunks[start : start + 8]
                vectors = await embedding.vectors([chunk["text"] for chunk in batch])
                points = [
                    models.PointStruct(
                        id=str(uuid5(NAMESPACE_URL, chunk["chunk_id"])),
                        vector={
                            "dense": vector,
                            "lexical": models.Document(
                                text=lexical(chunk["text"]),
                                model="qdrant/bm25",
                                options={"tokenizer": "multilingual"},
                            ),
                        },
                        payload={**chunk, "knowledge_version": version},
                    )
                    for chunk, vector in zip(batch, vectors, strict=True)
                ]
                await client.upsert(collection, points, wait=True)
            if (await client.count(collection, exact=True)).count != len(chunks):
                raise AppError(ErrorCode.OUTPUT_INVALID)
            active = {
                "schema_version": 1,
                "knowledge_version": version,
                "collection": collection,
                "dimensions": 1024,
                "embedding_model": identity["model"],
                "embedding_digest": identity["digest"],
                "tokenizer_hash": tokenizer_hash,
                "chunk_version": CHUNK_VERSION,
                "count": len(chunks),
                "manifest_version": manifest["version"],
            }
            # Queries pin a collection; switching keeps the old one usable.
            self.active_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.active_path.with_suffix(".json." + uuid4().hex + ".partial")
            temporary.write_text(json.dumps(active, indent=2), encoding="utf-8")
            os.replace(temporary, self.active_path)
            published = True
            return {**active, "reused": False}
        except asyncio.CancelledError:
            raise
        except AppError:
            raise
        except Exception as error:
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE) from error
        finally:
            if created and not published:
                await client.delete_collection(collection)
            await client.close()
