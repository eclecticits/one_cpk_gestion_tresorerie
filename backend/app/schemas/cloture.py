from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel
from uuid import UUID

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
    # Un écart constaté ne modifie le solde que si l'utilisateur demande sa
    # régularisation : elle crée alors un encaissement (excédent) ou une sortie
    # (déficit). À défaut, la clôture aboutit quand même et l'écart reste ouvert.
    regulariser_ecart: bool = False
    motif_regularisation: str | None = None


class EcartRegularisationRequest(BaseModel):
    """Régularisation, après coup, d'un écart laissé ouvert."""

    motif: str
    # Restreint la régularisation à une devise ; par défaut les deux sont traitées.
    devise: str | None = None


class OuvertureCreateRequest(BaseModel):
    solde_ouverture_usd: Decimal = Decimal("0")
    solde_ouverture_cdf: Decimal = Decimal("0")
    billetage_usd: dict[str, int] | None = None
    billetage_cdf: dict[str, int] | None = None
    observation: str | None = None
    regulariser_ecart: bool = False
    motif_regularisation: str | None = None


class OuvertureOut(DecimalBaseModel):
    id: int
    reference_numero: str
    date_ouverture: datetime
    caissier_id: UUID | None = None
    solde_ouverture_usd: Decimal
    solde_ouverture_cdf: Decimal
    solde_attendu_usd: Decimal = Decimal("0")
    solde_attendu_cdf: Decimal = Decimal("0")
    ecart_usd: Decimal = Decimal("0")
    ecart_cdf: Decimal = Decimal("0")
    billetage_usd: dict | None = None
    billetage_cdf: dict | None = None
    observation: str | None = None
    statut: str
    # Régularisations créées pour l'écart constaté, et messages d'échec le cas
    # échéant. Un échec n'empêche jamais l'ouverture : l'écart reste ouvert.
    regularisations: list[dict] = []
    regularisation_erreurs: list[str] = []


class ClotureOut(DecimalBaseModel):
    id: int
    reference_numero: str
    date_cloture: datetime
    date_debut: datetime | None = None
    caissier_id: UUID | None = None
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
    regularisations: list[dict] = []
    regularisation_erreurs: list[str] = []


class CloturePdfDetail(BaseModel):
    reference_numero: str | None = None
    beneficiaire: str | None = None
    motif: str | None = None
    montant_paye: Decimal | None = None


class CloturePdfData(DecimalBaseModel):
    cloture: ClotureOut
    details: list[CloturePdfDetail]
