from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict


MatchStatus = Literal["found", "missing", "conflict", "unmatched"]


class PdfRequisitionItem(BaseModel):
    numero_requisition: str | None = None
    montant: Decimal | None = None
    statut: str | None = None
    rubrique: str | None = None
    objet: str | None = None
    raw_line: str
    match_status: MatchStatus = "unmatched"
    db_id: str | None = None
    db_montant: Decimal | None = None
    db_status: str | None = None

    model_config = ConfigDict(from_attributes=True, json_encoders={Decimal: str})


class PdfRequisitionParseResponse(BaseModel):
    items: list[PdfRequisitionItem]
    raw_text_excerpt: str
    warnings: list[str] = []
    total_items: int = 0
    matched: int = 0
    conflicts: int = 0
    missing: int = 0


class PdfRequisitionImportItem(BaseModel):
    numero_requisition: str
    montant: Decimal
    objet: str | None = None
    rubrique: str | None = None


class PdfRequisitionImportRequest(BaseModel):
    items: list[PdfRequisitionImportItem]


class PdfRequisitionImportResponse(BaseModel):
    imported: int = 0
    skipped_existing: int = 0
    skipped_invalid: int = 0
    created_ids: list[str] = []
