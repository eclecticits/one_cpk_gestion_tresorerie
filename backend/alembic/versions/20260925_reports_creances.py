"""Report des créances impayées vers les arriérés de l'exercice suivant

Revision ID: 20260925_reports_creances
Revises: 20260918_types_client

Une note « Cotisation 2026 » impayée à la clôture ne tombe pas : son reste dû
passe sur le poste d'arriérés de 2027, où s'imputent les versements suivants.

- budget_postes.code_poste_arrieres : le code du poste qui, dans l'exercice
  suivant, reprend ce qui reste dû sur ce poste ;
- reports_creances : une ligne par encaissement et par poste d'origine.

Aucune donnée n'est reportée ici : les exercices déjà clôturés le sont par
POST /budget/exercices/{annee}/reporter-creances, une fois les correspondances
de postes saisies.

Create Date: 2026-09-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260925_reports_creances"
down_revision = "20260918_types_client"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("budget_postes", sa.Column("code_poste_arrieres", sa.String(length=20), nullable=True))

    op.create_table(
        "reports_creances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("encaissement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("encaissements.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("exercice_source_id", sa.Integer(), sa.ForeignKey("budget_exercices.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("exercice_cible_id", sa.Integer(), sa.ForeignKey("budget_exercices.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("poste_source_id", sa.Integer(), sa.ForeignKey("budget_postes.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("poste_cible_id", sa.Integer(), sa.ForeignKey("budget_postes.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("montant", sa.Numeric(15, 2), nullable=False),
        sa.Column("statut", sa.String(length=20), nullable=False, server_default="ACTIVE"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("annule_le", sa.DateTime(timezone=True), nullable=True),
        sa.Column("annule_par_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint("montant > 0", name="ck_reports_creances_montant_positif"),
        sa.CheckConstraint("statut IN ('ACTIVE','REMPLACE','ANNULE')", name="ck_reports_creances_statut"),
    )
    op.create_index(
        "uq_reports_creances_part_vivante",
        "reports_creances",
        ["encaissement_id", "exercice_source_id", "poste_source_id"],
        unique=True,
        postgresql_where=sa.text("statut <> 'ANNULE'"),
    )
    op.create_index("ix_reports_creances_encaissement_statut", "reports_creances", ["encaissement_id", "statut"])
    op.create_index("ix_reports_creances_org_exercice_source", "reports_creances", ["organisation_id", "exercice_source_id"])
    op.create_index("ix_reports_creances_poste_cible_id", "reports_creances", ["poste_cible_id"])


def downgrade() -> None:
    op.drop_index("ix_reports_creances_poste_cible_id", table_name="reports_creances")
    op.drop_index("ix_reports_creances_org_exercice_source", table_name="reports_creances")
    op.drop_index("ix_reports_creances_encaissement_statut", table_name="reports_creances")
    op.drop_index("uq_reports_creances_part_vivante", table_name="reports_creances")
    op.drop_table("reports_creances")
    op.drop_column("budget_postes", "code_poste_arrieres")
