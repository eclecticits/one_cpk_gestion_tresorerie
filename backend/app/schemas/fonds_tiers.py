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
    tiers_concerne: str
    payeur_origine: str | None = None
    beneficiaire_reel: str | None = None
    motif: str | None = None
    reference: str | None = None
    piece_justificative: str | None = None
    montant_recu: Decimal
    devise: Literal["USD", "CDF"]
    montant_rembourse: Decimal
    solde_restant: Decimal
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime
