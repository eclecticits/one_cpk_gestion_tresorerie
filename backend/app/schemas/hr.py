from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import DecimalBaseModel


class HRBaseOut(DecimalBaseModel):
    model_config = ConfigDict(from_attributes=True, json_encoders={Decimal: str})


class HRServiceCreate(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    libelle: str = Field(min_length=2, max_length=150)
    is_active: bool = True


class HRServiceUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=30)
    libelle: str | None = Field(default=None, min_length=2, max_length=150)
    is_active: bool | None = None


class HRServiceOut(HRBaseOut):
    id: int
    code: str
    libelle: str
    is_active: bool


class HRFunctionCreate(BaseModel):
    libelle: str = Field(min_length=2, max_length=150)
    is_active: bool = True


class HRFunctionUpdate(BaseModel):
    libelle: str | None = Field(default=None, min_length=2, max_length=150)
    is_active: bool | None = None


class HRFunctionOut(HRBaseOut):
    id: int
    libelle: str
    is_active: bool


class HRReferenceCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    libelle: str = Field(min_length=2, max_length=150)
    description: str | None = None
    is_active: bool = True


class HRReferenceUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50)
    libelle: str | None = Field(default=None, min_length=2, max_length=150)
    description: str | None = None
    is_active: bool | None = None


class HRReferenceOut(HRBaseOut):
    id: int
    category: str
    code: str
    libelle: str
    description: str | None = None
    is_active: bool


class HREmployeeBase(BaseModel):
    matricule: str = Field(min_length=1, max_length=50)
    nom: str = Field(min_length=1, max_length=120)
    post_nom: str | None = None
    prenom: str | None = None
    sexe: str | None = None
    date_naissance: date | None = None
    lieu_naissance: str | None = None
    telephone: str | None = None
    email: str | None = None
    adresse: str | None = None
    service_id: int | None = None
    fonction_id: int | None = None
    statut: str = "actif"
    date_entree: date | None = None
    photo_url: str | None = None
    contact_urgence_nom: str | None = None
    contact_urgence_telephone: str | None = None


class HREmployeeCreate(HREmployeeBase):
    pass


class HREmployeeUpdate(BaseModel):
    matricule: str | None = Field(default=None, min_length=1, max_length=50)
    nom: str | None = Field(default=None, min_length=1, max_length=120)
    post_nom: str | None = None
    prenom: str | None = None
    sexe: str | None = None
    date_naissance: date | None = None
    lieu_naissance: str | None = None
    telephone: str | None = None
    email: str | None = None
    adresse: str | None = None
    service_id: int | None = None
    fonction_id: int | None = None
    statut: str | None = None
    date_entree: date | None = None
    date_sortie: date | None = None
    raison_sortie: str | None = None
    photo_url: str | None = None
    contact_urgence_nom: str | None = None
    contact_urgence_telephone: str | None = None


class HREmployeeOut(HRBaseOut):
    id: int
    matricule: str
    nom: str
    post_nom: str | None = None
    prenom: str | None = None
    sexe: str | None = None
    date_naissance: date | None = None
    lieu_naissance: str | None = None
    telephone: str | None = None
    email: str | None = None
    adresse: str | None = None
    service_id: int | None = None
    fonction_id: int | None = None
    service: HRServiceOut | None = None
    fonction: HRFunctionOut | None = None
    statut: str
    date_entree: date | None = None
    date_sortie: date | None = None
    raison_sortie: str | None = None
    photo_url: str | None = None
    contact_urgence_nom: str | None = None
    contact_urgence_telephone: str | None = None
    created_at: datetime


class HRContractCreate(BaseModel):
    employee_id: int
    type_contrat: str
    date_debut: date
    date_fin: date | None = None
    poste: str
    salaire_base: Decimal = Decimal("0")
    devise: str = "USD"
    statut: str = "actif"
    document_url: str | None = None


class HRContractUpdate(BaseModel):
    type_contrat: str | None = None
    date_debut: date | None = None
    date_fin: date | None = None
    poste: str | None = None
    salaire_base: Decimal | None = None
    devise: str | None = None
    statut: str | None = None
    document_url: str | None = None


class HRContractOut(HRBaseOut):
    id: int
    employee_id: int
    type_contrat: str
    date_debut: date
    date_fin: date | None = None
    poste: str
    salaire_base: Decimal | None = None
    devise: str
    statut: str
    document_url: str | None = None


class HRLeaveCreate(BaseModel):
    employee_id: int
    type_absence: str
    date_debut: date
    date_fin: date
    nombre_jours: Decimal
    motif: str | None = None
    justificatif_url: str | None = None
    statut: str = "brouillon"


class HRLeaveUpdate(BaseModel):
    type_absence: str | None = None
    date_debut: date | None = None
    date_fin: date | None = None
    nombre_jours: Decimal | None = None
    motif: str | None = None
    justificatif_url: str | None = None
    statut: str | None = None


class HRLeaveOut(HRBaseOut):
    id: int
    employee_id: int
    type_absence: str
    date_debut: date
    date_fin: date
    nombre_jours: Decimal
    motif: str | None = None
    justificatif_url: str | None = None
    statut: str
    validateur_id: UUID | None = None


class HRDocumentCreate(BaseModel):
    employee_id: int
    type_document: str
    titre: str
    fichier_url: str


class HRDocumentUpdate(BaseModel):
    type_document: str | None = None
    titre: str | None = None
    fichier_url: str | None = None


class HRDocumentOut(HRBaseOut):
    id: int
    employee_id: int
    type_document: str
    titre: str
    fichier_url: str
    date_upload: datetime
    uploaded_by: UUID | None = None


class HRDashboardOut(HRBaseOut):
    total_agents_actifs: int
    agents_en_conge: int
    contrats_expirant_bientot: int
    demandes_conge_en_attente: int
    masse_salariale_estimee: Decimal | None = None
    derniers_mouvements: list[dict]
    total_absences_mois: int = 0
    nb_bulletins_en_attente: int = 0
    taux_presence_mois: float | None = None


# ─── Leave Allocation schemas ─────────────────────────────────────────────────

class HRLeaveAllocationCreate(BaseModel):
    employee_id: int
    type_absence: str = Field(min_length=1, max_length=50)
    annee: int
    jours_alloues: Decimal
    report_annee_precedente: Decimal = Decimal("0")


class HRLeaveAllocationUpdate(BaseModel):
    jours_alloues: Decimal | None = None
    report_annee_precedente: Decimal | None = None


class HRLeaveAllocationOut(HRBaseOut):
    id: int
    employee_id: int
    type_absence: str
    annee: int
    jours_alloues: Decimal
    report_annee_precedente: Decimal
    created_at: datetime
    updated_at: datetime


class HRLeaveBalanceOut(HRBaseOut):
    employee_id: int
    type_absence: str
    annee: int
    jours_alloues: Decimal
    report_annee_precedente: Decimal
    jours_utilises: Decimal
    solde: Decimal


# ─── Attendance schemas ───────────────────────────────────────────────────────

class HRAttendanceCreate(BaseModel):
    employee_id: int
    date_presence: date
    statut_presence: str = Field(min_length=1, max_length=30)
    heure_arrivee: str | None = None
    heure_depart: str | None = None
    note: str | None = None


class HRAttendanceUpdate(BaseModel):
    statut_presence: str | None = None
    heure_arrivee: str | None = None
    heure_depart: str | None = None
    note: str | None = None


class HRAttendanceOut(HRBaseOut):
    id: int
    employee_id: int
    date_presence: date
    statut_presence: str
    heure_arrivee: str | None = None
    heure_depart: str | None = None
    note: str | None = None
    created_at: datetime


class HRAttendanceBatchCreate(BaseModel):
    employee_ids: list[int]
    date: date
    statut: str


class HRAttendanceSummaryOut(BaseModel):
    mois: int
    annee: int
    total_jours_saisis: int
    presents: int
    absents: int
    demi_journees: int
    conges: int
    teletravail: int
    taux_presence: float | None = None


# ─── Payroll schemas ──────────────────────────────────────────────────────────

class HRPayrollEntryCreate(BaseModel):
    mois: int = Field(ge=1, le=12)
    annee: int
    note: str | None = None


class HRPayrollEntryOut(HRBaseOut):
    id: int
    mois: int
    annee: int
    statut: str
    note: str | None = None
    nb_bulletins: int
    created_at: datetime
    updated_at: datetime


class HRSalarySlipOut(HRBaseOut):
    id: int
    payroll_entry_id: int
    employee_id: int
    salaire_base: Decimal
    total_primes: Decimal
    total_retenues: Decimal
    net_a_payer: Decimal
    devise: str
    jours_travailles: int | None = None
    jours_absences: int | None = None
    statut: str
    pdf_url: str | None = None
    created_at: datetime


# ─── Evaluation schemas ───────────────────────────────────────────────────────

class HREvaluationCreate(BaseModel):
    employee_id: int
    annee: int
    periode: str = Field(default="annuelle", max_length=20)
    note_globale: Decimal | None = Field(default=None, ge=0, le=20)
    appreciation: str | None = Field(default=None, max_length=50)
    objectifs_atteints: str | None = None
    axes_amelioration: str | None = None
    commentaire: str | None = None
    statut: str = "brouillon"


class HREvaluationUpdate(BaseModel):
    note_globale: Decimal | None = Field(default=None, ge=0, le=20)
    appreciation: str | None = None
    objectifs_atteints: str | None = None
    axes_amelioration: str | None = None
    commentaire: str | None = None
    statut: str | None = None


class HREvaluationOut(HRBaseOut):
    id: int
    employee_id: int
    annee: int
    periode: str
    note_globale: Decimal | None = None
    appreciation: str | None = None
    objectifs_atteints: str | None = None
    axes_amelioration: str | None = None
    commentaire: str | None = None
    statut: str
    created_at: datetime
    updated_at: datetime


# ─── Sanction schemas ─────────────────────────────────────────────────────────

class HRSanctionCreate(BaseModel):
    employee_id: int
    type_sanction: str = Field(max_length=50)
    date_sanction: date
    motif: str = Field(max_length=255)
    description: str | None = None
    duree_jours: int | None = Field(default=None, ge=1)
    statut: str = "actif"


class HRSanctionUpdate(BaseModel):
    type_sanction: str | None = None
    motif: str | None = None
    description: str | None = None
    duree_jours: int | None = None
    statut: str | None = None


class HRSanctionOut(HRBaseOut):
    id: int
    employee_id: int
    type_sanction: str
    date_sanction: date
    motif: str
    description: str | None = None
    duree_jours: int | None = None
    statut: str
    created_at: datetime
    updated_at: datetime


# ─── Report schemas ───────────────────────────────────────────────────────────

class HRReportEffectifService(BaseModel):
    service: str
    total: int
    actifs: int
    en_conge: int

class HRReportPresence(BaseModel):
    mois: int
    annee: int
    presents: int
    absents: int
    demi_journees: int
    conges: int
    taux_presence: float | None

class HRReportMasseSalariale(BaseModel):
    mois: int
    annee: int
    total_net: Decimal
    nb_bulletins: int
    devise: str

class HRReportConge(BaseModel):
    type_absence: str
    total_demandes: int
    total_jours: Decimal
    approuves: int
    en_attente: int

class HRReportOut(HRBaseOut):
    effectifs_par_service: list[HRReportEffectifService]
    presences: list[HRReportPresence]
    masse_salariale: list[HRReportMasseSalariale]
    conges_par_type: list[HRReportConge]
