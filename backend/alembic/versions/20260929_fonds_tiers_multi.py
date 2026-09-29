"""Reverser plusieurs fonds de tiers en un seul versement

Revision ID: 20260929_fonds_tiers_multi
Revises: 20260925_reports_creances

- requisition_fonds_tiers : les fonds qu'une réquisition FONDS_DE_TIERS
  autorise à reverser, avec la part de chacun ;
- sortie_fonds_tiers : la part de chaque sortie imputée sur chaque fonds.

Reprise : chaque sortie déjà rattachée à un fonds (`fonds_tiers_operation_id`)
reçoit sa ligne, pour son montant entier. Le « déjà reversé » d'un fonds se
lit désormais dans cette seule table.

Create Date: 2026-09-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260929_fonds_tiers_multi"
down_revision = "20260925_reports_creances"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "requisition_fonds_tiers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("requisition_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("requisitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "fonds_tiers_operation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fonds_tiers_operations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("montant", sa.Numeric(14, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("montant > 0", name="ck_requisition_fonds_tiers_montant"),
        sa.UniqueConstraint("requisition_id", "fonds_tiers_operation_id", name="uq_requisition_fonds_tiers"),
    )
    op.create_index("ix_requisition_fonds_tiers_organisation_id", "requisition_fonds_tiers", ["organisation_id"])
    op.create_index("ix_requisition_fonds_tiers_requisition_id", "requisition_fonds_tiers", ["requisition_id"])
    op.create_index(
        "ix_requisition_fonds_tiers_fonds_tiers_operation_id", "requisition_fonds_tiers", ["fonds_tiers_operation_id"]
    )

    op.create_table(
        "sortie_fonds_tiers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("sortie_fonds_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sorties_fonds.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "fonds_tiers_operation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fonds_tiers_operations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("montant", sa.Numeric(14, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("montant > 0", name="ck_sortie_fonds_tiers_montant"),
        sa.UniqueConstraint("sortie_fonds_id", "fonds_tiers_operation_id", name="uq_sortie_fonds_tiers"),
    )
    op.create_index("ix_sortie_fonds_tiers_organisation_id", "sortie_fonds_tiers", ["organisation_id"])
    op.create_index("ix_sortie_fonds_tiers_sortie_fonds_id", "sortie_fonds_tiers", ["sortie_fonds_id"])
    op.create_index("ix_sortie_fonds_tiers_fonds_tiers_operation_id", "sortie_fonds_tiers", ["fonds_tiers_operation_id"])

    op.execute(
        """
        INSERT INTO sortie_fonds_tiers (id, organisation_id, sortie_fonds_id, fonds_tiers_operation_id, montant, created_at)
        SELECT gen_random_uuid(), sf.organisation_id, sf.id, sf.fonds_tiers_operation_id, sf.montant_paye, sf.created_at
        FROM sorties_fonds sf
        WHERE sf.fonds_tiers_operation_id IS NOT NULL
          AND sf.montant_paye > 0
        """
    )


def downgrade() -> None:
    op.drop_table("sortie_fonds_tiers")
    op.drop_table("requisition_fonds_tiers")
