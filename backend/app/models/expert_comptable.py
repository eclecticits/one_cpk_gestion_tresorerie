from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ExpertComptable(Base):
    __tablename__ = "experts_comptables"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    numero_ordre: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    nom_denomination: Mapped[str] = mapped_column(String(300), nullable=False)
    
    # Type: EC (Expert Comptable) ou SEC (Société d'Expertise Comptable)
    type_ec: Mapped[str] = mapped_column(String(10), nullable=False, default="EC")
    
    # Personne Physique ou Personne Morale
    categorie_personne: Mapped[str | None] = mapped_column(String(50), nullable=True)
    
    # En Cabinet, Indépendant, Salarié, Cabinet
    statut_professionnel: Mapped[str | None] = mapped_column(String(50), nullable=True)
    
    sexe: Mapped[str | None] = mapped_column(String(1), nullable=True)
    telephone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    
    # Champs spécifiques selon catégorie
    nif: Mapped[str | None] = mapped_column(String(50), nullable=True)  # Indépendant
    cabinet_attache: Mapped[str | None] = mapped_column(String(200), nullable=True)  # En Cabinet
    nom_employeur: Mapped[str | None] = mapped_column(String(200), nullable=True)  # Salarié
    raison_sociale: Mapped[str | None] = mapped_column(String(300), nullable=True)  # SEC
    associe_gerant: Mapped[str | None] = mapped_column(String(200), nullable=True)  # SEC
    
    # Référence à l'import d'origine
    import_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
