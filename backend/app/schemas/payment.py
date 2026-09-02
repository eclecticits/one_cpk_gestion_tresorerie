from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator

from app.schemas.base import DecimalBaseModel
from app.schemas.requisition import UserInfo


ModePaiement = Literal["cash", "mobile_money", "virement", "card", "cheque"]
StatutPaiement = Literal["non_paye", "partiel", "complet", "avance"]
CanalPaiement = Literal["CAISSE", "BANQUE"]
PaymentHistoryStatut = Literal["ACTIF", "ANNULE"]
PaymentAccountingStatut = Literal["NON_APPLICABLE", "EN_ATTENTE", "COMPTABILISE"]


class PaymentHistoryBase(DecimalBaseModel):
    montant: Decimal = Field(gt=0)
    mode_paiement: ModePaiement = "cash"
    reference: str | None = None
    notes: str | None = None


class PaymentHistoryCreate(PaymentHistoryBase):
    encaissement_id: UUID


class PaymentHistoryResponse(PaymentHistoryBase):
    id: UUID
    encaissement_id: UUID
    devise: Literal["USD", "CDF"] = "USD"
    canal: CanalPaiement = "CAISSE"
    compte_bancaire_id: int | None = None
    budget_poste_id: int | None = None
    taux_change_applique: Decimal = Decimal("1")
    date_paiement: datetime
    statut: PaymentHistoryStatut = "ACTIF"
    statut_comptabilisation: PaymentAccountingStatut = "NON_APPLICABLE"
    message_comptabilisation: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    annule_le: datetime | None = None
    annule_par_id: UUID | None = None
    motif_annulation: str | None = None
    annulation_ip: str | None = None

    model_config = ConfigDict(from_attributes=True, json_encoders={Decimal: str})


class PaymentHistoryCancelPayload(DecimalBaseModel):
    motif_annulation: str = Field(min_length=3, max_length=2000)


class EncaissementArticleBase(DecimalBaseModel):
    libelle: str = Field(max_length=255)
    description: str | None = None
    quantite: Decimal = Field(gt=0, default=1)
    prix_unitaire: Decimal = Field(ge=0)
    montant: Decimal | None = Field(default=None, ge=0)


class EncaissementArticleCreate(EncaissementArticleBase):
    pass


class EncaissementArticleResponse(EncaissementArticleBase):
    id: UUID
    encaissement_id: UUID
    montant: Decimal = Field(ge=0)
    sort_order: int = 0
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, json_encoders={Decimal: str})


class EncaissementBase(DecimalBaseModel):
    numero_recu: str | None = Field(default=None, max_length=50)
    numero_proforma: str | None = Field(default=None, max_length=50)
    est_proforma: bool = False
    source_proforma_id: UUID | None = None
    type_client: str
    expert_comptable_id: UUID | None = None
    client_nom: str | None = None
    # Référentiel clients : id d'un client existant (anti-doublons) et
    # coordonnées pour créer/compléter la fiche client à la volée.
    client_id: UUID | None = None
    client_email: str | None = None
    client_telephone: str | None = None
    libelle: str = Field(max_length=255)
    description: str | None = None
    montant: Decimal = Field(ge=0)
    montant_total: Decimal = Field(gt=0)
    mode_paiement: ModePaiement = "cash"
    reference: str | None = None
    canal: CanalPaiement = "CAISSE"
    compte_bancaire_id: int | None = None
    piece_jointe: str | None = None
    montant_paye: Decimal = Field(ge=0, default=0)
    montant_percu: Decimal = Field(ge=0, default=0)
    devise_perception: Literal["USD", "CDF"] = "USD"
    taux_change_applique: Decimal = Field(ge=0, default=1)
    statut_paiement: StatutPaiement = "non_paye"
    nature_mouvement: Literal["BUDGETAIRE", "HORS_BUDGET_A_REGULARISER", "FONDS_DE_TIERS", "TRANSFERT_INTERNE"] = "BUDGETAIRE"
    impact_budgetaire: bool | None = None
    hors_budget_status: Literal["A_REGULARISER", "PARTIELLEMENT_AFFECTE", "AFFECTE_BUDGET", "MAINTENU_HORS_BUDGET", "ANNULE"] | None = None
    fonds_tiers_display_name: str | None = None
    fonds_tiers_type: Literal["ORGANISATION", "EXTERNE", "LEGACY"] | None = None
    statut_operation: Literal["ACTIVE", "ANNULEE"] = "ACTIVE"
    motif_annulation: str | None = None
    annulee_le: datetime | None = None
    annulee_par_id: UUID | None = None
    annulation_ip: str | None = None
    ancien_statut_operation: str | None = None
    date_encaissement: datetime | None = None
    date_paiement: datetime | None = None
    budget_poste_id: int | None = None
    service_id: int | None = None
    project_activity_id: int | None = None
    articles: list[EncaissementArticleCreate] | None = None

    @field_validator("date_encaissement")
    @classmethod
    def validate_date_encaissement(cls, value: datetime | None):
        if value is None:
            return value
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if value > now:
            raise ValueError("La date d'encaissement ne peut pas être dans le futur")
        return value

    @field_validator("client_email")
    @classmethod
    def validate_client_email(cls, value: str | None):
        # Tolère l'absence d'email mais valide le format si fourni (F3).
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        from email_validator import EmailNotValidError, validate_email

        try:
            return validate_email(cleaned, check_deliverability=False).normalized
        except EmailNotValidError as exc:
            raise ValueError(f"Adresse email client invalide : {exc}") from exc


class FondsTiersCreate(DecimalBaseModel):
    tiers_organisation_id: int | None = None
    tiers_nom_libre: str | None = Field(default=None, max_length=255)
    payeur_origine: str | None = Field(default=None, max_length=255)
    motif: str | None = None
    reference: str | None = Field(default=None, max_length=100)
    piece_justificative: str | None = Field(default=None, max_length=200)


class EncaissementCreate(EncaissementBase):
    created_by: UUID | None = None
    notes_paiement: str | None = None
    #: Renseigné uniquement quand `nature_mouvement` vaut `FONDS_DE_TIERS` :
    #: décrit le tiers pour qui l'argent est encaissé.
    fonds_tiers: FondsTiersCreate | None = None


class BudgetAffectationLine(DecimalBaseModel):
    budget_poste_id: int
    montant: Decimal = Field(gt=0)


class AffecterBudgetPayload(DecimalBaseModel):
    lignes: list[BudgetAffectationLine] = Field(min_length=1)
    justification: str = Field(min_length=3)
    reference: str | None = Field(default=None, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=128)


class ProformaConversion(DecimalBaseModel):
    montant_paye: Decimal | None = None
    mode_paiement: ModePaiement | None = None
    reference: str | None = None
    notes_paiement: str | None = None
    canal: CanalPaiement | None = None
    compte_bancaire_id: int | None = None
    date_paiement: datetime | None = None


class EncaissementCancelPayload(DecimalBaseModel):
    motif_annulation: str = Field(min_length=3, max_length=2000)


class EncaissementResponse(EncaissementBase):
    id: UUID
    date_encaissement: datetime
    relance_count: int = 0
    derniere_relance_le: datetime | None = None
    created_by: UUID | None = None
    created_at: datetime
    budget_poste_code: str | None = None
    budget_poste_libelle: str | None = None
    project_activity_name: str | None = None
    #: Part de ce mouvement déjà imputée au budget par régularisation. Nulle pour
    #: un encaissement budgétaire, qui impute au fil des paiements.
    montant_affecte_budget: Decimal = Decimal("0")
    statut_comptabilisation: str = "NON_COMPTABILISEE"
    message_comptabilisation: str | None = None
    is_reconciled: bool = False
    reconciled_at: datetime | None = None
    reconciled_by_id: UUID | None = None
    bank_statement_ref: str | None = None
    articles: list[EncaissementArticleResponse] = []
    # Expert comptable associé (optionnel, pour affichage)
    expert_comptable: dict | None = None
    created_by_user: UserInfo | None = None
    annulee_par_user: UserInfo | None = None
    is_deleted: bool = False
    deleted_at: datetime | None = None
    deleted_by: UUID | None = None

    model_config = ConfigDict(from_attributes=True, json_encoders={Decimal: str})


class EncaissementWithPayments(EncaissementResponse):
    payment_history: list[PaymentHistoryResponse] = []


class EncaissementsListResponse(DecimalBaseModel):
    items: list[EncaissementResponse]
    total: int
    total_montant_facture: Decimal = Decimal("0")
    total_montant_paye: Decimal = Decimal("0")
