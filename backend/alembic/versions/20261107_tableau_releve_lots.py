"""Tableau : envois groupés des relevés de situation

Revision ID: 20261107_tableau_releve_lots
Revises: 20261107_tableau_releves

Un lot fige la liste des membres au lancement et avance membre par membre, en
arrière-plan ; chaque relevé envoyé garde le lot d'où il vient.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20261107_tableau_releve_lots"
down_revision = "20261107_tableau_releves"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tableau_releve_lots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("exercice", sa.String(20), nullable=False),
        sa.Column("canaux", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("renvoyer", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("numeros", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("traites", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("envoyes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("echecs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deja_envoyes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ignores", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("statut", sa.String(12), nullable=False, server_default="en_cours"),
        sa.Column("cree_par", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("termine_le", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("statut IN ('en_cours', 'termine', 'interrompu')", name="ck_tableau_releve_lot_statut"),
    )
    op.create_index("ix_tableau_releve_lots_organisation_id", "tableau_releve_lots", ["organisation_id"])
    op.add_column(
        "tableau_releves",
        sa.Column("lot_id", sa.Integer(), sa.ForeignKey("tableau_releve_lots.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_tableau_releves_lot_id", "tableau_releves", ["lot_id"])


def downgrade() -> None:
    op.drop_index("ix_tableau_releves_lot_id", table_name="tableau_releves")
    op.drop_column("tableau_releves", "lot_id")
    op.drop_index("ix_tableau_releve_lots_organisation_id", table_name="tableau_releve_lots")
    op.drop_table("tableau_releve_lots")
