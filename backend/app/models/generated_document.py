from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GeneratedDocument(Base):
    __tablename__ = "generated_documents"
    __table_args__ = (
        UniqueConstraint(
            "organisation_id",
            "resource_type",
            "resource_id",
            "document_type",
            "version",
            name="uq_generated_documents_resource_version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    resource_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    generated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    source_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    signatories_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    exchange_rate_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    rendered_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    pdf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_original: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reprint_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("generated_documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    legacy_data_status: Mapped[str] = mapped_column(String(40), nullable=False, default="current_snapshot")

    signatories: Mapped[list["DocumentSignatorySnapshot"]] = relationship(
        "DocumentSignatorySnapshot",
        back_populates="document",
        cascade="all, delete-orphan",
    )


class DocumentSignatorySnapshot(Base):
    __tablename__ = "document_signatory_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("generated_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    full_name_snapshot: Mapped[str | None] = mapped_column(String(200), nullable=True)
    title_snapshot: Mapped[str | None] = mapped_column(String(200), nullable=True)
    role_snapshot: Mapped[str | None] = mapped_column(String(100), nullable=True)
    signature_snapshot: Mapped[str | None] = mapped_column(String(500), nullable=True)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document: Mapped["GeneratedDocument"] = relationship("GeneratedDocument", back_populates="signatories")
