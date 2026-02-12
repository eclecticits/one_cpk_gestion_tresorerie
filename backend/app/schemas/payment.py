from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import ConfigDict, Field

from app.schemas.base import DecimalBaseModel


ModePaiement = Literal["cash", "mobile_money", "virement"]
StatutPaiement = Literal["non_paye", "partiel", "complet", "avance"]


class PaymentHistoryBase(DecimalBaseModel):
    montant: Decimal = Field(gt=0)
    mode_paiement: ModePaiement = "cash"
    reference: str | None = None
    notes: str | None = None


class PaymentHistoryCreate(PaymentHistoryBase):
    encaissement_id: str


class PaymentHistoryResponse(PaymentHistoryBase):
    id: str
    encaissement_id: str
    created_by: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, json_encoders={Decimal: str})


class EncaissementBase(DecimalBaseModel):
    numero_recu: str = Field(max_length=50)
    type_client: str
    expert_comptable_id: str | None = None
    client_nom: str | None = None
    type_operation: str
    description: str | None = None
    montant: Decimal = Field(ge=0)
    montant_total: Decimal = Field(ge=0)
    mode_paiement: ModePaiement = "cash"
    reference: str | None = None
    montant_paye: Decimal = Field(ge=0, default=0)
    montant_percu: Decimal = Field(ge=0, default=0)
    devise_perception: Literal["USD", "CDF"] = "USD"
    taux_change_applique: Decimal = Field(ge=0, default=1)
    statut_paiement: StatutPaiement = "non_paye"
    date_encaissement: datetime | None = None
    budget_ligne_id: int | None = None


class EncaissementCreate(EncaissementBase):
    created_by: str | None = None


class EncaissementResponse(EncaissementBase):
    id: str
    date_encaissement: datetime
    created_by: str | None = None
    created_at: datetime
    # Expert comptable associé (optionnel, pour affichage)
    expert_comptable: dict | None = None

    model_config = ConfigDict(from_attributes=True, json_encoders={Decimal: str})


class EncaissementWithPayments(EncaissementResponse):
    payment_history: list[PaymentHistoryResponse] = []


class EncaissementsListResponse(DecimalBaseModel):
    items: list[EncaissementResponse]
    total: int
    total_montant_facture: Decimal = Decimal("0")
    total_montant_paye: Decimal = Decimal("0")
