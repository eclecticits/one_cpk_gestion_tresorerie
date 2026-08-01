"""Module Comptabilité (Lot 3) — mapping des rubriques techniques

`compta_mapping_rubrique` : résolution de compte par CODE fonctionnel, pour
les faits générateurs qui n'ont ni poste budgétaire ni compte bancaire à
mapper (paie, encaissement issu d'un paiement en ligne).

Revision ID: 20260731_compta_rubriques
Revises: 20260731_compta_caisse_defaut
Create Date: 2026-07-31
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260731_compta_rubriques"
down_revision = "20260731_compta_caisse_defaut"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "compta_mapping_rubrique",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column("code_rubrique", sa.String(length=60), nullable=False),
        sa.Column(
            "compte_id",
            sa.Integer(),
            sa.ForeignKey("compta_comptes.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint("organisation_id", "code_rubrique", name="uq_compta_mapping_rubrique"),
    )


def downgrade() -> None:
    op.drop_table("compta_mapping_rubrique")
