"""Knowledge base document: uploaded file with processing status."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.task import Base


class KbDocument(Base):
    __tablename__ = "kb_documents"
    __table_args__ = (
        Index("ix_kb_documents_collection_id", "collection_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collection_id: Mapped[int] = mapped_column(
        ForeignKey("kb_collections.id", ondelete="CASCADE"), nullable=False,
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_type: Mapped[str] = mapped_column(String(16), nullable=False)  # "pdf" | "docx"
    stored_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    # pending -> processing -> ready | failed
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
