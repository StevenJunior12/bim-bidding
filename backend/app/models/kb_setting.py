"""Knowledge base settings: kb_type (none/ragflow/internal) and config."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.task import Base


class KbSetting(Base):
    __tablename__ = "kb_settings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_kb_settings_tenant_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    kb_type: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    ragflow_api_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ragflow_encrypted_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    ragflow_dataset_ids: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    internal_collection_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("kb_collections.id", ondelete="SET NULL"), nullable=True,
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
