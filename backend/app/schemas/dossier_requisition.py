from __future__ import annotations

from datetime import datetime
from uuid import UUID
from pydantic import Field

from app.schemas.base import DecimalBaseModel
from app.schemas.requisition import RequisitionOut


class DossierRequisitionCreate(DecimalBaseModel):
    requisition_ids: list[UUID] = Field(default_factory=list)
    description: str | None = None


class DossierRequisitionUpdate(DecimalBaseModel):
    description: str | None = None
    commentaires_examen: str | None = None


class DossierRequisitionAdd(DecimalBaseModel):
    requisition_ids: list[UUID] = Field(default_factory=list)


class DossierRequisitionRemove(DecimalBaseModel):
    requisition_ids: list[UUID] = Field(default_factory=list)


class DossierRequisitionOut(DecimalBaseModel):
    id: UUID
    reference: str
    description: str | None = None
    status: str
    commentaires_examen: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime
    rejete_le: datetime | None = None
    # Fin du délai de décision après un rejet (rouvrir ou accepter).
    rejet_echeance: datetime | None = None
    rejet_accepte_le: datetime | None = None
    rejet_accepte_par: UUID | None = None
    requisitions: list[RequisitionOut] = []


DossierRequisitionOut.model_rebuild()
