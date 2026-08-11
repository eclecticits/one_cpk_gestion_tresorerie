from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RetourCaisse(Base):
    """Retour en caisse consécutif à une sortie de fonds.

    Enregistre le remboursement de fonds préalablement décaissés : reliquat non
    utilisé d'une avance « à valoir », correction d'une sortie erronée (au-delà
    de la fenêtre d'annulation de 30 min), ou trop-perçu rendu par le
    bénéficiaire.

    C'est le miroir (contre-passation partielle) d'une ``SortieFonds`` :
    - la trésorerie de destination (caisse ou compte bancaire) est **créditée** ;
    - l'imputation budgétaire de la sortie d'origine est **réduite** du montant
      rendu (la dépense réelle est inférieure à ce qui avait été décaissé) ;
    - une écriture comptable inverse (D Trésorerie / C Charge) est générée si le
      module Comptabilité est actif.

    Le lien ``sortie_fonds_id`` est obligatoire : un retour se rattache toujours
    à la sortie qui l'a provoqué, ce qui permet de calculer le reste à justifier
    (``montant_paye`` de la sortie − somme des retours valides).
    """

    __tablename__ = "retours_caisse"
    __table_args__ = (
        CheckConstraint(
            "canal IN ('CAISSE','BANQUE')",
            name="ck_retours_caisse_canal",
        ),
        CheckConstraint(
            "devise IN ('USD','CDF')",
            name="ck_retours_caisse_devise",
        ),
        CheckConstraint(
            "(canal = 'BANQUE' AND compte_bancaire_id IS NOT NULL) OR (canal = 'CAISSE')",
            name="ck_retours_caisse_compte_bancaire",
        ),
        CheckConstraint("montant > 0", name="ck_retours_caisse_montant_positif"),
        CheckConstraint(
            "type_retour IN ('reliquat_avance','correction','trop_percu')",
            name="ck_retours_caisse_type_retour",
        ),
        UniqueConstraint(
            "organisation_id", "reference_numero", name="uq_retours_caisse_org_reference_numero"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Sortie de fonds d'origine : lien obligatoire (RESTRICT — un retour ne doit
    # jamais devenir orphelin, la traçabilité du reliquat en dépend).
    sortie_fonds_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sorties_fonds.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Copie de commodité de la réquisition liée (le cas échéant) pour filtrer /
    # calculer le reliquat d'une avance à valoir sans re-joindre la sortie.
    requisition_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("requisitions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    type_retour: Mapped[str] = mapped_column(String(30), nullable=False, default="reliquat_avance")

    # Imputation budgétaire d'origine (reprise de la sortie) : sert à réduire le
    # cumul payé du poste et à résoudre le compte de charge à créditer.
    budget_poste_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("budget_postes.id"),
        nullable=True,
        index=True,
    )
    budget_poste_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    budget_poste_libelle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # True => le retour diminue l'imputation budgétaire de la sortie d'origine.
    ajuste_budget: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    service_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("services.id"),
        nullable=True,
        index=True,
    )

    montant: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    devise: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    canal: Mapped[str] = mapped_column(String(10), nullable=False, default="CAISSE")
    compte_bancaire_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("comptes_bancaires.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    mode: Mapped[str] = mapped_column(String(50), nullable=False, default="cash")
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reference_numero: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    motif: Mapped[str | None] = mapped_column(Text, nullable=True)
    commentaire: Mapped[str | None] = mapped_column(Text, nullable=True)
    piece_justificative: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Taux figé (repris de la sortie) pour convertir le montant vers la devise du
    # budget de façon cohérente avec l'imputation d'origine.
    exchange_rate_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)

    date_retour: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    statut: Mapped[str] = mapped_column(String(20), nullable=False, default="VALIDE")
    statut_comptabilisation: Mapped[str] = mapped_column(
        String(40), nullable=False, default="NON_COMPTABILISEE", index=True
    )
    message_comptabilisation: Mapped[str | None] = mapped_column(Text, nullable=True)

    motif_annulation: Mapped[str | None] = mapped_column(Text, nullable=True)
    annulee_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    annulee_par_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    annulation_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ancien_statut: Mapped[str | None] = mapped_column(String(20), nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    # Relations volontairement uni-directionnelles (aucun back_populates ajouté
    # aux modèles existants) pour ne pas modifier leur configuration de mapper.
    organisation = relationship("Organisation")
    sortie_fonds = relationship("SortieFonds", foreign_keys=[sortie_fonds_id])
    compte_bancaire = relationship("CompteBancaire")
