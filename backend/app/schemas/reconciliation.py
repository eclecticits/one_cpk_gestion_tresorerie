from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from app.schemas.base import DecimalBaseModel


TransactionType = Literal["encaissement", "sortie"]


class ReconcilePatch(DecimalBaseModel):
    is_reconciled: bool = True
    bank_statement_ref: str | None = None


class ReconcileItem(DecimalBaseModel):
    transaction_type: TransactionType
    transaction_id: UUID
    is_reconciled: bool = True
    bank_statement_ref: str | None = None


class ReconcileBatchRequest(DecimalBaseModel):
    items: list[ReconcileItem]


class ReconcileResult(DecimalBaseModel):
    transaction_type: TransactionType
    transaction_id: UUID
    is_reconciled: bool
    reconciled_at: datetime | None = None
    reconciled_by_id: UUID | None = None
    bank_statement_ref: str | None = None


class ReconcileBatchResponse(DecimalBaseModel):
    updated: int
    items: list[ReconcileResult]
