from __future__ import annotations

from datetime import datetime
from pydantic import Field

from app.schemas.base import DecimalBaseModel
from app.schemas.requisition import RequisitionOut


class DossierRequisitionCreate(DecimalBaseModel):
    requisition_ids: list[str] = Field(default_factory=list)
    description: str | None = None


class DossierRequisitionUpdate(DecimalBaseModel):
    description: str | None = None
    commentaires_examen: str | None = None


class DossierRequisitionOut(DecimalBaseModel):
    id: str
    reference: str
    description: str | None = None
    status: str
    commentaires_examen: str | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime
    requisitions: list[RequisitionOut] = []
