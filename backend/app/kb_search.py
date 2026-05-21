"""Internal pgvector knowledge base search with optional rerank."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import text

from app.database import SessionLocal
from app.kb_embedding import embed_query, rerank_texts
from app.settings_store import get_api_key_from_db

logger = logging.getLogger(__name__)

# Over-retrieve from vector search, then rerank down to top_k
_CANDIDATE_MULTIPLIER = 4


@dataclass
class SearchResult:
    content: str
    heading_path: str | None
    chunk_index: int
    doc_filename: str
    similarity: float
    rerank_score: float | None = None


def search_internal(
    query: str,
    top_k: int,
    *,
    collection_id: int,
    tenant_id: str,
    user_id: str,
) -> list[SearchResult]:
    """Two-stage search: vector recall + rerank.

    Stage 1: pgvector cosine similarity → top_k * _CANDIDATE_MULTIPLIER candidates
    Stage 2: rerank (cross-encoder) → top_k final results
    If rerank fails, fall back to vector-only results.
    """
    api_key = get_api_key_from_db("siliconflow", tenant_id=tenant_id, user_id=user_id)
    if not api_key:
        logger.warning("search_internal: no SiliconFlow API key for tenant=%s user=%s", tenant_id, user_id)
        return []

    query_vec = embed_query(query, api_key=api_key)

    # Stage 1: vector search — over-retrieve for rerank
    candidate_limit = top_k * _CANDIDATE_MULTIPLIER

    db = SessionLocal()
    try:
        result = db.execute(
            text(
                """
                SELECT c.content, c.heading_path, c.chunk_index,
                       d.filename AS doc_filename,
                       1 - (c.embedding <=> :query_vec) AS similarity
                FROM kb_chunks c
                JOIN kb_documents d ON c.document_id = d.id
                JOIN kb_collections col ON c.collection_id = col.id
                WHERE col.id = :collection_id
                  AND col.tenant_id = :tenant_id
                  AND col.user_id = :user_id
                  AND d.status = 'ready'
                  AND c.embedding IS NOT NULL
                ORDER BY c.embedding <=> :query_vec
                LIMIT :limit
                """
            ),
            {
                "collection_id": collection_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "query_vec": str(query_vec),
                "limit": candidate_limit,
            },
        )
        candidates = [
            SearchResult(
                content=row[0],
                heading_path=row[1],
                chunk_index=row[2],
                doc_filename=row[3],
                similarity=float(row[4]),
            )
            for row in result.fetchall()
        ]
    except Exception as e:
        logger.warning("search_internal vector stage failed: %s", e)
        return []
    finally:
        db.close()

    if not candidates:
        return []

    # If few candidates, no need to rerank
    if len(candidates) <= top_k:
        return candidates

    # Stage 2: rerank
    try:
        rerank_results = rerank_texts(
            query,
            [c.content for c in candidates],
            api_key=api_key,
            top_n=top_k,
        )
    except Exception as e:
        logger.warning("search_internal rerank failed, using vector-only results: %s", e)
        return candidates[:top_k]

    if not rerank_results:
        return candidates[:top_k]

    # Map rerank results back to SearchResults
    final: list[SearchResult] = []
    for rr in rerank_results:
        hit = candidates[rr.index]
        hit.rerank_score = round(rr.relevance_score, 4)
        final.append(hit)
    return final
