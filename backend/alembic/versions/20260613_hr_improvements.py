"""hr improvements: leave allocations, attendance, payroll, employee exit fields

Revision ID: 20260613_hr_improvements
Revises: 20260613_org_modules
Create Date: 2026-06-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg


revision = "20260613_hr_improvements"
down_revision = "20260613_org_modules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. hr_leave_allocations
    op.create_table(
        "hr_leave_allocations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("type_absence", sa.String(length=50), nullable=False),
        sa.Column("annee", sa.Integer(), nullable=False),
        sa.Column("jours_alloues", sa.Numeric(6, 2), nullable=False),
        sa.Column("report_annee_precedente", sa.Numeric(6, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_employees.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "employee_id", "type_absence", "annee", name="uq_hr_leave_alloc_tenant_emp_type_year"),
    )
    op.create_index(op.f("ix_hr_leave_allocations_tenant_id"), "hr_leave_allocations", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_hr_leave_allocations_employee_id"), "hr_leave_allocations", ["employee_id"], unique=False)

    # 2. hr_attendances
    op.create_table(
        "hr_attendances",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("date_presence", sa.Date(), nullable=False),
        sa.Column("statut_presence", sa.String(length=30), nullable=False),
        sa.Column("heure_arrivee", sa.String(length=10), nullable=True),
        sa.Column("heure_depart", sa.String(length=10), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("saisi_par", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_employees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["saisi_par"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "employee_id", "date_presence", name="uq_hr_attendances_tenant_emp_date"),
    )
    op.create_index(op.f("ix_hr_attendances_tenant_id"), "hr_attendances", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_hr_attendances_employee_id"), "hr_attendances", ["employee_id"], unique=False)
    op.create_index(op.f("ix_hr_attendances_date_presence"), "hr_attendances", ["date_presence"], unique=False)

    # 3. hr_payroll_entries
    op.create_table(
        "hr_payroll_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("mois", sa.Integer(), nullable=False),
        sa.Column("annee", sa.Integer(), nullable=False),
        sa.Column("statut", sa.String(length=30), nullable=False, server_default="brouillon"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("nb_bulletins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "mois", "annee", name="uq_hr_payroll_entries_tenant_mois_annee"),
    )
    op.create_index(op.f("ix_hr_payroll_entries_tenant_id"), "hr_payroll_entries", ["tenant_id"], unique=False)

    # 4. hr_salary_slips
    op.create_table(
        "hr_salary_slips",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("payroll_entry_id", sa.Integer(), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("salaire_base", sa.Numeric(14, 2), nullable=False),
        sa.Column("total_primes", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("total_retenues", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("net_a_payer", sa.Numeric(14, 2), nullable=False),
        sa.Column("devise", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("jours_travailles", sa.Integer(), nullable=True),
        sa.Column("jours_absences", sa.Integer(), nullable=True),
        sa.Column("statut", sa.String(length=30), nullable=False, server_default="brouillon"),
        sa.Column("pdf_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["payroll_entry_id"], ["hr_payroll_entries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_employees.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payroll_entry_id", "employee_id", name="uq_hr_salary_slips_entry_employee"),
    )
    op.create_index(op.f("ix_hr_salary_slips_tenant_id"), "hr_salary_slips", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_hr_salary_slips_payroll_entry_id"), "hr_salary_slips", ["payroll_entry_id"], unique=False)
    op.create_index(op.f("ix_hr_salary_slips_employee_id"), "hr_salary_slips", ["employee_id"], unique=False)

    # 5. Alter hr_employees: add date_sortie and raison_sortie
    op.add_column("hr_employees", sa.Column("date_sortie", sa.Date(), nullable=True))
    op.add_column("hr_employees", sa.Column("raison_sortie", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("hr_employees", "raison_sortie")
    op.drop_column("hr_employees", "date_sortie")

    op.drop_index(op.f("ix_hr_salary_slips_employee_id"), table_name="hr_salary_slips")
    op.drop_index(op.f("ix_hr_salary_slips_payroll_entry_id"), table_name="hr_salary_slips")
    op.drop_index(op.f("ix_hr_salary_slips_tenant_id"), table_name="hr_salary_slips")
    op.drop_table("hr_salary_slips")

    op.drop_index(op.f("ix_hr_payroll_entries_tenant_id"), table_name="hr_payroll_entries")
    op.drop_table("hr_payroll_entries")

    op.drop_index(op.f("ix_hr_attendances_date_presence"), table_name="hr_attendances")
    op.drop_index(op.f("ix_hr_attendances_employee_id"), table_name="hr_attendances")
    op.drop_index(op.f("ix_hr_attendances_tenant_id"), table_name="hr_attendances")
    op.drop_table("hr_attendances")

    op.drop_index(op.f("ix_hr_leave_allocations_employee_id"), table_name="hr_leave_allocations")
    op.drop_index(op.f("ix_hr_leave_allocations_tenant_id"), table_name="hr_leave_allocations")
    op.drop_table("hr_leave_allocations")
