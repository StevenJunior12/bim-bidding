"""FAISS index management for internal KB retrieval."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import faiss
import numpy as np

from app import config
from app.database import SessionLocal
from app.models import KbChunk, KbDocument

logger = logging.getLogger(__name__)

INDEX_DIR = config.FAISS_INDEX_DIR


@dataclass(frozen=True)
class FaissHit:
    chunk_id: int
    score: float


def _collection_dir(collection_id: int) -> Path:
    return INDEX_DIR / f"collection_{collection_id}"


def _index_path(collection_id: int) -> Path:
    return _collection_dir(collection_id) / "index.faiss"


def _meta_path(collection_id: int) -> Path:
    return _collection_dir(collection_id) / "meta.json"


def ensure_index_dir(collection_id: int) -> Path:
    path = _collection_dir(collection_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _normalize_matrix(vectors: list[list[float]]) -> np.ndarray:
    arr = np.asarray(vectors, dtype=np.float32)
    if arr.ndim != 2 or arr.size == 0:
        raise ValueError("Empty or invalid vector matrix")
    faiss.normalize_L2(arr)
    return arr


def rebuild_collection_index(collection_id: int) -> int:
    """Rebuild the FAISS index from MySQL chunk rows. Returns chunk count."""
    db = SessionLocal()
    try:
        rows = (
            db.query(KbChunk.id, KbChunk.embedding)
            .join(KbDocument, KbChunk.document_id == KbDocument.id)
            .filter(
                KbChunk.collection_id == collection_id,
                KbDocument.status == "ready",
                KbChunk.embedding.isnot(None),
            )
            .order_by(KbChunk.id.asc())
            .all()
        )
    finally:
        db.close()

    index_path = _index_path(collection_id)
    meta_path = _meta_path(collection_id)

    if not rows:
        if index_path.exists():
            index_path.unlink()
        if meta_path.exists():
            meta_path.unlink()
        return 0

    chunk_ids: list[int] = []
    vectors: list[list[float]] = []
    for chunk_id, embedding in rows:
        try:
            vec = [float(v) for v in json.loads(json.dumps(embedding or []))]
        except Exception:
            continue
        if vec:
            chunk_ids.append(int(chunk_id))
            vectors.append(vec)

    if not vectors:
        if index_path.exists():
            index_path.unlink()
        if meta_path.exists():
            meta_path.unlink()
        dir_path = _collection_dir(collection_id)
        if dir_path.exists() and not any(dir_path.iterdir()):
            dir_path.rmdir()
        return 0

    ensure_index_dir(collection_id)
    matrix = _normalize_matrix(vectors)
    dim = matrix.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(matrix)
    faiss.write_index(index, str(index_path))
    meta_path.write_text(
        json.dumps({"chunk_ids": chunk_ids, "dimension": dim}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return len(chunk_ids)


def remove_collection_index(collection_id: int) -> None:
    path = _collection_dir(collection_id)
    if not path.exists():
        return
    for child in path.iterdir():
        if child.is_file():
            child.unlink(missing_ok=True)
    path.rmdir()


def search_collection(collection_id: int, query_vector: list[float], top_k: int) -> list[FaissHit]:
    index_path = _index_path(collection_id)
    meta_path = _meta_path(collection_id)
    if not index_path.exists() or not meta_path.exists():
        return []

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    chunk_ids = meta.get("chunk_ids") if isinstance(meta, dict) else None
    if not isinstance(chunk_ids, list) or not chunk_ids:
        return []

    index = faiss.read_index(str(index_path))
    if index.ntotal == 0:
        return []

    query = np.asarray([query_vector], dtype=np.float32)
    if query.ndim != 2 or query.shape[1] != index.d:
        logger.warning("search_collection: dimension mismatch for collection=%s", collection_id)
        return []
    faiss.normalize_L2(query)
    scores, indices = index.search(query, min(top_k, len(chunk_ids)))

    hits: list[FaissHit] = []
    for score, idx in zip(scores[0], indices[0], strict=True):
        if idx < 0 or idx >= len(chunk_ids):
            continue
        hits.append(FaissHit(chunk_id=int(chunk_ids[idx]), score=float(score)))
    return hits


def count_indexed_chunks(collection_id: int) -> int:
    meta_path = _meta_path(collection_id)
    if not meta_path.exists():
        return 0
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    chunk_ids = meta.get("chunk_ids") if isinstance(meta, dict) else None
    return len(chunk_ids) if isinstance(chunk_ids, list) else 0
