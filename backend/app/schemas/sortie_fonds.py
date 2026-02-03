from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.schemas.requisition import RequisitionOut


class SortieFondsCreate(BaseModel):
    type_sortie: str
    requisition_id: str | None = None
    rubrique_code: str | None = None
    montant_paye: Decimal
    date_paiement: datetime | str | None = None
    mode_paiement: str
    reference: str | None = None
    motif: str
    beneficiaire: str
    piece_justificative: str | None = None
    commentaire: str | None = None
    created_by: str | None = None


class SortieFondsOut(BaseModel):
    id: str
    type_sortie: str
    requisition_id: str | None = None
    rubrique_code: str | None = None
    montant_paye: Decimal
    date_paiement: datetime | None = None
    mode_paiement: str
    reference: str | None = None
    motif: str
    beneficiaire: str
    piece_justificative: str | None = None
    commentaire: str | None = None
    created_by: str | None = None
    created_at: datetime
    requisition: RequisitionOut | None = None
