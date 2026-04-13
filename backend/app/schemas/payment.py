from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator

from app.schemas.base import DecimalBaseModel


ModePaiement = Literal["cash", "mobile_money", "virement", "card"]
StatutPaiement = Literal["non_paye", "partiel", "complet", "avance"]
CanalPaiement = Literal["CAISSE", "BANQUE"]


class PaymentHistoryBase(DecimalBaseModel):
    montant: Decimal = Field(gt=0)
    mode_paiement: ModePaiement = "cash"
    reference: str | None = None
    notes: str | None = None


class PaymentHistoryCreate(PaymentHistoryBase):
    encaissement_id: UUID


class PaymentHistoryResponse(PaymentHistoryBase):
    id: UUID
    encaissement_id: UUID
    created_by: UUID | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, json_encoders={Decimal: str})


class EncaissementBase(DecimalBaseModel):
    numero_recu: str | None = Field(default=None, max_length=50)
    numero_proforma: str | None = Field(default=None, max_length=50)
    est_proforma: bool = False
    source_proforma_id: UUID | None = None
    type_client: str
    expert_comptable_id: UUID | None = None
    client_nom: str | None = None
    libelle: str = Field(max_length=255)
    description: str | None = None
    montant: Decimal = Field(ge=0)
    montant_total: Decimal = Field(gt=0)
    mode_paiement: ModePaiement = "cash"
    reference: str | None = None
    canal: CanalPaiement = "CAISSE"
    compte_bancaire_id: int | None = None
    piece_jointe: str | None = None
    montant_paye: Decimal = Field(ge=0, default=0)
    montant_percu: Decimal = Field(ge=0, default=0)
    devise_perception: Literal["USD", "CDF"] = "USD"
    taux_change_applique: Decimal = Field(ge=0, default=1)
    statut_paiement: StatutPaiement = "non_paye"
    date_encaissement: datetime | None = None
    date_paiement: datetime | None = None
    budget_poste_id: int | None = None
    service_id: int | None = None

    @field_validator("date_encaissement")
    @classmethod
    def validate_date_encaissement(cls, value: datetime | None):
        if value is None:
            return value
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if value > now:
            raise ValueError("La date d'encaissement ne peut pas être dans le futur")
        return value


class EncaissementCreate(EncaissementBase):
    created_by: UUID | None = None
    notes_paiement: str | None = None


class ProformaConversion(DecimalBaseModel):
    montant_paye: Decimal | None = None
    mode_paiement: ModePaiement | None = None
    reference: str | None = None
    notes_paiement: str | None = None
    canal: CanalPaiement | None = None
    compte_bancaire_id: int | None = None
    date_paiement: datetime | None = None


class EncaissementResponse(EncaissementBase):
    id: UUID
    date_encaissement: datetime
    created_by: UUID | None = None
    created_at: datetime
    budget_poste_code: str | None = None
    budget_poste_libelle: str | None = None
    is_reconciled: bool = False
    reconciled_at: datetime | None = None
    reconciled_by_id: UUID | None = None
    bank_statement_ref: str | None = None
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
