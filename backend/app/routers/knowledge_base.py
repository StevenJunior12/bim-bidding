"""Knowledge base management API: collections, documents, upload."""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from celery_app import app as celery_app
from app import config
from app.auth import Principal, get_principal
from app.database import get_db
from app.models import KbChunk, KbCollection, KbDocument
from app.upload_sniff import bytes_match_upload_extension
from tasks.kb_ingest import run_kb_ingest

router = APIRouter(prefix="/api/kb", tags=["knowledge-base"])

ALLOWED_EXTENSIONS = (".pdf", ".docx")


# --- Schemas ---

class CreateCollectionBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1024)


class CollectionResponse(BaseModel):
    id: int
    name: str
    description: str | None
    document_count: int
    created_at: str | None = None
    updated_at: str | None = None


class DocumentResponse(BaseModel):
    id: int
    collection_id: int
    filename: str
    file_size: int
    file_type: str
    status: str
    chunk_count: int
    error_message: str | None
    created_at: str | None = None


class ChunkResponse(BaseModel):
    id: int
    document_id: int
    content: str
    heading_path: str | None
    chunk_index: int


# --- Helpers ---

def _require_collection(collection_id: int, db: Session, principal: Principal) -> KbCollection:
    col = db.query(KbCollection).filter(
        KbCollection.id == collection_id,
        KbCollection.tenant_id == principal.tenant_id,
        KbCollection.user_id == principal.user_id,
    ).first()
    if not col:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return col


def _require_document(doc_id: int, collection_id: int, db: Session, principal: Principal) -> KbDocument:
    _require_collection(collection_id, db, principal)
    doc = db.query(KbDocument).filter(
        KbDocument.id == doc_id,
        KbDocument.collection_id == collection_id,
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    return doc


# --- Collection endpoints ---

@router.post("/collections", response_model=CollectionResponse, status_code=201)
def create_collection(
    body: CreateCollectionBody,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    col = KbCollection(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        name=body.name.strip(),
        description=body.description.strip() if body.description else None,
    )
    db.add(col)
    db.commit()
    db.refresh(col)
    return CollectionResponse(
        id=col.id,
        name=col.name,
        description=col.description,
        document_count=0,
        created_at=col.created_at.isoformat() if col.created_at else None,
        updated_at=col.updated_at.isoformat() if col.updated_at else None,
    )


@router.get("/collections", response_model=list[CollectionResponse])
def list_collections(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    cols = (
        db.query(KbCollection)
        .filter(
            KbCollection.tenant_id == principal.tenant_id,
            KbCollection.user_id == principal.user_id,
        )
        .order_by(KbCollection.created_at.desc())
        .all()
    )
    result = []
    for col in cols:
        doc_count = db.query(func.count(KbDocument.id)).filter(
            KbDocument.collection_id == col.id,
        ).scalar() or 0
        result.append(CollectionResponse(
            id=col.id,
            name=col.name,
            description=col.description,
            document_count=doc_count,
            created_at=col.created_at.isoformat() if col.created_at else None,
            updated_at=col.updated_at.isoformat() if col.updated_at else None,
        ))
    return result


@router.delete("/collections/{collection_id}", status_code=204)
def delete_collection(
    collection_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    col = _require_collection(collection_id, db, principal)
    # Cascade deletes documents and chunks
    db.delete(col)
    db.commit()
    return None


# --- Document endpoints ---

@router.post("/collections/{collection_id}/documents", response_model=DocumentResponse, status_code=201)
def upload_document(
    collection_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    _require_collection(collection_id, db, principal)

    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型，仅限 {', '.join(ALLOWED_EXTENSIONS)}")

    # Validate magic bytes
    head = file.file.read(8192)
    if len(head) < 4:
        raise HTTPException(status_code=400, detail="文件过小或为空")
    if not bytes_match_upload_extension(suffix, head):
        raise HTTPException(status_code=400, detail="文件内容与扩展名不符")

    # Store file
    kb_dir = config.UPLOAD_DIR / "kb" / f"tenant_{principal.tenant_id}" / f"user_{principal.user_id}"
    kb_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    dest_path = kb_dir / stored_name
    relative_path = f"kb/tenant_{principal.tenant_id}/user_{principal.user_id}/{stored_name}"

    size = len(head)
    chunk_size = 1024 * 1024
    try:
        with open(dest_path, "wb") as f:
            f.write(head)
            while True:
                chunk = file.file.read(chunk_size)
                if not chunk:
                    break
                size += len(chunk)
                if size > config.MAX_UPLOAD_SIZE_BYTES:
                    dest_path.unlink(missing_ok=True)
                    raise HTTPException(status_code=400, detail=f"文件过大，最大 {config.MAX_UPLOAD_SIZE_MB} MB")
                f.write(chunk)
    except HTTPException:
        raise
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"文件保存失败: {e}") from e

    doc = KbDocument(
        collection_id=collection_id,
        filename=filename,
        file_size=size,
        file_type=suffix.lstrip("."),
        stored_path=relative_path,
        status="pending",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Dispatch Celery task
    run_kb_ingest.delay(doc.id, tenant_id=principal.tenant_id, user_id=principal.user_id)

    return DocumentResponse(
        id=doc.id,
        collection_id=doc.collection_id,
        filename=doc.filename,
        file_size=doc.file_size,
        file_type=doc.file_type,
        status=doc.status,
        chunk_count=doc.chunk_count,
        error_message=doc.error_message,
        created_at=doc.created_at.isoformat() if doc.created_at else None,
    )


@router.get("/collections/{collection_id}/documents", response_model=list[DocumentResponse])
def list_documents(
    collection_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    _require_collection(collection_id, db, principal)
    docs = (
        db.query(KbDocument)
        .filter(KbDocument.collection_id == collection_id)
        .order_by(KbDocument.created_at.desc())
        .all()
    )
    return [
        DocumentResponse(
            id=d.id,
            collection_id=d.collection_id,
            filename=d.filename,
            file_size=d.file_size,
            file_type=d.file_type,
            status=d.status,
            chunk_count=d.chunk_count,
            error_message=d.error_message,
            created_at=d.created_at.isoformat() if d.created_at else None,
        )
        for d in docs
    ]


@router.delete("/collections/{collection_id}/documents/{doc_id}", status_code=204)
def delete_document(
    collection_id: int,
    doc_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    doc = _require_document(doc_id, collection_id, db, principal)
    db.delete(doc)
    db.commit()
    return None


# --- Chunk browsing (debug) ---

@router.get("/collections/{collection_id}/documents/{doc_id}/chunks", response_model=list[ChunkResponse])
def list_chunks(
    collection_id: int,
    doc_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    _require_document(doc_id, collection_id, db, principal)
    chunks = (
        db.query(KbChunk)
        .filter(KbChunk.document_id == doc_id)
        .order_by(KbChunk.chunk_index)
        .all()
    )
    return [
        ChunkResponse(
            id=c.id,
            document_id=c.document_id,
            content=c.content,
            heading_path=c.heading_path,
            chunk_index=c.chunk_index,
        )
        for c in chunks
    ]


# --- Test search (debug) ---

class TestSearchBody(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class SearchHitResponse(BaseModel):
    content: str
    heading_path: str | None
    chunk_index: int
    doc_filename: str
    similarity: float
    rerank_score: float | None = None


class TestSearchResponse(BaseModel):
    results: list[SearchHitResponse]


@router.post("/collections/{collection_id}/search", response_model=TestSearchResponse)
def test_search(
    collection_id: int,
    body: TestSearchBody,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
):
    _require_collection(collection_id, db, principal)
    from app.kb_search import search_internal
    hits = search_internal(
        body.query,
        body.top_k,
        collection_id=collection_id,
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
    )
    return TestSearchResponse(
        results=[
            SearchHitResponse(
                content=h.content,
                heading_path=h.heading_path,
                chunk_index=h.chunk_index,
                doc_filename=h.doc_filename,
                similarity=round(h.similarity, 4),
                rerank_score=h.rerank_score,
            )
            for h in hits
        ],
    )
