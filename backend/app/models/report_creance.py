"""Report d'une créance d'un exercice clôturé vers le poste d'arriérés du suivant.

Une note de débit « Cotisation 2026 » impayée au 31 décembre ne tombe pas : ce
qui en reste dû change de poste. Le reçu lui-même n'est pas réécrit — il dit
toujours « Cotisation 2026 », et ce qui a été payé en 2026 reste réalisé sur
le poste 2026. Seul le reste à recouvrer passe, à la clôture, sur le poste
d'arriérés de l'exercice suivant, où les versements ultérieurs s'imputeront.

Une ligne par encaissement et par poste d'origine : une note à plusieurs
articles porte plusieurs postes, et chacun reporte sa part.

Statuts :
  - ACTIVE    le report en vigueur : les versements s'imputent sur son poste
              cible, dans la proportion des montants reportés ;
  - REMPLACE  la créance est restée impayée à la clôture de l'exercice cible,
              et un report plus récent l'a reprise (arriérés 2027 → 2028) ;
  - ANNULE    l'exercice d'origine a été rouvert avant tout versement.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


REPORT_ACTIVE = "ACTIVE"
REPORT_REMPLACE = "REMPLACE"
REPORT_ANNULE = "ANNULE"


class ReportCreance(Base):
    __tablename__ = "reports_creances"
    __table_args__ = (
        CheckConstraint("montant > 0", name="ck_reports_creances_montant_positif"),
        CheckConstraint(
            "statut IN ('ACTIVE','REMPLACE','ANNULE')", name="ck_reports_creances_statut"
        ),
        # Rejouer la clôture ne reporte pas deux fois : une part d'origine n'a
        # qu'un report vivant par exercice source.
        Index(
            "uq_reports_creances_part_vivante",
            "encaissement_id",
            "exercice_source_id",
            "poste_source_id",
            unique=True,
            postgresql_where=text("statut <> 'ANNULE'"),
        ),
        Index("ix_reports_creances_encaissement_statut", "encaissement_id", "statut"),
        Index("ix_reports_creances_org_exercice_source", "organisation_id", "exercice_source_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False
    )
    encaissement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("encaissements.id", ondelete="RESTRICT"), nullable=False
    )
    exercice_source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("budget_exercices.id", ondelete="RESTRICT"), nullable=False
    )
    exercice_cible_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("budget_exercices.id", ondelete="RESTRICT"), nullable=False
    )
    poste_source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("budget_postes.id", ondelete="RESTRICT"), nullable=False
    )
    poste_cible_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("budget_postes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    #: Reste à recouvrer de cette part au moment du report, dans la devise de
    #: l'encaissement. Il sert de poids pour répartir les versements suivants.
    montant: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    statut: Mapped[str] = mapped_column(String(20), nullable=False, default=REPORT_ACTIVE)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    annule_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    annule_par_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
