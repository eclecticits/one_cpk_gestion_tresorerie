from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normaliser_cle_beneficiaire(value: str | None) -> str:
    """Clé de regroupement du plafond anti-fractionnement des ordres directs.

    SEULE normalisation du bénéficiaire, et elle vit ici, auprès de la colonne
    qui la stocke (`beneficiaire_normalise`) : tout ce qui écrit un ordre doit
    passer par elle. La requête de cumul compare la colonne nue et ne
    renormalise rien.

    Une seconde normalisation, écrite en SQL, ne pourrait pas être tenue
    identique à celle-ci : `\\s` de Python couvre l'espace Unicode (insécable
    comprise), là où `[[:space:]]` de Postgres dépend du ctype et exclut
    l'insécable sous glibc. L'écart suffisait à faire passer deux ordres
    identiques pour étrangers l'un à l'autre, donc à contourner le plafond en
    collant un nom porteur d'une insécable.
    """
    return re.sub(r"\s+", " ", (value or "").lower()).strip()


class OrdreDecaissement(Base):
    """Tranche autorisée d'une réquisition à décaissement progressif.

    Créé et autorisé par le demandeur de la réquisition ; la caissière ne peut
    qu'exécuter le paiement (création d'une SortieFonds liée, montant et
    bénéficiaire verrouillés).
    """

    __tablename__ = "ordres_decaissement"
    __table_args__ = (
        # Couvre GET /ordres-decaissement : filtre organisation_id systématique,
        # tri par défaut sur created_at desc.
        Index(
            "ix_ordres_decaissement_org_created",
            "organisation_id",
            "created_at",
        ),
        # Sert le cumul anti-fractionnement des ordres directs : filtre
        # (organisation, service, bénéficiaire normalisé) puis borne des 24 h.
        # Restreint aux ordres directs, les seuls que le plafond regarde.
        Index(
            "ix_ordres_direct_fractionnement",
            "organisation_id",
            "service_id",
            "beneficiaire_normalise",
            "created_at",
            postgresql_where=text("requisition_id IS NULL"),
        ),
        CheckConstraint("montant > 0", name="ck_ordres_decaissement_montant_positif"),
        CheckConstraint(
            "statut IN ('AUTORISE','PAYE','ANNULE')",
            name="ck_ordres_decaissement_statut",
        ),
        CheckConstraint("devise IN ('USD','CDF')", name="ck_ordres_decaissement_devise"),
        CheckConstraint("canal IN ('CAISSE','BANQUE')", name="ck_ordres_decaissement_canal"),
        CheckConstraint(
            "(canal = 'BANQUE' AND compte_bancaire_id IS NOT NULL) OR canal = 'CAISSE'",
            name="ck_ordres_decaissement_compte_bancaire",
        ),
        UniqueConstraint("organisation_id", "numero_ordre", name="uq_ordres_decaissement_org_numero"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # NULL = ordre de sortie directe (sans réquisition), programmé par un
    # utilisateur disposant de can_direct_disbursement et payé par la caisse.
    requisition_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("requisitions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    numero_ordre: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    beneficiaire: Mapped[str] = mapped_column(String(200), nullable=False)
    # Clé de regroupement du plafond anti-fractionnement. Calculée UNE fois, en
    # Python (`_normaliser_cle_fractionnement`), et stockée : deux
    # normalisations — une par langage — ne peuvent pas être tenues identiques,
    # et leur écart rendait le plafond contournable. Colonne nue, donc
    # indexable : cf. ix_ordres_direct_fractionnement.
    # Sans valeur par défaut à dessein : un site d'écriture qui l'oublierait
    # doit échouer bruyamment (NOT NULL) plutôt que d'enregistrer une clé vide,
    # laquelle regrouperait entre eux des ordres sans rapport sous le plafond.
    beneficiaire_normalise: Mapped[str] = mapped_column(String(200), nullable=False)
    montant: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    montant_usd_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    devise: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    motif: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Volet de règlement : décision ferme posée à l'autorisation, exécutée telle
    # quelle par la caisse. Un ordre est mono-(mode, compte) — c'est ce qui le
    # garde traduisible en une seule SortieFonds (cf. sortie_fonds_id, 1:1).
    # Une réquisition mixte donne donc autant d'ordres que de volets, chacun
    # payable indépendamment des autres.
    mode_paiement: Mapped[str] = mapped_column(String(50), nullable=False, default="cash")
    canal: Mapped[str] = mapped_column(String(10), nullable=False, default="CAISSE")
    compte_bancaire_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("comptes_bancaires.id"),
        nullable=True,
        index=True,
    )

    # Définition « en amont » façon réquisition (sorties directes programmées) :
    # service/commission responsable et lignes budgétaires (postes). Null pour
    # les ordres liés à une réquisition (l'info vit alors sur la réquisition).
    service_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("services.id"), nullable=True, index=True
    )
    lignes: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    statut: Mapped[str] = mapped_column(String(20), nullable=False, default="AUTORISE", index=True)

    autorise_par: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    autorise_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    paye_par: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    paye_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sortie_fonds_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sorties_fonds.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    annule_par: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    annule_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motif_annulation: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    requisition: Mapped["Requisition | None"] = relationship("Requisition")
    sortie_fonds = relationship("SortieFonds", foreign_keys=[sortie_fonds_id])
