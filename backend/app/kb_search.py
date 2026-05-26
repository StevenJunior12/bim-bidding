"""Internal knowledge base search with FAISS recall + rerank."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.database import SessionLocal
from app.kb_embedding import embed_query, rerank_texts
from app.kb_faiss import search_collection
from app.models import KbChunk, KbDocument
from app.settings_store import get_api_key_from_db

logger = logging.getLogger(__name__)

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
    """Two-stage search: FAISS recall + rerank."""
    api_key = get_api_key_from_db("siliconflow", tenant_id=tenant_id, user_id=user_id)
    if not api_key:
        logger.warning("search_internal: no SiliconFlow API key for tenant=%s user=%s", tenant_id, user_id)
        return []

    query_vec = embed_query(query, api_key=api_key)
    hits = search_collection(collection_id, query_vec, top_k * _CANDIDATE_MULTIPLIER)
    if not hits:
        logger.info("search_internal: no FAISS hits for collection_id=%s", collection_id)
        return []

    db = SessionLocal()
    try:
        chunk_ids = [hit.chunk_id for hit in hits]
        rows = (
            db.query(
                KbChunk.id,
                KbChunk.content,
                KbChunk.heading_path,
                KbChunk.chunk_index,
                KbDocument.filename,
            )
            .join(KbDocument, KbChunk.document_id == KbDocument.id)
            .filter(
                KbChunk.id.in_(chunk_ids),
                KbDocument.status == "ready",
            )
            .all()
        )
        row_map = {
            chunk_id: (content, heading_path, chunk_index, doc_filename)
            for chunk_id, content, heading_path, chunk_index, doc_filename in rows
        }
        candidates: list[SearchResult] = []
        for hit in hits:
            row = row_map.get(hit.chunk_id)
            if not row:
                continue
            candidates.append(
                SearchResult(
                    content=row[0],
                    heading_path=row[1],
                    chunk_index=row[2],
                    doc_filename=row[3],
                    similarity=hit.score,
                )
            )
    except Exception as e:
        logger.warning("search_internal metadata stage failed: %s", e)
        return []
    finally:
        db.close()

    if not candidates:
        return []

    candidates.sort(key=lambda x: x.similarity, reverse=True)
    candidate_limit = top_k * _CANDIDATE_MULTIPLIER
    if len(candidates) > candidate_limit:
        candidates = candidates[:candidate_limit]

    if len(candidates) <= top_k:
        return candidates

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

    final: list[SearchResult] = []
    for rr in rerank_results:
        result = candidates[rr.index]
        result.rerank_score = round(rr.relevance_score, 4)
        final.append(result)
    return final
