from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import uuid

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HRService(Base):
    __tablename__ = "hr_services"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_hr_services_tenant_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    libelle: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    responsable_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("hr_employees.id", ondelete="SET NULL"), nullable=True, index=True)
    parent_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("hr_services.id", ondelete="SET NULL"), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    employees = relationship("HREmployee", back_populates="service", foreign_keys="[HREmployee.service_id]")
    responsable = relationship("HREmployee", foreign_keys=[responsable_id])
    parent: Mapped["HRService | None"] = relationship("HRService", remote_side="HRService.id", back_populates="children")
    children: Mapped[list["HRService"]] = relationship("HRService", back_populates="parent")


class HRFunction(Base):
    __tablename__ = "hr_functions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "libelle", name="uq_hr_functions_tenant_libelle"),
        UniqueConstraint("tenant_id", "code", name="uq_hr_functions_tenant_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    libelle: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    niveau_hierarchique: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    employees = relationship("HREmployee", back_populates="fonction")


class HRReference(Base):
    __tablename__ = "hr_references"
    __table_args__ = (UniqueConstraint("tenant_id", "category", "code", name="uq_hr_references_tenant_category_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    libelle: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class HREmployee(Base):
    __tablename__ = "hr_employees"
    __table_args__ = (UniqueConstraint("tenant_id", "matricule", name="uq_hr_employees_tenant_matricule"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    matricule: Mapped[str] = mapped_column(String(50), nullable=False)
    nom: Mapped[str] = mapped_column(String(120), nullable=False)
    post_nom: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prenom: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sexe: Mapped[str | None] = mapped_column(String(20), nullable=True)
    date_naissance: Mapped[date | None] = mapped_column(Date, nullable=True)
    lieu_naissance: Mapped[str | None] = mapped_column(String(150), nullable=True)
    telephone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    adresse: Mapped[str | None] = mapped_column(Text, nullable=True)
    service_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("hr_services.id", ondelete="SET NULL"), nullable=True, index=True)
    fonction_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("hr_functions.id", ondelete="SET NULL"), nullable=True, index=True)
    statut: Mapped[str] = mapped_column(String(30), nullable=False, default="actif")
    date_entree: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_sortie: Mapped[date | None] = mapped_column(Date, nullable=True)
    raison_sortie: Mapped[str | None] = mapped_column(String(100), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_urgence_nom: Mapped[str | None] = mapped_column(String(150), nullable=True)
    contact_urgence_telephone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    service = relationship("HRService", back_populates="employees", foreign_keys=[service_id])
    fonction = relationship("HRFunction", back_populates="employees")
    contracts = relationship("HRContract", back_populates="employee", cascade="all, delete-orphan")
    leaves = relationship("HRLeave", back_populates="employee", cascade="all, delete-orphan")
    documents = relationship("HRDocument", back_populates="employee", cascade="all, delete-orphan")
    leave_allocations = relationship("HRLeaveAllocation", back_populates="employee", cascade="all, delete-orphan")
    attendances = relationship("HRAttendance", back_populates="employee", cascade="all, delete-orphan")
    attendance_punches = relationship("HRAttendancePunch", back_populates="employee", cascade="all, delete-orphan")
    salary_slips = relationship("HRSalarySlip", back_populates="employee", cascade="all, delete-orphan")
    evaluations = relationship("HREvaluation", back_populates="employee", cascade="all, delete-orphan")
    sanctions = relationship("HRSanction", back_populates="employee", cascade="all, delete-orphan")


class HRContract(Base):
    __tablename__ = "hr_contracts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    employee_id: Mapped[int] = mapped_column(Integer, ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False, index=True)
    type_contrat: Mapped[str] = mapped_column(String(30), nullable=False)
    date_debut: Mapped[date] = mapped_column(Date, nullable=False)
    date_fin: Mapped[date | None] = mapped_column(Date, nullable=True)
    poste: Mapped[str] = mapped_column(String(150), nullable=False)
    salaire_base: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    devise: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    statut: Mapped[str] = mapped_column(String(30), nullable=False, default="actif")
    document_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    employee = relationship("HREmployee", back_populates="contracts")


class HRLeave(Base):
    __tablename__ = "hr_leaves"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    employee_id: Mapped[int] = mapped_column(Integer, ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False, index=True)
    type_absence: Mapped[str] = mapped_column(String(50), nullable=False)
    date_debut: Mapped[date] = mapped_column(Date, nullable=False)
    date_fin: Mapped[date] = mapped_column(Date, nullable=False)
    nombre_jours: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    motif: Mapped[str | None] = mapped_column(Text, nullable=True)
    justificatif_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    statut: Mapped[str] = mapped_column(String(30), nullable=False, default="brouillon")
    validateur_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    employee = relationship("HREmployee", back_populates="leaves")


class HRDocument(Base):
    __tablename__ = "hr_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    employee_id: Mapped[int] = mapped_column(Integer, ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False, index=True)
    type_document: Mapped[str] = mapped_column(String(50), nullable=False)
    titre: Mapped[str] = mapped_column(String(180), nullable=False)
    fichier_url: Mapped[str] = mapped_column(Text, nullable=False)
    date_upload: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    employee = relationship("HREmployee", back_populates="documents")


class HRLeaveAllocation(Base):
    __tablename__ = "hr_leave_allocations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "employee_id", "type_absence", "annee", name="uq_hr_leave_alloc_tenant_emp_type_year"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    employee_id: Mapped[int] = mapped_column(Integer, ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False, index=True)
    type_absence: Mapped[str] = mapped_column(String(50), nullable=False)
    annee: Mapped[int] = mapped_column(Integer, nullable=False)
    jours_alloues: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    report_annee_precedente: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    employee = relationship("HREmployee", back_populates="leave_allocations")


class HRAttendance(Base):
    __tablename__ = "hr_attendances"
    __table_args__ = (
        UniqueConstraint("tenant_id", "employee_id", "date_presence", name="uq_hr_attendances_tenant_emp_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    employee_id: Mapped[int] = mapped_column(Integer, ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False, index=True)
    date_presence: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    statut_presence: Mapped[str] = mapped_column(String(30), nullable=False)
    heure_arrivee: Mapped[str | None] = mapped_column(String(10), nullable=True)
    heure_depart: Mapped[str | None] = mapped_column(String(10), nullable=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="MANUAL")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    saisi_par: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    employee = relationship("HREmployee", back_populates="attendances")


class HRAttendancePunch(Base):
    __tablename__ = "hr_attendance_punches"
    __table_args__ = (
        Index("ix_hr_punch_tenant_employee_time", "tenant_id", "employee_id", "punched_at"),
        Index("ix_hr_punch_tenant_time", "tenant_id", "punched_at"),
        Index("ix_hr_punch_tenant_source", "tenant_id", "source"),
        UniqueConstraint("tenant_id", "device_id", "external_reference", name="uq_hr_punch_tenant_device_external_ref"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    employee_id: Mapped[int] = mapped_column(Integer, ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False, index=True)
    punched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(10), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="MANUAL")
    device_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    external_reference: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    employee = relationship("HREmployee", back_populates="attendance_punches")


class HRAttendanceAgent(Base):
    __tablename__ = "hr_attendance_agents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "agent_id", name="uq_hr_attendance_agents_tenant_agent"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    site: Mapped[str | None] = mapped_column(String(100), nullable=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    hostname: Mapped[str | None] = mapped_column(String(150), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pending_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    devices = relationship("HRAttendanceDevice", back_populates="agent")
    enrollments = relationship("HRAttendanceAgentEnrollment", back_populates="agent", cascade="all, delete-orphan")


class HRAttendanceAgentEnrollment(Base):
    __tablename__ = "hr_attendance_agent_enrollments"
    __table_args__ = (
        Index("ix_hr_agent_enrollment_tenant_status", "tenant_id", "status"),
        UniqueConstraint("token_hash", name="uq_hr_agent_enrollment_token_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    agent_id: Mapped[int] = mapped_column(Integer, ForeignKey("hr_attendance_agents.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    api_base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    device_code: Mapped[str] = mapped_column(String(100), nullable=False)
    device_name: Mapped[str] = mapped_column(String(150), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="hikvision")
    site: Mapped[str | None] = mapped_column(String(100), nullable=True)
    local_host: Mapped[str] = mapped_column(String(100), nullable=False)
    local_port: Mapped[int] = mapped_column(Integer, nullable=False, default=80)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    agent = relationship("HRAttendanceAgent", back_populates="enrollments")


class HRAttendanceDevice(Base):
    __tablename__ = "hr_attendance_devices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_hr_attendance_devices_tenant_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    agent_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("hr_attendance_agents.id", ondelete="SET NULL"), nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    site: Mapped[str | None] = mapped_column(String(100), nullable=True)
    local_host: Mapped[str | None] = mapped_column(String(100), nullable=True)
    local_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    firmware: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="UNKNOWN")
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_test_result_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    pending_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    today_punch_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    agent = relationship("HRAttendanceAgent", back_populates="devices")
    mappings = relationship("HRAttendanceDeviceEmployeeMapping", back_populates="device", cascade="all, delete-orphan")


class HRAttendanceDeviceEmployeeMapping(Base):
    __tablename__ = "hr_attendance_device_employee_mappings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "device_id", "external_employee_id", name="uq_hr_attendance_mapping_device_external_employee"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    device_id: Mapped[int] = mapped_column(Integer, ForeignKey("hr_attendance_devices.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id: Mapped[int] = mapped_column(Integer, ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False, index=True)
    external_employee_id: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    device = relationship("HRAttendanceDevice", back_populates="mappings")
    employee = relationship("HREmployee")


class HRAttendanceUnmappedPunch(Base):
    __tablename__ = "hr_attendance_unmapped_punches"
    __table_args__ = (
        UniqueConstraint("tenant_id", "device_id", "external_reference", name="uq_hr_unmapped_punch_device_external_ref"),
        Index("ix_hr_unmapped_punch_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    device_id: Mapped[int] = mapped_column(Integer, ForeignKey("hr_attendance_devices.id", ondelete="CASCADE"), nullable=False, index=True)
    external_employee_id: Mapped[str] = mapped_column(String(100), nullable=False)
    punched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    event_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="DEVICE")
    external_reference: Mapped[str] = mapped_column(String(150), nullable=False)
    raw_event_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="UNMAPPED_EMPLOYEE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class HRAttendanceAgentRelease(Base):
    __tablename__ = "hr_attendance_agent_releases"
    __table_args__ = (
        UniqueConstraint("version", "platform", "architecture", name="uq_hr_agent_release_version_platform_arch"),
        Index("ix_hr_agent_release_active_platform", "is_active", "platform", "architecture"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    platform: Mapped[str] = mapped_column(String(30), nullable=False)
    architecture: Mapped[str] = mapped_column(String(30), nullable=False, default="x64")
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    minimum_backend_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class HRAttendanceAgentCommand(Base):
    __tablename__ = "hr_attendance_agent_commands"
    __table_args__ = (
        Index("ix_hr_agent_command_tenant_status", "tenant_id", "status"),
        Index("ix_hr_agent_command_agent_status", "agent_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    agent_id: Mapped[int] = mapped_column(Integer, ForeignKey("hr_attendance_agents.id", ondelete="CASCADE"), nullable=False, index=True)
    device_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("hr_attendance_devices.id", ondelete="SET NULL"), nullable=True, index=True)
    command_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class HRPayrollSettings(Base):
    __tablename__ = "hr_payroll_settings"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_hr_payroll_settings_tenant"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    devise_bareme: Mapped[str] = mapped_column(String(3), nullable=False, default="CDF")
    ipr_brackets: Mapped[list] = mapped_column(JSONB, nullable=False)
    ipr_plancher: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    ipr_plafond_taux: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    cnss_taux_salarie: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class HRPayrollEntry(Base):
    __tablename__ = "hr_payroll_entries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "mois", "annee", name="uq_hr_payroll_entries_tenant_mois_annee"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    mois: Mapped[int] = mapped_column(Integer, nullable=False)
    annee: Mapped[int] = mapped_column(Integer, nullable=False)
    statut: Mapped[str] = mapped_column(String(30), nullable=False, default="brouillon")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    nb_bulletins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    salary_slips = relationship("HRSalarySlip", back_populates="payroll_entry", cascade="all, delete-orphan")


class HRSalarySlip(Base):
    __tablename__ = "hr_salary_slips"
    __table_args__ = (
        UniqueConstraint("payroll_entry_id", "employee_id", name="uq_hr_salary_slips_entry_employee"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    payroll_entry_id: Mapped[int] = mapped_column(Integer, ForeignKey("hr_payroll_entries.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id: Mapped[int] = mapped_column(Integer, ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False, index=True)
    salaire_base: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total_primes: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0"))
    ipr: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0"))
    cnss_salarie: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0"))
    total_retenues: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0"))
    net_a_payer: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    devise: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    jours_travailles: Mapped[int | None] = mapped_column(Integer, nullable=True)
    jours_absences: Mapped[int | None] = mapped_column(Integer, nullable=True)
    statut: Mapped[str] = mapped_column(String(30), nullable=False, default="brouillon")
    pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    payroll_entry = relationship("HRPayrollEntry", back_populates="salary_slips")
    employee = relationship("HREmployee", back_populates="salary_slips")


class HREvaluation(Base):
    __tablename__ = "hr_evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    employee_id: Mapped[int] = mapped_column(Integer, ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False, index=True)
    annee: Mapped[int] = mapped_column(Integer, nullable=False)
    periode: Mapped[str] = mapped_column(String(20), nullable=False, default="annuelle")
    note_globale: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)
    appreciation: Mapped[str | None] = mapped_column(String(50), nullable=True)
    objectifs_atteints: Mapped[str | None] = mapped_column(Text, nullable=True)
    axes_amelioration: Mapped[str | None] = mapped_column(Text, nullable=True)
    commentaire: Mapped[str | None] = mapped_column(Text, nullable=True)
    statut: Mapped[str] = mapped_column(String(30), nullable=False, default="brouillon")
    evaluateur_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    employee = relationship("HREmployee", back_populates="evaluations")


class HRSanction(Base):
    __tablename__ = "hr_sanctions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True)
    employee_id: Mapped[int] = mapped_column(Integer, ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False, index=True)
    type_sanction: Mapped[str] = mapped_column(String(50), nullable=False)
    date_sanction: Mapped[date] = mapped_column(Date, nullable=False)
    motif: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    duree_jours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    statut: Mapped[str] = mapped_column(String(30), nullable=False, default="actif")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    employee = relationship("HREmployee", back_populates="sanctions")
