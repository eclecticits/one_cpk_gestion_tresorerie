from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TableauImport(Base):
    __tablename__ = "secretariat_tableau_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    exercice: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending", index=True)
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    dossiers: Mapped[list[TableauDossier]] = relationship("TableauDossier", back_populates="import_ref", cascade="all, delete-orphan")


class TableauDossier(Base):
    __tablename__ = "secretariat_tableau_dossiers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    import_id: Mapped[int] = mapped_column(Integer, ForeignKey("secretariat_tableau_imports.id", ondelete="CASCADE"), nullable=False, index=True)
    exercice: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    numero_ordre: Mapped[str | None] = mapped_column(String(50), nullable=True)
    nom: Mapped[str] = mapped_column(String(200), nullable=False)
    prenom: Mapped[str | None] = mapped_column(String(200), nullable=True)
    categorie: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    statut_membre: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cotisation_montant: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    cotisation_payee: Mapped[bool | None] = mapped_column(nullable=True)
    heures_forco: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    assurance: Mapped[bool | None] = mapped_column(nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    telephone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    adresse: Mapped[str | None] = mapped_column(Text, nullable=True)
    cabinet: Mapped[str | None] = mapped_column(String(200), nullable=True)
    statut_dossier: Mapped[str] = mapped_column(String(30), nullable=False, default="imported", index=True)
    anomalie_detectee: Mapped[bool] = mapped_column(nullable=False, default=False)
    raw_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    import_ref: Mapped[TableauImport] = relationship("TableauImport", back_populates="dossiers")
    anomalies: Mapped[list[TableauAnomalie]] = relationship("TableauAnomalie", back_populates="dossier", cascade="all, delete-orphan")


class TableauAnalyse(Base):
    __tablename__ = "secretariat_tableau_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    import_id: Mapped[int] = mapped_column(Integer, ForeignKey("secretariat_tableau_imports.id", ondelete="CASCADE"), nullable=False, index=True)
    exercice: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending", index=True)
    total_dossiers: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dossiers_complets: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dossiers_incomplets: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    anomalies_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    doublons_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cotisations_non_payees: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    heures_forco_insuffisantes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    assurances_manquantes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    observations_ia: Mapped[str | None] = mapped_column(Text, nullable=True)
    stats_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class TableauAnomalie(Base):
    __tablename__ = "secretariat_tableau_anomalies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    dossier_id: Mapped[int] = mapped_column(Integer, ForeignKey("secretariat_tableau_dossiers.id", ondelete="CASCADE"), nullable=False, index=True)
    type_anomalie: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    gravite: Mapped[str] = mapped_column(String(20), nullable=False, default="medium", index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    champ_concerne: Mapped[str | None] = mapped_column(String(100), nullable=True)
    valeur_trouvee: Mapped[str | None] = mapped_column(String(500), nullable=True)
    valeur_attendue: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open", index=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    dossier: Mapped[TableauDossier] = relationship("TableauDossier", back_populates="anomalies")


class TableauDecision(Base):
    __tablename__ = "secretariat_tableau_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    dossier_id: Mapped[int] = mapped_column(Integer, ForeignKey("secretariat_tableau_dossiers.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    type_decision: Mapped[str] = mapped_column(String(80), nullable=False)
    decision: Mapped[str] = mapped_column(String(50), nullable=False)
    motif: Mapped[str | None] = mapped_column(Text, nullable=True)
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class TableauReport(Base):
    __tablename__ = "secretariat_tableau_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organisation_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    import_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("secretariat_tableau_imports.id", ondelete="SET NULL"), nullable=True)
    exercice: Mapped[str] = mapped_column(String(20), nullable=False)
    type_rapport: Mapped[str] = mapped_column(String(50), nullable=False)
    titre: Mapped[str] = mapped_column(String(300), nullable=False)
    contenu: Mapped[str | None] = mapped_column(Text, nullable=True)
    format_sortie: Mapped[str] = mapped_column(String(20), nullable=False, default="text")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", index=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
