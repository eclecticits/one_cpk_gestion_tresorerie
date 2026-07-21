from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from app.schemas.base import DecimalBaseModel
from app.schemas.requisition import RequisitionOut, RequisitionWithUserOut, UserInfo
from uuid import UUID


class SortieFondsCreate(DecimalBaseModel):
    type_sortie: str
    requisition_id: UUID | None = None
    ordre_decaissement_id: UUID | None = None
    rubrique_code: str | None = None
    budget_poste_id: int | None = None
    service_id: int | None = None
    montant_paye: Decimal
    date_paiement: datetime | str | None = None
    mode_paiement: str
    reference: str | None = None
    devise: Literal["USD", "CDF"] = "USD"
    canal: Literal["CAISSE", "BANQUE"] = "CAISSE"
    compte_bancaire_id: int | None = None
    statut: str | None = None
    motif: str
    beneficiaire: str
    piece_justificative: str | None = None
    commentaire: str | None = None
    created_by: UUID | None = None


class SortieFondsOut(DecimalBaseModel):
    id: UUID
    type_sortie: str
    requisition_id: UUID | None = None
    rubrique_code: str | None = None
    budget_poste_id: int | None = None
    budget_poste_code: str | None = None
    budget_poste_libelle: str | None = None
    service_id: int | None = None
    montant_paye: Decimal
    date_paiement: datetime | None = None
    mode_paiement: str
    reference: str | None = None
    devise: Literal["USD", "CDF"] = "USD"
    canal: Literal["CAISSE", "BANQUE"] = "CAISSE"
    compte_bancaire_id: int | None = None
    reference_numero: str | None = None
    pdf_path: str | None = None
    statut: str
    motif_annulation: str | None = None
    annulee_le: datetime | None = None
    annulee_par_id: UUID | None = None
    annulation_ip: str | None = None
    ancien_statut: str | None = None
    exchange_rate_snapshot: Decimal | None = None
    motif: str
    beneficiaire: str
    piece_justificative: str | None = None
    commentaire: str | None = None
    annexes: list[str] | None = None
    created_by: UUID | None = None
    created_by_user: UserInfo | None = None
    programme_par_id: UUID | None = None
    programme_par_user: UserInfo | None = None
    annulee_par_user: UserInfo | None = None
    created_at: datetime
    requisition: RequisitionWithUserOut | RequisitionOut | None = None
    is_reconciled: bool = False
    reconciled_at: datetime | None = None
    reconciled_by_id: UUID | None = None
    bank_statement_ref: str | None = None


class SortiesFondsListResponse(DecimalBaseModel):
    items: list[SortieFondsOut]
    total: int
    total_montant_paye: Decimal = Decimal("0")


class SortieFondsStatusUpdate(DecimalBaseModel):
    statut: str
    motif_annulation: str | None = None


class SortieFondsPaymentRejectPayload(DecimalBaseModel):
    motif_rejet: str
