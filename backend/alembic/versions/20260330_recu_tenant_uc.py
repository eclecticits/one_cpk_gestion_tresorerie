"""scope receipt uniqueness by organisation

Revision ID: 20260330_recu_tenant_uc
Revises: 20260328_paystat_val
Create Date: 2026-03-30
"""

from alembic import op

revision = "20260330_recu_tenant_uc"
down_revision = "20260328_paystat_val"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("encaissements_numero_recu_key", "encaissements", type_="unique")
    op.create_unique_constraint(
        "uq_encaissements_org_numero",
        "encaissements",
        ["organisation_id", "numero_recu"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_encaissements_org_numero", "encaissements", type_="unique")
    op.create_unique_constraint(
        "encaissements_numero_recu_key",
        "encaissements",
        ["numero_recu"],
    )
