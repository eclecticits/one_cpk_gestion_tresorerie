from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.base import DecimalBaseModel
from app.schemas.requisition import UserInfo
from app.services.reglement import MODES_PAIEMENT


class OrdreDecaissementCreate(DecimalBaseModel):
    # None = ordre de sortie directe (sans réquisition), plafonné à 100 USD
    requisition_id: UUID | None = None
    beneficiaire: str = Field(min_length=2, max_length=200)
    montant: Decimal = Field(gt=0)
    devise: Literal["USD", "CDF"] = "USD"
    motif: str | None = None
    # Définition « en amont » (sorties directes programmées type réquisition).
    service_id: int | None = None
    # Répartition de la tranche par poste budgétaire. Chaque entrée :
    # {budget_poste_id, montant (ou montant_total), libelle?}. Somme = montant.
    lignes: list[dict[str, Any]] | None = None
    # Volet de règlement de la tranche. Absent, l'ordre hérite du mode de la
    # réquisition — comportement historique. Le canal est toujours déduit du
    # mode, jamais reçu du client.
    mode_paiement: str | None = None
    compte_bancaire_id: int | None = None

    @field_validator("mode_paiement")
    @classmethod
    def validate_mode_paiement(cls, value: str | None):
        if value is None:
            return value
        if value.lower() not in MODES_PAIEMENT:
            raise ValueError("mode_paiement invalide")
        return value.lower()


class OrdreDecaissementCancel(DecimalBaseModel):
    motif_annulation: str = Field(min_length=3)


class OrdreDecaissementOut(DecimalBaseModel):
    id: UUID
    organisation_id: int
    requisition_id: UUID | None = None
    numero_ordre: str
    beneficiaire: str
    montant: Decimal
    montant_usd_snapshot: Decimal | None = None
    devise: str
    motif: str | None = None
    service_id: int | None = None
    lignes: list[dict[str, Any]] | None = None
    mode_paiement: str | None = None
    canal: str | None = None
    compte_bancaire_id: int | None = None
    statut: str
    autorise_par: UUID | None = None
    autorise_le: datetime | None = None
    autorise_par_user: UserInfo | None = None
    paye_par: UUID | None = None
    paye_le: datetime | None = None
    paye_par_user: UserInfo | None = None
    sortie_fonds_id: UUID | None = None
    sortie_reference_numero: str | None = None
    annule_par: UUID | None = None
    annule_le: datetime | None = None
    motif_annulation: str | None = None
    created_at: datetime
    requisition_numero: str | None = None
    requisition_objet: str | None = None
    requisition_montant_total: Decimal | None = None
    requisition_status: str | None = None


class OrdreDecaissementListResponse(DecimalBaseModel):
    items: list[OrdreDecaissementOut]
    total: int
    montant_total_requisition: Decimal | None = None
    total_paye: Decimal = Decimal("0")
    total_autorise_non_paye: Decimal = Decimal("0")
    reliquat: Decimal | None = None
