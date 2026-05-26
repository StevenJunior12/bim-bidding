"""Celery task: parse, chunk, (optionally) embed and store a KB document."""
from __future__ import annotations

import logging

from app import config
from app.database import SessionLocal
from app.kb_chunker import chunk_sections
from app.kb_embedding import embed_texts
from app.kb_faiss import rebuild_collection_index
from app.kb_parser import parse_document_structured
from app.models import KbChunk, KbCollection, KbDocument
from app.settings_store import get_api_key_from_db
from celery_app import app
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _set_doc_failed(db: Session, doc_id: int, error_message: str) -> None:
    doc = db.query(KbDocument).filter(KbDocument.id == doc_id).first()
    if doc:
        doc.status = "failed"
        doc.error_message = error_message[:2000]
        db.commit()


@app.task
def run_kb_ingest(document_id: int, tenant_id: str | None = None, user_id: str | None = None) -> None:
    """Parse, chunk, embed and store a KB document."""
    db: Session = SessionLocal()
    try:
        if not tenant_id or not user_id:
            _set_doc_failed(db, document_id, "缺少租户/用户信息")
            return

        doc = db.query(KbDocument).filter(KbDocument.id == document_id).first()
        if not doc:
            logger.warning("run_kb_ingest: document_id=%s not found", document_id)
            return

        collection = db.query(KbCollection).filter(KbCollection.id == doc.collection_id).first()
        if not collection or collection.tenant_id != tenant_id or collection.user_id != user_id:
            _set_doc_failed(db, document_id, "文档归属校验失败")
            return

        doc.status = "processing"
        doc.error_message = None
        db.commit()

        file_path = config.UPLOAD_DIR / doc.stored_path
        sections = parse_document_structured(file_path)
        logger.info("run_kb_ingest: doc_id=%s parsed %d sections", document_id, len(sections))

        api_key = get_api_key_from_db("siliconflow", tenant_id=tenant_id, user_id=user_id)
        chunks = chunk_sections(sections, doc.filename, api_key=api_key)
        if not chunks:
            _set_doc_failed(db, document_id, "文档解析后无可切块内容")
            return
        logger.info("run_kb_ingest: doc_id=%s chunked into %d pieces", document_id, len(chunks))

        embeddings: list[list[float] | None] | None = None
        if api_key:
            try:
                texts = [c.content for c in chunks]
                embeddings = embed_texts(texts, api_key=api_key)
                if len(embeddings) != len(chunks):
                    logger.warning(
                        "run_kb_ingest: embedding count mismatch, expected %d got %d",
                        len(chunks),
                        len(embeddings),
                    )
                    embeddings = None
            except Exception as e:
                logger.warning("run_kb_ingest: embedding failed, storing chunks without vectors: %s", e)
                embeddings = None

        for i, chunk_data in enumerate(chunks):
            db.add(
                KbChunk(
                    collection_id=doc.collection_id,
                    document_id=doc.id,
                    content=chunk_data.content,
                    heading_path=chunk_data.heading_path,
                    chunk_index=chunk_data.chunk_index,
                    embedding=list(embeddings[i]) if embeddings else None,
                )
            )

        if embeddings:
            doc.status = "ready"
        else:
            doc.status = "chunked"
            doc.error_message = "切块完成，但未向量化（未配置 SiliconFlow API Key）。配置后可重新处理。"
        doc.chunk_count = len(chunks)
        db.commit()

        if embeddings:
            try:
                rebuild_collection_index(doc.collection_id)
            except Exception as e:
                logger.warning("run_kb_ingest: faiss rebuild failed for collection=%s: %s", doc.collection_id, e)

        logger.info("run_kb_ingest: doc_id=%s done, %d chunks, status=%s", document_id, len(chunks), doc.status)
    except Exception as e:
        logger.exception("run_kb_ingest: document_id=%s failed", document_id)
        try:
            db.rollback()
            _set_doc_failed(db, document_id, str(e)[:2000])
        except Exception:
            db.rollback()
            raise
    finally:
        db.close()
