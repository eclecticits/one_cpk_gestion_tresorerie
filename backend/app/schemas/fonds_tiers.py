from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from app.schemas.base import DecimalBaseModel


class FondsTiersOut(DecimalBaseModel):
    id: UUID
    organisation_id: int
    encaissement_id: UUID
    statut: Literal["OUVERT", "PARTIELLEMENT_REMBOURSE", "REGULARISE", "ANNULE"]
    tiers_concerne: str | None = None
    tiers_organisation_id: int | None = None
    tiers_nom_libre: str | None = None
    tiers_display_name: str
    tiers_type: Literal["ORGANISATION", "EXTERNE", "LEGACY"]
    payeur_origine: str | None = None
    beneficiaire_reel: str | None = None
    motif: str | None = None
    reference: str | None = None
    piece_justificative: str | None = None
    montant_recu: Decimal
    devise: Literal["USD", "CDF"]
    montant_rembourse: Decimal
    solde_restant: Decimal
    # Part du solde déjà promise par des réquisitions en cours, et ce qui
    # reste libre pour un nouveau versement.
    montant_reserve: Decimal = Decimal("0.00")
    disponible: Decimal = Decimal("0.00")
    requisitions_en_cours: list[str] = []
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime
