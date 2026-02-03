from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.requisition import RequisitionWithUserOut


class ParticipantTransportBase(BaseModel):
    nom: str
    titre_fonction: str
    montant: Decimal = Field(default=0)
    type_participant: Literal["principal", "assistant"]
    expert_comptable_id: str | None = None


class ParticipantTransportCreate(ParticipantTransportBase):
    remboursement_id: str


class ParticipantTransportResponse(ParticipantTransportBase):
    id: str
    remboursement_id: str
    created_at: datetime

    class Config:
        from_attributes = True


class RemboursementTransportBase(BaseModel):
    instance: str
    type_reunion: Literal["bureau", "commission", "conseil", "atelier"]
    nature_reunion: str
    nature_travail: list[str] = Field(default_factory=list)
    lieu: str
    date_reunion: datetime
    heure_debut: str | None = None
    heure_fin: str | None = None
    montant_total: Decimal = Field(default=0)
    requisition_id: str | None = None


class RemboursementTransportCreate(RemboursementTransportBase):
    created_by: str | None = None


class RemboursementTransportResponse(RemboursementTransportBase):
    id: str
    numero_remboursement: str
    created_at: datetime
    created_by: str | None = None
    participants: list[ParticipantTransportResponse] | None = None
    requisition: RequisitionWithUserOut | None = None

    class Config:
        from_attributes = True
