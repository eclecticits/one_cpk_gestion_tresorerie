from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RequisitionCreate(BaseModel):
    numero_requisition: str
    objet: str
    mode_paiement: str
    type_requisition: str
    montant_total: float
    status: str | None = None
    statut: str | None = None
    created_by: str | None = None
    a_valoir: bool | None = False
    instance_beneficiaire: str | None = None
    notes_a_valoir: str | None = None


class RequisitionUpdate(BaseModel):
    objet: str | None = None
    mode_paiement: str | None = None
    type_requisition: str | None = None
    montant_total: float | None = None
    status: str | None = None
    statut: str | None = None
    created_by: str | None = None
    validee_par: str | None = None
    validee_le: datetime | None = None
    approuvee_par: str | None = None
    approuvee_le: datetime | None = None
    payee_par: str | None = None
    payee_le: datetime | None = None
    motif_rejet: str | None = None
    a_valoir: bool | None = None
    instance_beneficiaire: str | None = None
    notes_a_valoir: str | None = None
    updated_at: datetime | None = None


class RequisitionOut(BaseModel):
    id: str
    numero_requisition: str
    objet: str
    mode_paiement: str
    type_requisition: str
    montant_total: float
    status: str
    statut: str
    created_by: str | None = None
    validee_par: str | None = None
    validee_le: datetime | None = None
    approuvee_par: str | None = None
    approuvee_le: datetime | None = None
    payee_par: str | None = None
    payee_le: datetime | None = None
    motif_rejet: str | None = None
    a_valoir: bool | None = False
    instance_beneficiaire: str | None = None
    notes_a_valoir: str | None = None
    created_at: datetime
    updated_at: datetime


class LigneRequisitionCreate(BaseModel):
    requisition_id: str
    rubrique: str
    description: str
    quantite: int = 1
    montant_unitaire: float
    montant_total: float


class LigneRequisitionOut(BaseModel):
    id: str
    requisition_id: str
    rubrique: str
    description: str
    quantite: int
    montant_unitaire: float
    montant_total: float


class RequisitionListResponse(BaseModel):
    items: list[RequisitionOut]
    total: int | None = None


class UserInfo(BaseModel):
    id: str
    prenom: str | None = None
    nom: str | None = None
    email: str | None = None


class RequisitionWithUserOut(RequisitionOut):
    demandeur: UserInfo | None = None
    validateur: UserInfo | None = None
    approbateur: UserInfo | None = None
    caissier: UserInfo | None = None
