from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.schemas.base import DecimalBaseModel


class BilletagePayload(BaseModel):
    usd: dict[str, int] = {}
    cdf: dict[str, int] = {}


class ClotureBalanceResponse(DecimalBaseModel):
    date_debut: datetime | None = None
    date_fin: datetime
    taux_change: Decimal = Decimal("1")
    solde_initial_usd: Decimal = Decimal("0")
    solde_initial_cdf: Decimal = Decimal("0")
    total_entrees_usd: Decimal = Decimal("0")
    total_entrees_cdf: Decimal = Decimal("0")
    total_sorties_usd: Decimal = Decimal("0")
    total_sorties_cdf: Decimal = Decimal("0")
    solde_theorique_usd: Decimal = Decimal("0")
    solde_theorique_cdf: Decimal = Decimal("0")


class ClotureCreateRequest(BaseModel):
    solde_physique_usd: Decimal
    solde_physique_cdf: Decimal
    billetage_usd: dict[str, int] | None = None
    billetage_cdf: dict[str, int] | None = None
    observation: str | None = None


class ClotureOut(DecimalBaseModel):
    id: int
    reference_numero: str
    date_cloture: datetime
    date_debut: datetime | None = None
    caissier_id: str | None = None
    solde_initial_usd: Decimal
    solde_initial_cdf: Decimal
    total_entrees_usd: Decimal
    total_entrees_cdf: Decimal
    total_sorties_usd: Decimal
    total_sorties_cdf: Decimal
    solde_theorique_usd: Decimal
    solde_theorique_cdf: Decimal
    solde_physique_usd: Decimal
    solde_physique_cdf: Decimal
    ecart_usd: Decimal
    ecart_cdf: Decimal
    taux_change_applique: Decimal
    billetage_usd: dict | None = None
    billetage_cdf: dict | None = None
    observation: str | None = None
    pdf_path: str | None = None
    statut: str


class CloturePdfDetail(BaseModel):
    reference_numero: str | None = None
    beneficiaire: str | None = None
    motif: str | None = None
    montant_paye: Decimal | None = None


class CloturePdfData(DecimalBaseModel):
    cloture: ClotureOut
    details: list[CloturePdfDetail]
