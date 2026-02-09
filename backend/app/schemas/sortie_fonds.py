from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.schemas.base import DecimalBaseModel
from app.schemas.requisition import RequisitionOut


class SortieFondsCreate(DecimalBaseModel):
    type_sortie: str
    requisition_id: str | None = None
    rubrique_code: str | None = None
    budget_ligne_id: int | None = None
    montant_paye: Decimal
    date_paiement: datetime | str | None = None
    mode_paiement: str
    reference: str | None = None
    statut: str | None = None
    motif: str
    beneficiaire: str
    piece_justificative: str | None = None
    commentaire: str | None = None
    created_by: str | None = None


class SortieFondsOut(DecimalBaseModel):
    id: str
    type_sortie: str
    requisition_id: str | None = None
    rubrique_code: str | None = None
    budget_ligne_id: int | None = None
    montant_paye: Decimal
    date_paiement: datetime | None = None
    mode_paiement: str
    reference: str | None = None
    reference_numero: str | None = None
    statut: str
    motif_annulation: str | None = None
    motif: str
    beneficiaire: str
    piece_justificative: str | None = None
    commentaire: str | None = None
    created_by: str | None = None
    created_at: datetime
    requisition: RequisitionOut | None = None


class SortiesFondsListResponse(DecimalBaseModel):
    items: list[SortieFondsOut]
    total: int
    total_montant_paye: Decimal = Decimal("0")


class SortieFondsStatusUpdate(DecimalBaseModel):
    statut: str
    motif_annulation: str | None = None
