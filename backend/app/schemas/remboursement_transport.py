from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import ConfigDict, Field

from app.schemas.base import DecimalBaseModel
from app.schemas.requisition import RequisitionWithUserOut


class ParticipantTransportBase(DecimalBaseModel):
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

    model_config = ConfigDict(from_attributes=True, json_encoders={Decimal: str})


class RemboursementTransportBase(DecimalBaseModel):
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
    reference_numero: str | None = None
    created_at: datetime
    created_by: str | None = None
    trans_titre_officiel_hist: str | None = None
    trans_label_gauche_hist: str | None = None
    trans_nom_gauche_hist: str | None = None
    trans_label_droite_hist: str | None = None
    trans_nom_droite_hist: str | None = None
    signataire_g_label: str | None = None
    signataire_g_nom: str | None = None
    signataire_d_label: str | None = None
    signataire_d_nom: str | None = None
    participants: list[ParticipantTransportResponse] | None = None
    requisition: RequisitionWithUserOut | None = None

    model_config = ConfigDict(from_attributes=True, json_encoders={Decimal: str})
