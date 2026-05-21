"""SiliconFlow Embedding & Rerank API client."""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app import config

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 32
DEFAULT_RERANK_MODEL = "BAAI/bge-reranker-v2-m3"


def embed_texts(
    texts: list[str],
    *,
    api_key: str,
    base_url: str | None = None,
    model: str | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[list[float]]:
    """Embed a list of texts via SiliconFlow API in batches.

    Returns list of embedding vectors in the same order as input.
    """
    if not texts:
        return []

    base = (base_url or config.SILICONFLOW_BASE_URL).rstrip("/")
    mdl = model or config.SILICONFLOW_EMBEDDING_MODEL
    all_embeddings: list[list[float]] = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = _call_embedding_api(base, api_key, mdl, batch)
        all_embeddings.extend(resp)

    return all_embeddings


def embed_query(
    query: str,
    *,
    api_key: str,
    base_url: str | None = None,
    model: str | None = None,
) -> list[float]:
    """Embed a single query string."""
    results = embed_texts([query], api_key=api_key, base_url=base_url, model=model)
    return results[0]


@dataclass
class RerankResult:
    index: int
    relevance_score: float


def rerank_texts(
    query: str,
    documents: list[str],
    *,
    api_key: str,
    base_url: str | None = None,
    model: str | None = None,
    top_n: int | None = None,
) -> list[RerankResult]:
    """Rerank documents against a query using cross-encoder model.

    Returns results sorted by relevance_score descending.
    """
    if not documents:
        return []

    base = (base_url or config.SILICONFLOW_BASE_URL).rstrip("/")
    mdl = model or DEFAULT_RERANK_MODEL

    url = f"{base}/rerank"
    payload: dict = {
        "model": mdl,
        "query": query,
        "documents": documents,
        "return_documents": False,
    }
    if top_n is not None:
        payload["top_n"] = top_n

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=60.0) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    results = data.get("results", [])
    return [
        RerankResult(index=r["index"], relevance_score=r["relevance_score"])
        for r in results
    ]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _call_embedding_api(
    base_url: str, api_key: str, model: str, texts: list[str],
) -> list[list[float]]:
    """Call the OpenAI-compatible /embeddings endpoint."""
    url = f"{base_url}/embeddings"
    payload = {
        "model": model,
        "input": texts,
        "encoding_format": "float",
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=60.0) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    if not isinstance(data, dict) or "data" not in data:
        raise ValueError(f"Unexpected embedding response: {data!r:.200}")

    # Sort by index to maintain order
    items = sorted(data["data"], key=lambda x: x.get("index", 0))
    return [item["embedding"] for item in items]
