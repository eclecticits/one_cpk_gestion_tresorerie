from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DocumentSequence(Base):
    __tablename__ = "document_sequences"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_type: Mapped[str] = mapped_column(String(10), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    service_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("services.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    tenant_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    counter: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        Index(
            "uq_docseq_central",
            "doc_type",
            "year",
            "tenant_id",
            unique=True,
            postgresql_where=text("service_id IS NULL"),
        ),
        Index(
            "uq_docseq_service",
            "doc_type",
            "year",
            "tenant_id",
            "service_id",
            unique=True,
            postgresql_where=text("service_id IS NOT NULL"),
        ),
    )
