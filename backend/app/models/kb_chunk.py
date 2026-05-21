"""Knowledge base chunk: document segment with pgvector embedding."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from pgvector.sqlalchemy import Vector

from app.models.task import Base


class KbChunk(Base):
    __tablename__ = "kb_chunks"
    __table_args__ = (
        Index("ix_kb_chunks_collection_id", "collection_id"),
        Index("ix_kb_chunks_document_id", "document_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collection_id: Mapped[int] = mapped_column(
        ForeignKey("kb_collections.id", ondelete="CASCADE"), nullable=False,
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("kb_documents.id", ondelete="CASCADE"), nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    heading_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding = mapped_column(Vector(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
