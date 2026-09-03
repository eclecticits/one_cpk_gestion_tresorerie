from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from pydantic import Field, field_validator, model_validator
from app.schemas.base import DecimalBaseModel
from app.services.reglement import MODE_PAIEMENT_MIXTE, MODES_PAIEMENT
from uuid import UUID


class LigneRequisitionInline(DecimalBaseModel):
    """Ligne fournie à la création de la réquisition (pas encore d'identifiant
    de réquisition à référencer : les deux sont écrits dans la même
    transaction)."""

    budget_poste_id: int | None = None
    rubrique: str = Field(min_length=2)
    description: str = Field(min_length=3)
    quantite: int = 1
    montant_unitaire: Decimal = Field(gt=0)
    montant_total: Decimal = Field(gt=0)
    devise: str | None = "USD"
    # Intention de règlement. Absente, la ligne hérite du mode de la réquisition
    # — c'est le cas courant, mono-mode, où la saisie ne change pas.
    mode_paiement: str | None = None
    compte_bancaire_id: int | None = None

    @field_validator("mode_paiement")
    @classmethod
    def validate_ligne_mode_paiement(cls, value: str | None):
        if value is None:
            return value
        if value.lower() not in MODES_PAIEMENT:
            raise ValueError("mode_paiement invalide")
        return value.lower()


class VoletReglementOut(DecimalBaseModel):
    """Regroupement des lignes partageant le même couple (mode, compte). C'est
    l'unité autorisée puis payée indépendamment des autres."""

    mode_paiement: str
    canal: str
    compte_bancaire_id: int | None = None
    montant_total: Decimal
    lignes_ids: list[str] = []


class RequisitionCreate(DecimalBaseModel):
    numero_requisition: str | None = None
    objet: str = Field(min_length=3)
    mode_paiement: str
    type_requisition: str
    nature_requisition: Literal["BUDGETAIRE", "HORS_BUDGET", "FONDS_DE_TIERS"] = "BUDGETAIRE"
    montant_total: Decimal = Field(gt=0)
    # Date métier, antidatable. Absente -> le serveur prend l'instant courant.
    date_requisition: datetime | None = None
    devise: str | None = "USD"
    service_id: int | None = None
    compte_bancaire_id: int | None = None
    status: str | None = "EN_ATTENTE"
    statut: str | None = None
    created_by: UUID | None = None
    a_valoir: bool | None = False
    decaissement_progressif: bool | None = False
    beneficiaire: str | None = Field(default=None, max_length=200)
    instance_beneficiaire: str | None = None
    tiers_organisation_id: int | None = None
    tiers_nom_libre: str | None = Field(default=None, max_length=255)
    notes_a_valoir: str | None = None
    # Lignes créées avec la réquisition. Absentes = création nue (parcours
    # historiques : remboursement transport, imports).
    lignes: list[LigneRequisitionInline] | None = None

    @field_validator("mode_paiement")
    @classmethod
    def validate_mode_paiement(cls, value: str):
        # `mixte` est accepté ici : c'est le résumé d'une réquisition dont les
        # lignes divergent. Le serveur le recalcule de toute façon depuis les
        # lignes, il n'est jamais cru sur parole.
        if value.lower() not in MODES_PAIEMENT | {MODE_PAIEMENT_MIXTE}:
            raise ValueError("mode_paiement invalide")
        return value

    @field_validator("type_requisition")
    @classmethod
    def validate_type_requisition(cls, value: str):
        allowed = {"classique", "remboursement_transport"}
        if value.lower() not in allowed:
            raise ValueError("type_requisition invalide")
        return value

    @field_validator("nature_requisition", mode="before")
    @classmethod
    def normaliser_nature_requisition(cls, value):
        # `mode="before"` est indispensable : la validation du Literal rejette
        # « budgetaire » avant qu'un validateur `after` ne puisse le remonter en
        # capitales, ce qui rendait la normalisation inopérante.
        if value is None:
            return "BUDGETAIRE"
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @model_validator(mode="after")
    def validate_instance_beneficiaire(self):
        # Une avance « à valoir » est une créance : sans instance bénéficiaire,
        # personne n'est désigné pour la rembourser et la dette est orpheline.
        if self.a_valoir and not (self.instance_beneficiaire or "").strip():
            raise ValueError("instance_beneficiaire est requis pour une réquisition à valoir")
        if self.type_requisition == "remboursement_transport" and self.nature_requisition != "BUDGETAIRE":
            raise ValueError("remboursement_transport doit rester une réquisition BUDGETAIRE")
        if self.nature_requisition == "FONDS_DE_TIERS":
            tiers_nom = (self.tiers_nom_libre or "").strip() or None
            if self.tiers_organisation_id is not None and tiers_nom is not None:
                raise ValueError("tiers_organisation_id et tiers_nom_libre sont exclusifs")
            if self.tiers_organisation_id is None and tiers_nom is None:
                raise ValueError("tiers_organisation_id ou tiers_nom_libre requis pour FONDS_DE_TIERS")
            self.tiers_nom_libre = tiers_nom
        else:
            self.tiers_organisation_id = None
            self.tiers_nom_libre = None
        if self.beneficiaire is not None:
            self.beneficiaire = self.beneficiaire.strip() or None
        # Un mouvement hors budget n'a ni ligne ni poste : le bénéficiaire est
        # la seule pièce qui désigne à qui l'argent va. Sans lui, la sortie
        # descendait d'une source anonyme et s'enregistrait sous un libellé de
        # remplissage. FONDS_DE_TIERS est dispensé : son bénéficiaire est le
        # tiers créancier, déjà identifié et imposé au paiement.
        if self.nature_requisition == "HORS_BUDGET" and not self.beneficiaire:
            raise ValueError("beneficiaire est requis pour une réquisition HORS_BUDGET")
        return self


class RequisitionUpdate(DecimalBaseModel):
    objet: str | None = None
    mode_paiement: str | None = None
    type_requisition: str | None = None
    nature_requisition: Literal["BUDGETAIRE", "HORS_BUDGET", "FONDS_DE_TIERS"] | None = None
    montant_total: Decimal | None = Field(default=None, gt=0)
    service_id: int | None = None
    compte_bancaire_id: int | None = None
    status: str | None = None
    statut: str | None = None
    created_by: UUID | None = None
    validee_par: UUID | None = None
    validee_le: datetime | None = None
    approuvee_par: UUID | None = None
    approuvee_le: datetime | None = None
    signed_by_id: UUID | None = None
    signed_at: datetime | None = None
    payee_par: UUID | None = None
    payee_le: datetime | None = None
    motif_rejet: str | None = None
    a_valoir: bool | None = None
    decaissement_progressif: bool | None = None
    beneficiaire: str | None = Field(default=None, max_length=200)
    instance_beneficiaire: str | None = None
    tiers_organisation_id: int | None = None
    tiers_nom_libre: str | None = Field(default=None, max_length=255)
    notes_a_valoir: str | None = None
    updated_at: datetime | None = None

    @field_validator("mode_paiement")
    @classmethod
    def validate_mode_paiement(cls, value: str | None):
        if value is None:
            return value
        if value.lower() not in MODES_PAIEMENT | {MODE_PAIEMENT_MIXTE}:
            raise ValueError("mode_paiement invalide")
        return value

    @field_validator("type_requisition")
    @classmethod
    def validate_type_requisition(cls, value: str | None):
        if value is None:
            return value
        allowed = {"classique", "remboursement_transport"}
        if value.lower() not in allowed:
            raise ValueError("type_requisition invalide")
        return value

    @field_validator("nature_requisition", mode="before")
    @classmethod
    def normaliser_nature_requisition(cls, value):
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @model_validator(mode="after")
    def validate_fonds_tiers_identity(self):
        if self.beneficiaire is not None:
            self.beneficiaire = self.beneficiaire.strip() or None
        if self.tiers_nom_libre is not None:
            self.tiers_nom_libre = self.tiers_nom_libre.strip() or None
        if self.tiers_organisation_id is not None and self.tiers_nom_libre is not None:
            raise ValueError("tiers_organisation_id et tiers_nom_libre sont exclusifs")
        return self

class RequisitionOut(DecimalBaseModel):
    id: UUID
    numero_requisition: str
    reference_numero: str | None = None
    objet: str
    mode_paiement: str
    type_requisition: str
    nature_requisition: Literal["BUDGETAIRE", "HORS_BUDGET", "FONDS_DE_TIERS"] = "BUDGETAIRE"
    montant_total: Decimal
    date_requisition: datetime | None = None
    devise: str | None = "USD"
    montant_deja_paye: Decimal | None = None
    lignes_count: int | None = None
    service_id: int | None = None
    compte_bancaire_id: int | None = None
    # Découpage du règlement, dérivé des lignes. Une seule entrée dans le cas
    # courant ; plusieurs dès que les lignes visent des modes ou des comptes
    # différents, chacune payable indépendamment des autres.
    volets_reglement: list[VoletReglementOut] | None = None
    status: str
    statut: str
    dossier_id: UUID | None = None
    examen_status: str | None = None
    examen_commentaire: str | None = None
    examen_par: UUID | None = None
    examen_le: datetime | None = None
    created_by: UUID | None = None
    validee_par: UUID | None = None
    validee_le: datetime | None = None
    approuvee_par: UUID | None = None
    approuvee_le: datetime | None = None
    signed_by_id: UUID | None = None
    signed_at: datetime | None = None
    payee_par: UUID | None = None
    payee_le: datetime | None = None
    motif_rejet: str | None = None
    a_valoir: bool | None = False
    decaissement_progressif: bool | None = False
    beneficiaire: str | None = None
    instance_beneficiaire: str | None = None
    tiers_organisation_id: int | None = None
    tiers_nom_libre: str | None = None
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
    print_settings_snapshot: dict[str, Any] | None = None
    organisation_snapshot: dict[str, Any] | None = None
    bank_account_snapshot: dict[str, Any] | None = None
    signatories_snapshot: dict[str, Any] | None = None
    historical_snapshot_status: str | None = None
    snapshot_created_at: datetime | None = None
    snapshot_version: int | None = None
    row_version: int | None = None
    exchange_rate_snapshot: Decimal | None = None
    exchange_rate_source: str | None = None
    exchange_rate_date: datetime | None = None
    base_amount_snapshot: Decimal | None = None
    converted_amount_snapshot: Decimal | None = None
    import_source: str | None = None
    annexe: "RequisitionAnnexeOut | None" = None
    remboursement_transport: dict[str, Any] | None = None
    lignes: "list[LigneRequisitionOut] | None" = None
    created_at: datetime
    updated_at: datetime


class RequisitionAnnexeOut(DecimalBaseModel):
    id: UUID
    requisition_id: UUID
    file_path: str
    filename: str
    file_type: str
    file_size: int
    upload_date: datetime


class LigneRequisitionCreate(DecimalBaseModel):
    requisition_id: UUID
    budget_poste_id: int | None = None
    rubrique: str = Field(min_length=2)
    description: str = Field(min_length=3)
    quantite: int = 1
    montant_unitaire: Decimal = Field(gt=0)
    montant_total: Decimal = Field(gt=0)
    devise: str | None = "USD"
    mode_paiement: str | None = None
    compte_bancaire_id: int | None = None

    @field_validator("mode_paiement")
    @classmethod
    def validate_ligne_mode_paiement(cls, value: str | None):
        if value is None:
            return value
        if value.lower() not in MODES_PAIEMENT:
            raise ValueError("mode_paiement invalide")
        return value.lower()




class LigneRequisitionOut(DecimalBaseModel):
    id: UUID
    requisition_id: UUID
    budget_poste_id: int | None = None
    rubrique: str
    description: str
    quantite: int
    montant_unitaire: Decimal
    montant_total: Decimal
    devise: str | None = "USD"
    mode_paiement: str | None = None
    compte_bancaire_id: int | None = None
    budget_poste_code_snapshot: str | None = None
    budget_poste_libelle_snapshot: str | None = None
    montant_alloue_snapshot: Decimal | None = None
    montant_disponible_snapshot: Decimal | None = None


class RequisitionListResponse(DecimalBaseModel):
    items: list[RequisitionOut]
    total: int | None = None


class UserInfo(DecimalBaseModel):
    id: UUID
    prenom: str | None = None
    nom: str | None = None
    email: str | None = None


class RequisitionWithUserOut(RequisitionOut):
    demandeur: UserInfo | None = None
    validateur: UserInfo | None = None
    approbateur: UserInfo | None = None
    examinateur: UserInfo | None = None
    caissier: UserInfo | None = None


RequisitionOut.model_rebuild()
RequisitionWithUserOut.model_rebuild()


class RequisitionExamenPayload(DecimalBaseModel):
    commentaire: str | None = None
