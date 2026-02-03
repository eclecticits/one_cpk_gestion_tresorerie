from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CategoryChangesHistory(Base):
    __tablename__ = "category_changes_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    expert_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    numero_ordre: Mapped[str] = mapped_column(String(50), nullable=False)
    
    old_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    new_category: Mapped[str] = mapped_column(String(50), nullable=False)
    
    changed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Données avant/après en JSON pour traçabilité complète
    old_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    new_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
