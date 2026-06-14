"""add hr mvp module

Revision ID: 20260528_hr_mvp
Revises: 20260510_req_bank
Create Date: 2026-05-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260528_hr_mvp"
down_revision = "20260510_req_bank"
branch_labels = None
depends_on = None


HR_PERMISSIONS = [
    ("rh.dashboard.view", "RH - consulter le tableau de bord"),
    ("rh.employees.view", "RH - consulter le personnel"),
    ("rh.employees.create", "RH - créer des agents"),
    ("rh.employees.update", "RH - modifier des agents"),
    ("rh.employees.archive", "RH - archiver des agents"),
    ("rh.contracts.view", "RH - consulter les contrats"),
    ("rh.contracts.manage", "RH - gérer les contrats"),
    ("rh.attendance.view", "RH - consulter les présences"),
    ("rh.attendance.manage", "RH - gérer les présences"),
    ("rh.leave.view", "RH - consulter les congés"),
    ("rh.leave.request", "RH - demander un congé"),
    ("rh.leave.approve", "RH - approuver les congés"),
    ("rh.payroll.view", "RH - consulter la paie"),
    ("rh.payroll.prepare", "RH - préparer la paie"),
    ("rh.payroll.validate", "RH - valider la paie"),
    ("rh.payslips.view", "RH - consulter les bulletins"),
    ("rh.payslips.generate", "RH - générer les bulletins"),
    ("rh.documents.view", "RH - consulter les documents"),
    ("rh.documents.manage", "RH - gérer les documents"),
    ("rh.evaluations.view", "RH - consulter les évaluations"),
    ("rh.evaluations.manage", "RH - gérer les évaluations"),
    ("rh.sanctions.view", "RH - consulter les sanctions"),
    ("rh.sanctions.manage", "RH - gérer les sanctions"),
    ("rh.reports.view", "RH - consulter les rapports"),
    ("rh.settings.manage", "RH - gérer les paramètres"),
    ("rh.salaries.view", "RH - consulter les salaires"),
]


def upgrade() -> None:
    op.create_table(
        "hr_services",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("libelle", sa.String(length=150), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_hr_services_tenant_code"),
    )
    op.create_index(op.f("ix_hr_services_tenant_id"), "hr_services", ["tenant_id"], unique=False)

    op.create_table(
        "hr_functions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("libelle", sa.String(length=150), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "libelle", name="uq_hr_functions_tenant_libelle"),
    )
    op.create_index(op.f("ix_hr_functions_tenant_id"), "hr_functions", ["tenant_id"], unique=False)

    op.create_table(
        "hr_employees",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("matricule", sa.String(length=50), nullable=False),
        sa.Column("nom", sa.String(length=120), nullable=False),
        sa.Column("post_nom", sa.String(length=120), nullable=True),
        sa.Column("prenom", sa.String(length=120), nullable=True),
        sa.Column("sexe", sa.String(length=20), nullable=True),
        sa.Column("date_naissance", sa.Date(), nullable=True),
        sa.Column("lieu_naissance", sa.String(length=150), nullable=True),
        sa.Column("telephone", sa.String(length=50), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("adresse", sa.Text(), nullable=True),
        sa.Column("service_id", sa.Integer(), nullable=True),
        sa.Column("fonction_id", sa.Integer(), nullable=True),
        sa.Column("statut", sa.String(length=30), nullable=False),
        sa.Column("date_entree", sa.Date(), nullable=True),
        sa.Column("photo_url", sa.Text(), nullable=True),
        sa.Column("contact_urgence_nom", sa.String(length=150), nullable=True),
        sa.Column("contact_urgence_telephone", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["fonction_id"], ["hr_functions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["service_id"], ["hr_services.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "matricule", name="uq_hr_employees_tenant_matricule"),
    )
    op.create_index(op.f("ix_hr_employees_fonction_id"), "hr_employees", ["fonction_id"], unique=False)
    op.create_index(op.f("ix_hr_employees_service_id"), "hr_employees", ["service_id"], unique=False)
    op.create_index(op.f("ix_hr_employees_tenant_id"), "hr_employees", ["tenant_id"], unique=False)

    op.create_table(
        "hr_contracts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("type_contrat", sa.String(length=30), nullable=False),
        sa.Column("date_debut", sa.Date(), nullable=False),
        sa.Column("date_fin", sa.Date(), nullable=True),
        sa.Column("poste", sa.String(length=150), nullable=False),
        sa.Column("salaire_base", sa.Numeric(14, 2), nullable=False),
        sa.Column("devise", sa.String(length=3), nullable=False),
        sa.Column("statut", sa.String(length=30), nullable=False),
        sa.Column("document_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_hr_contracts_employee_id"), "hr_contracts", ["employee_id"], unique=False)
    op.create_index(op.f("ix_hr_contracts_tenant_id"), "hr_contracts", ["tenant_id"], unique=False)

    op.create_table(
        "hr_leaves",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("type_absence", sa.String(length=50), nullable=False),
        sa.Column("date_debut", sa.Date(), nullable=False),
        sa.Column("date_fin", sa.Date(), nullable=False),
        sa.Column("nombre_jours", sa.Numeric(6, 2), nullable=False),
        sa.Column("motif", sa.Text(), nullable=True),
        sa.Column("justificatif_url", sa.Text(), nullable=True),
        sa.Column("statut", sa.String(length=30), nullable=False),
        sa.Column("validateur_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["validateur_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_hr_leaves_employee_id"), "hr_leaves", ["employee_id"], unique=False)
    op.create_index(op.f("ix_hr_leaves_tenant_id"), "hr_leaves", ["tenant_id"], unique=False)

    op.create_table(
        "hr_documents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("type_document", sa.String(length=50), nullable=False),
        sa.Column("titre", sa.String(length=180), nullable=False),
        sa.Column("fichier_url", sa.Text(), nullable=False),
        sa.Column("date_upload", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_hr_documents_employee_id"), "hr_documents", ["employee_id"], unique=False)
    op.create_index(op.f("ix_hr_documents_tenant_id"), "hr_documents", ["tenant_id"], unique=False)

    values = ",\n".join(
        f"('{code}', '{description.replace(chr(39), chr(39) + chr(39))}', NOW())"
        for code, description in HR_PERMISSIONS
    )
    op.execute(
        f"""
        INSERT INTO permissions (code, description, created_at)
        VALUES
        {values}
        ON CONFLICT (code) DO UPDATE
        SET description = EXCLUDED.description;
        """
    )
    non_sensitive = ", ".join(f"'{code}'" for code, _ in HR_PERMISSIONS if code != "rh.salaries.view")
    op.execute(
        f"""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r
        JOIN permissions p ON p.code IN ({non_sensitive})
        WHERE r.code = 'admin'
        ON CONFLICT DO NOTHING;
        """
    )


def downgrade() -> None:
    codes = ", ".join(f"'{code}'" for code, _ in HR_PERMISSIONS)
    op.execute(f"DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code IN ({codes}));")
    op.execute(f"DELETE FROM permissions WHERE code IN ({codes});")
    op.drop_index(op.f("ix_hr_documents_tenant_id"), table_name="hr_documents")
    op.drop_index(op.f("ix_hr_documents_employee_id"), table_name="hr_documents")
    op.drop_table("hr_documents")
    op.drop_index(op.f("ix_hr_leaves_tenant_id"), table_name="hr_leaves")
    op.drop_index(op.f("ix_hr_leaves_employee_id"), table_name="hr_leaves")
    op.drop_table("hr_leaves")
    op.drop_index(op.f("ix_hr_contracts_tenant_id"), table_name="hr_contracts")
    op.drop_index(op.f("ix_hr_contracts_employee_id"), table_name="hr_contracts")
    op.drop_table("hr_contracts")
    op.drop_index(op.f("ix_hr_employees_tenant_id"), table_name="hr_employees")
    op.drop_index(op.f("ix_hr_employees_service_id"), table_name="hr_employees")
    op.drop_index(op.f("ix_hr_employees_fonction_id"), table_name="hr_employees")
    op.drop_table("hr_employees")
    op.drop_index(op.f("ix_hr_functions_tenant_id"), table_name="hr_functions")
    op.drop_table("hr_functions")
    op.drop_index(op.f("ix_hr_services_tenant_id"), table_name="hr_services")
    op.drop_table("hr_services")
