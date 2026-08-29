"""Add tenant-scoped idempotency keys to fund outflows."""

from alembic import op
import sqlalchemy as sa


revision = "20260829_sorties_idempotency"
down_revision = "20260828_export_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sorties_fonds", sa.Column("idempotency_key", sa.String(length=128), nullable=True))
    op.add_column("sorties_fonds", sa.Column("idempotency_payload_hash", sa.String(length=64), nullable=True))
    op.create_unique_constraint(
        "uq_sorties_fonds_org_idempotency_key",
        "sorties_fonds",
        ["organisation_id", "idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_sorties_fonds_org_idempotency_key", "sorties_fonds", type_="unique")
    op.drop_column("sorties_fonds", "idempotency_payload_hash")
    op.drop_column("sorties_fonds", "idempotency_key")
