from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from app.schemas.base import DecimalBaseModel


class RequisitionCreate(DecimalBaseModel):
    numero_requisition: str
    objet: str
    mode_paiement: str
    type_requisition: str
    montant_total: Decimal
    status: str | None = None
    statut: str | None = None
    created_by: str | None = None
    a_valoir: bool | None = False
    instance_beneficiaire: str | None = None
    notes_a_valoir: str | None = None


class RequisitionUpdate(DecimalBaseModel):
    objet: str | None = None
    mode_paiement: str | None = None
    type_requisition: str | None = None
    montant_total: Decimal | None = None
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


class RequisitionOut(DecimalBaseModel):
    id: str
    numero_requisition: str
    objet: str
    mode_paiement: str
    type_requisition: str
    montant_total: Decimal
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


class LigneRequisitionCreate(DecimalBaseModel):
    requisition_id: str
    budget_ligne_id: int | None = None
    rubrique: str
    description: str
    quantite: int = 1
    montant_unitaire: Decimal
    montant_total: Decimal
    devise: str | None = "USD"


class LigneRequisitionOut(DecimalBaseModel):
    id: str
    requisition_id: str
    budget_ligne_id: int | None = None
    rubrique: str
    description: str
    quantite: int
    montant_unitaire: Decimal
    montant_total: Decimal
    devise: str | None = "USD"


class RequisitionListResponse(DecimalBaseModel):
    items: list[RequisitionOut]
    total: int | None = None


class UserInfo(DecimalBaseModel):
    id: str
    prenom: str | None = None
    nom: str | None = None
    email: str | None = None


class RequisitionWithUserOut(RequisitionOut):
    demandeur: UserInfo | None = None
    validateur: UserInfo | None = None
    approbateur: UserInfo | None = None
    caissier: UserInfo | None = None
