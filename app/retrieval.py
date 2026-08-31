"""Async hybrid retrieval with BM25, dense vectors, ACL filters, and Pinecone fallback."""

import asyncio
import hashlib
import json
import logging
import math
import re
from pathlib import Path
from typing import Any

from langsmith import traceable
from rank_bm25 import BM25Okapi

from app.config import get_settings
from app.models import Evidence, User

logger = logging.getLogger(__name__)


def tokenize(text: str) -> list[str]:
    """Create stable lowercase terms for BM25 and the deterministic local vectorizer."""

    return re.findall(r"[a-z0-9]+", text.lower())


def local_embedding(text: str, dimensions: int = 256) -> list[float]:
    """Deterministic feature hashing fallback; not a semantic production embedding."""
    vector = [0.0] * dimensions
    for token in tokenize(text):
        digest = hashlib.sha256(token.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        vector[index] += 1 if digest[4] % 2 else -1
    norm = math.sqrt(sum(value * value for value in vector)) or 1
    return [value / norm for value in vector]


def cosine(left: list[float], right: list[float]) -> float:
    """Calculate cosine similarity for vectors already normalized to unit length."""

    return sum(a * b for a, b in zip(left, right))


class HybridRetriever:
    """Load document fixtures once and serve authorized weighted hybrid searches."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.settings = get_settings()
        self.data_dir = data_dir or Path("data/documents")
        self.documents: list[dict[str, Any]] = []
        self._bm25: BM25Okapi | None = None
        self._embeddings: list[list[float]] = []
        self._loaded = False
        self._lock = asyncio.Lock()

    async def load(self) -> None:
        """Build local sparse and dense indexes exactly once under an async lock."""

        async with self._lock:
            if self._loaded:
                return
            self.documents = [json.loads(path.read_text(encoding="utf-8")) for path in self.data_dir.glob("*.json")]
            corpus = [tokenize(f"{doc['title']} {doc['content']}") for doc in self.documents]
            self._bm25 = BM25Okapi(corpus)
            self._embeddings = [local_embedding(" ".join(tokens)) for tokens in corpus]
            self._loaded = True

    @traceable(name="hybrid-retrieval", run_type="retriever")
    async def search(
        self, query: str, user: User, filters: dict[str, str] | None = None, top_k: int | None = None
    ) -> list[Evidence]:
        """Retrieve, ACL-filter, fuse, rank, and attribute evidence for one query."""

        await self.load()
        filters = filters or {}
        top_k = min(top_k or self.settings.retrieval_top_k, 20)
        query_tokens = tokenize(query)
        sparse = await asyncio.to_thread(self._bm25.get_scores, query_tokens)  # type: ignore[union-attr]
        local_query_vector = await asyncio.to_thread(local_embedding, query)
        dense = [max(0.0, cosine(local_query_vector, vector)) for vector in self._embeddings]
        # Pinecone is the managed dense-search path. Local vectors make the POC runnable offline.
        if self.settings.pinecone_api_key:
            try:
                if not self.settings.openai_api_key:
                    raise RuntimeError("OPENAI_API_KEY is required for Pinecone query embeddings")
                from langchain_openai import OpenAIEmbeddings
                from pinecone import Pinecone

                query_vector = await OpenAIEmbeddings(
                    model=self.settings.embedding_model,
                    api_key=self.settings.openai_api_key,
                ).aembed_query(query)
                index = Pinecone(api_key=self.settings.pinecone_api_key).Index(
                    self.settings.pinecone_index
                )
                metadata_filter = {
                    **filters,
                    "access_level": {"$in": user.access_levels},
                }
                response = await asyncio.to_thread(
                    index.query,
                    namespace=self.settings.pinecone_namespace,
                    vector=query_vector,
                    top_k=min(top_k * 3, 50),
                    filter=metadata_filter,
                    include_metadata=False,
                )
                cloud_scores = {match["id"]: float(match["score"]) for match in response["matches"]}
                dense = [max(0.0, cloud_scores.get(doc["id"], 0.0)) for doc in self.documents]
            except Exception as exc:
                # A cloud outage degrades to the local dense index; the API remains available.
                logger.warning("pinecone_query_failed_using_local_fallback", exc_info=exc)
        sparse_max = max(sparse, default=1) or 1
        dense_max = max(dense, default=1) or 1

        ranked: list[tuple[float, dict[str, Any]]] = []
        for index, doc in enumerate(self.documents):
            metadata = doc["metadata"]
            if metadata.get("access_level", "internal") not in user.access_levels:
                continue
            if any(str(metadata.get(key)) != str(value) for key, value in filters.items()):
                continue
            score = 0.45 * float(sparse[index] / sparse_max) + 0.55 * (dense[index] / dense_max)
            ranked.append((score, doc))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [
            Evidence(
                document_id=doc["id"], title=doc["title"], text=doc["content"],
                score=round(min(max(score, 0), 1), 4), metadata=doc["metadata"],
            )
            for score, doc in ranked[:top_k] if score > 0
        ]


retriever = HybridRetriever()
