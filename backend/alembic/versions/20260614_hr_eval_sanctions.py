"""hr evaluations and sanctions

Revision ID: 20260614_hr_eval_sanctions
Revises: 678847c0d8e0
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa

revision = "20260614_hr_eval_sanctions"
down_revision = "678847c0d8e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hr_evaluations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("annee", sa.Integer(), nullable=False),
        sa.Column("periode", sa.String(20), nullable=False, server_default="annuelle"),
        sa.Column("note_globale", sa.Numeric(4, 2), nullable=True),
        sa.Column("appreciation", sa.String(50), nullable=True),
        sa.Column("objectifs_atteints", sa.Text(), nullable=True),
        sa.Column("axes_amelioration", sa.Text(), nullable=True),
        sa.Column("commentaire", sa.Text(), nullable=True),
        sa.Column("statut", sa.String(30), nullable=False, server_default="brouillon"),
        sa.Column("evaluateur_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    op.create_table(
        "hr_sanctions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("hr_employees.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("type_sanction", sa.String(50), nullable=False),
        sa.Column("date_sanction", sa.Date(), nullable=False),
        sa.Column("motif", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("duree_jours", sa.Integer(), nullable=True),
        sa.Column("statut", sa.String(30), nullable=False, server_default="actif"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("hr_sanctions")
    op.drop_table("hr_evaluations")
