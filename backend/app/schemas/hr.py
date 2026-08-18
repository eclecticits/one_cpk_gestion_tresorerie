from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.base import DecimalBaseModel


class HRBaseOut(DecimalBaseModel):
    model_config = ConfigDict(from_attributes=True, json_encoders={Decimal: str})


class HRServiceRefOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    libelle: str


class HREmployeeRefOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    matricule: str
    nom: str
    post_nom: str | None = None
    prenom: str | None = None


class HRServiceCreate(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    libelle: str = Field(min_length=2, max_length=150)
    description: str | None = None
    responsable_id: int | None = None
    parent_id: int | None = None
    is_active: bool = True


class HRServiceUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=30)
    libelle: str | None = Field(default=None, min_length=2, max_length=150)
    description: str | None = None
    responsable_id: int | None = None
    parent_id: int | None = None
    is_active: bool | None = None


class HRServiceOut(HRBaseOut):
    id: int
    code: str
    libelle: str
    description: str | None = None
    responsable_id: int | None = None
    parent_id: int | None = None
    is_active: bool


class HRServiceDetailOut(HRServiceOut):
    responsable: HREmployeeRefOut | None = None
    parent: HRServiceRefOut | None = None
    employees_count: int = 0


class HRFunctionCreate(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    libelle: str = Field(min_length=2, max_length=150)
    description: str | None = None
    niveau_hierarchique: str | None = None
    is_active: bool = True


class HRFunctionUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=30)
    libelle: str | None = Field(default=None, min_length=2, max_length=150)
    description: str | None = None
    niveau_hierarchique: str | None = None
    is_active: bool | None = None


class HRFunctionOut(HRBaseOut):
    id: int
    code: str
    libelle: str
    description: str | None = None
    niveau_hierarchique: str | None = None
    is_active: bool


class HRFunctionDetailOut(HRFunctionOut):
    employees_count: int = 0


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
    source: str = Field(default="MANUAL", max_length=30)
    note: str | None = None


class HRAttendanceUpdate(BaseModel):
    statut_presence: str | None = None
    heure_arrivee: str | None = None
    heure_depart: str | None = None
    source: str | None = Field(default=None, max_length=30)
    note: str | None = None


class HRAttendanceOut(HRBaseOut):
    id: int
    employee_id: int
    date_presence: date
    statut_presence: str
    heure_arrivee: str | None = None
    heure_depart: str | None = None
    source: str = "MANUAL"
    note: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


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


class HRAttendancePunchCreate(BaseModel):
    employee_id: int
    punched_at: datetime
    event_type: str = Field(pattern="^(IN|OUT|in|out)$")
    source: str = Field(default="MANUAL", max_length=30)
    device_id: str | None = Field(default=None, max_length=100)
    external_reference: str | None = Field(default=None, max_length=150)
    notes: str | None = None


class HRAttendancePunchOut(HRBaseOut):
    id: int
    employee_id: int
    punched_at: datetime
    event_type: str
    source: str
    device_id: str | None = None
    external_reference: str | None = None
    notes: str | None = None
    created_at: datetime


class HRAttendancePunchJournalItem(HRAttendancePunchOut):
    employee_matricule: str | None = None
    employee_name: str
    service_id: int | None = None
    service_name: str | None = None


class HRAttendancePunchJournalOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[HRAttendancePunchJournalItem]


class HRAttendanceDayPunchOut(BaseModel):
    id: int
    punched_at: datetime
    time: str
    event_type: str
    source: str
    device_id: str | None = None
    external_reference: str | None = None
    notes: str | None = None


class HRAttendanceDailySummaryOut(BaseModel):
    employee_id: int
    employee_matricule: str | None = None
    employee_name: str
    service_id: int | None = None
    service_name: str | None = None
    date: date
    is_working_day: bool
    status: str
    has_late: bool
    has_anomaly: bool
    first_in_time: str | None = None
    last_out_time: str | None = None
    worked_minutes: int
    worked_duration: str | None = None
    pause_minutes: int
    pause_duration: str | None = None
    late_minutes: int
    late_duration: str | None = None
    overtime_minutes: int
    overtime_duration: str | None = None
    anomalies: list[str] = Field(default_factory=list)
    punches: list[HRAttendanceDayPunchOut] = Field(default_factory=list)
    manual_attendance_id: int | None = None
    leave_id: int | None = None


class HRAttendanceEmployeeMonthlyOut(BaseModel):
    employee_id: int
    employee_matricule: str | None = None
    employee_name: str
    service_id: int | None = None
    service_name: str | None = None
    working_days: int
    present_days: int
    absent_days: int
    half_days: int
    leave_days: int
    remote_days: int
    late_count: int
    anomaly_count: int
    worked_minutes: int
    overtime_minutes: int
    days: list[HRAttendanceDailySummaryOut]


class HRAttendanceMonthlyOut(BaseModel):
    mois: int
    annee: int
    days_in_month: int
    generated_at: datetime
    totals: dict[str, int]
    employees: list[HRAttendanceEmployeeMonthlyOut]


class HRAttendanceAgentDeviceHeartbeat(BaseModel):
    device_id: str = Field(max_length=100)
    provider: str | None = Field(default=None, max_length=50)
    status: str = Field(default="UNKNOWN", max_length=30)
    last_sync_at: datetime | None = None
    pending_count: int = 0
    error_count: int = 0
    last_error: str | None = None
    model: str | None = Field(default=None, max_length=120)
    firmware: str | None = Field(default=None, max_length=120)
    serial_number: str | None = Field(default=None, max_length=120)


class HRAttendanceAgentHeartbeatIn(BaseModel):
    agent_version: str | None = Field(default=None, max_length=50)
    hostname: str | None = Field(default=None, max_length=150)
    site: str | None = Field(default=None, max_length=100)
    timestamp: datetime
    pending_queue_count: int = 0
    error_count: int = 0
    last_sync_at: datetime | None = None
    devices: list[HRAttendanceAgentDeviceHeartbeat] = Field(default_factory=list)


class HRAttendanceAgentEventIn(BaseModel):
    external_employee_id: str = Field(max_length=100)
    punched_at: datetime
    event_type: str | None = Field(default=None, max_length=10)
    source: str = Field(default="DEVICE", max_length=30)
    external_reference: str = Field(max_length=150)
    raw_event_type: str | None = Field(default=None, max_length=100)
    payload: dict | None = None


class HRAttendanceAgentPunchBatchIn(BaseModel):
    agent_id: str = Field(max_length=100)
    device_id: str = Field(max_length=100)
    events: list[HRAttendanceAgentEventIn] = Field(min_length=1, max_length=500)


class HRAttendanceAgentEventResult(BaseModel):
    external_reference: str
    status: str
    punch_id: int | None = None
    unmapped_id: int | None = None
    detail: str | None = None


class HRAttendanceAgentPunchBatchOut(BaseModel):
    accepted: int
    duplicates: int
    unmapped: int
    rejected: int
    results: list[HRAttendanceAgentEventResult]


class HRAttendanceAgentEnrollmentCreate(BaseModel):
    agent_name: str = Field(max_length=150)
    site: str | None = Field(default=None, max_length=100)
    api_base_url: str = Field(max_length=255)
    device_code: str = Field(max_length=100)
    device_name: str = Field(max_length=150)
    provider: str = Field(default="hikvision", max_length=50)
    model: str | None = Field(default="DS-K1A8603MF-B", max_length=120)
    local_host: str = Field(max_length=100)
    local_port: int = Field(default=80, ge=1, le=65535)
    expires_in_minutes: int = Field(default=60, ge=5, le=1440)
    agent_id: int | None = None


class HRAttendanceAgentEnrollmentOut(HRBaseOut):
    id: int
    agent_id: str
    agent_name: str
    enrollment_token: str
    enrollment_url: str
    api_base_url: str
    device_code: str
    device_name: str
    provider: str
    local_host: str
    local_port: int
    expires_at: datetime


class HRAttendanceAgentReleaseCreate(BaseModel):
    version: str = Field(max_length=50)
    platform: str = Field(pattern="^(windows|linux)$")
    architecture: str = Field(default="x64", pattern="^x64$")
    filename: str = Field(max_length=255)
    storage_key: str = Field(max_length=500)
    is_active: bool = True
    minimum_backend_version: str | None = Field(default=None, max_length=50)


class HRAttendanceAgentReleaseOut(HRBaseOut):
    id: int
    version: str
    platform: str
    architecture: str
    filename: str
    storage_key: str
    sha256: str
    file_size: int
    published_at: datetime
    is_active: bool
    minimum_backend_version: str | None = None


class HRAttendanceAgentPackageCreate(BaseModel):
    agent_id: int
    platform: str = Field(pattern="^(windows|linux)$")
    architecture: str = Field(default="x64", pattern="^x64$")
    api_base_url: str = Field(max_length=255)
    expires_in_minutes: int = Field(default=60, ge=5, le=1440)


class HRAttendanceAgentEnrollIn(BaseModel):
    enrollment_token: str = Field(min_length=20)
    hostname: str | None = Field(default=None, max_length=150)
    agent_version: str | None = Field(default=None, max_length=50)


class HRAttendanceAgentDeviceConfigOut(BaseModel):
    id: str
    provider: str
    host: str
    port: int
    configured_model: str | None = None


class HRAttendanceAgentEnrollOut(BaseModel):
    agent_id: str
    agent_token: str
    api_base_url: str
    site: str | None = None
    devices: list[HRAttendanceAgentDeviceConfigOut]


class HRAttendanceAgentOut(HRBaseOut):
    id: int
    agent_id: str
    name: str
    site: str | None = None
    is_active: bool
    version: str | None = None
    hostname: str | None = None
    last_seen_at: datetime | None = None
    last_sync_at: datetime | None = None
    revoked_at: datetime | None = None


class HRAttendanceAgentReinstallOut(BaseModel):
    agent: HRAttendanceAgentOut
    enrollment: HRAttendanceAgentEnrollmentOut


class HRAttendanceAgentCommandCreate(BaseModel):
    device_id: int
    command_type: str = Field(default="TEST_DEVICE", pattern="^(TEST_DEVICE|PROBE_DEVICE)$")
    expires_in_seconds: int = Field(default=120, ge=10, le=3600)


class HRAttendanceAgentCommandOut(HRBaseOut):
    id: int
    tenant_id: int
    agent_id: int
    device_id: int | None = None
    command_type: str
    payload_json: dict | None = None
    status: str
    created_at: datetime
    expires_at: datetime | None = None
    claimed_at: datetime | None = None
    completed_at: datetime | None = None
    result_json: dict | None = None
    error: str | None = None


class HRAttendanceAgentCommandResultIn(BaseModel):
    status: str = Field(pattern="^(SUCCESS|FAILED)$")
    result: dict | None = None
    error: str | None = None


class HRAttendanceDeviceOut(HRBaseOut):
    id: int
    code: str
    name: str
    provider: str
    site: str | None = None
    local_host: str | None = None
    local_port: int | None = None
    serial_number: str | None = None
    model: str | None = None
    firmware: str | None = None
    status: str
    is_active: bool
    last_seen_at: datetime | None = None
    last_sync_at: datetime | None = None
    last_test_at: datetime | None = None
    last_test_latency_ms: int | None = None
    last_test_result_json: dict | None = None
    last_error: str | None = None
    pending_count: int
    error_count: int
    today_punch_count: int


class HRAttendanceDeviceStatusOut(BaseModel):
    id: int
    agent_id: int | None = None
    device_id: str
    name: str
    provider: str
    site: str | None = None
    device_online: bool
    agent_online: bool
    status: str
    last_seen_at: datetime | None = None
    last_sync_at: datetime | None = None
    last_test_at: datetime | None = None
    last_test_latency_ms: int | None = None
    last_test_result: dict | None = None
    pending_count: int
    error_count: int
    today_punch_count: int
    last_error: str | None = None


class HRAttendanceMappingCreate(BaseModel):
    device_id: int
    employee_id: int
    external_employee_id: str = Field(max_length=100)


class HRAttendanceMappingOut(HRBaseOut):
    id: int
    device_id: int
    employee_id: int
    external_employee_id: str
    created_at: datetime
    updated_at: datetime


class HRAttendanceUnmappedPunchOut(HRBaseOut):
    id: int
    device_id: int
    external_employee_id: str
    punched_at: datetime
    event_type: str | None = None
    source: str
    external_reference: str
    raw_event_type: str | None = None
    status: str
    created_at: datetime
    resolved_at: datetime | None = None


# ─── Payroll schemas ──────────────────────────────────────────────────────────

class HRIprBracket(BaseModel):
    lower: Decimal = Field(ge=0)
    upper: Decimal | None = Field(default=None, ge=0)
    rate: Decimal = Field(ge=0, le=1)


class HRPayrollSettingsUpdate(BaseModel):
    devise_bareme: str = Field(min_length=3, max_length=3)
    ipr_brackets: list[HRIprBracket] = Field(min_length=1)
    ipr_plancher: Decimal = Field(ge=0)
    ipr_plafond_taux: Decimal = Field(ge=0, le=1)
    cnss_taux_salarie: Decimal = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _validate_brackets_contiguous(self) -> "HRPayrollSettingsUpdate":
        brackets = sorted(self.ipr_brackets, key=lambda b: b.lower)
        if brackets[0].lower != 0:
            raise ValueError("La première tranche doit commencer à 0.")
        for i, bracket in enumerate(brackets):
            is_last = i == len(brackets) - 1
            if is_last:
                if bracket.upper is not None:
                    raise ValueError("Seule la dernière tranche peut avoir une borne haute indéfinie (upper=null).")
            else:
                if bracket.upper is None:
                    raise ValueError("Seule la dernière tranche peut avoir une borne haute indéfinie (upper=null).")
                if bracket.upper <= bracket.lower:
                    raise ValueError("La borne haute d'une tranche doit être supérieure à sa borne basse.")
                if bracket.upper != brackets[i + 1].lower:
                    raise ValueError("Les tranches doivent être contiguës (pas de trou ni de chevauchement).")
        self.ipr_brackets[:] = brackets
        return self


class HRPayrollSettingsOut(BaseModel):
    devise_bareme: str
    ipr_brackets: list[HRIprBracket]
    ipr_plancher: Decimal
    ipr_plafond_taux: Decimal
    cnss_taux_salarie: Decimal
    is_default: bool
    updated_at: datetime | None = None


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
    ipr: Decimal
    cnss_salarie: Decimal
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
