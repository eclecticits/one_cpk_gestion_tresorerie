from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pydantic import Field, field_validator
from app.schemas.base import DecimalBaseModel


class RequisitionCreate(DecimalBaseModel):
    numero_requisition: str | None = None
    objet: str = Field(min_length=3)
    mode_paiement: str
    type_requisition: str
    montant_total: Decimal = Field(gt=0)
    status: str | None = "EN_ATTENTE"
    statut: str | None = None
    created_by: str | None = None
    a_valoir: bool | None = False
    instance_beneficiaire: str | None = None
    notes_a_valoir: str | None = None

    @field_validator("mode_paiement")
    @classmethod
    def validate_mode_paiement(cls, value: str):
        allowed = {"cash", "mobile_money", "virement"}
        if value.lower() not in allowed:
            raise ValueError("mode_paiement invalide")
        return value


class RequisitionUpdate(DecimalBaseModel):
    objet: str | None = None
    mode_paiement: str | None = None
    type_requisition: str | None = None
    montant_total: Decimal | None = Field(default=None, gt=0)
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

    @field_validator("mode_paiement")
    @classmethod
    def validate_mode_paiement(cls, value: str | None):
        if value is None:
            return value
        allowed = {"cash", "mobile_money", "virement"}
        if value.lower() not in allowed:
            raise ValueError("mode_paiement invalide")
        return value

class RequisitionOut(DecimalBaseModel):
    id: str
    numero_requisition: str
    reference_numero: str | None = None
    objet: str
    mode_paiement: str
    type_requisition: str
    montant_total: Decimal
    montant_deja_paye: Decimal | None = None
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
    req_titre_officiel_hist: str | None = None
    req_label_gauche_hist: str | None = None
    req_nom_gauche_hist: str | None = None
    req_label_droite_hist: str | None = None
    req_nom_droite_hist: str | None = None
    signataire_g_label: str | None = None
    signataire_g_nom: str | None = None
    signataire_d_label: str | None = None
    signataire_d_nom: str | None = None
    import_source: str | None = None
    annexe: "RequisitionAnnexeOut | None" = None
    created_at: datetime
    updated_at: datetime


class RequisitionAnnexeOut(DecimalBaseModel):
    id: str
    requisition_id: str
    file_path: str
    filename: str
    file_type: str
    file_size: int
    upload_date: datetime


class LigneRequisitionCreate(DecimalBaseModel):
    requisition_id: str
    budget_ligne_id: int | None = None
    rubrique: str = Field(min_length=2)
    description: str = Field(min_length=3)
    quantite: int = 1
    montant_unitaire: Decimal = Field(gt=0)
    montant_total: Decimal = Field(gt=0)
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
