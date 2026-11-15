"""Notes de débit : attestation comptable « en ordre de cotisation »

Revision ID: 20261114_cotis_attestations
Revises: 20261113_tableau_bilan_forco

- table `cotisations_attestations` : un membre, un exercice, qui et quand —
  aucun montant. Le Tableau lit la cotisation d'un membre attesté comme réglée
  sans attendre la saisie de la caisse ;
- permission `treso.experts_comptables.attester_cotisation`, accordée à
  l'administrateur et au comptable. La répartition se change ensuite dans
  l'écran des permissions.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql


revision = "20261114_cotis_attestations"
down_revision = "20261113_tableau_bilan_forco"
branch_labels = None
depends_on = None


CODE = "treso.experts_comptables.attester_cotisation"
DESCRIPTION = "Trésorerie — Experts-comptables : attester qu'un membre est en ordre de cotisation"
ROLES = ("admin", "comptable")

SEMER = """
    INSERT INTO permissions (code, description, created_at)
    VALUES (:code, :description, now())
    ON CONFLICT (code) DO UPDATE SET description = EXCLUDED.description
"""

ACCORDER = """
    INSERT INTO role_permissions (role_id, permission_id)
    SELECT r.id, p.id
    FROM roles r, permissions p
    WHERE r.code = :role AND p.code = :code
    ON CONFLICT DO NOTHING
"""


def upgrade() -> None:
    op.create_table(
        "cotisations_attestations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "expert_comptable_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("experts_comptables.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("exercice", sa.Integer(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "organisation_id", "expert_comptable_id", "exercice", name="uq_cotisation_attestation"
        ),
    )
    op.create_index(
        "ix_cotisations_attestations_organisation_id", "cotisations_attestations", ["organisation_id"]
    )
    op.create_index(
        "ix_cotisations_attestations_expert_comptable_id", "cotisations_attestations", ["expert_comptable_id"]
    )

    bind = op.get_bind()
    bind.execute(text(SEMER), {"code": CODE, "description": DESCRIPTION})
    for role in ROLES:
        bind.execute(text(ACCORDER), {"role": role, "code": CODE})


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code = :code)"),
        {"code": CODE},
    )
    bind.execute(text("DELETE FROM permissions WHERE code = :code"), {"code": CODE})
    op.drop_index("ix_cotisations_attestations_expert_comptable_id", table_name="cotisations_attestations")
    op.drop_index("ix_cotisations_attestations_organisation_id", table_name="cotisations_attestations")
    op.drop_table("cotisations_attestations")
