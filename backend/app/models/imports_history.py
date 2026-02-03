from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ImportsHistory(Base):
    __tablename__ = "imports_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    
    # sec, en_cabinet, independant, salarie
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    
    imported_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    rows_imported: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    
    # success, error, partial
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="success")
    
    # Données brutes du fichier importé (pour audit/rollback)
    file_data: Mapped[list | None] = mapped_column(JSON, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
