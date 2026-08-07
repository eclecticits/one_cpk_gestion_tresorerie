"""Ajoute le flag `active` sur service_rubriques (soft-deactivate des postes autorisés)."""

from alembic import op
import sqlalchemy as sa


revision = "20260806_service_rubrique_active"
down_revision = "20260805_retours_caisse"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "service_rubriques",
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_index("ix_service_rubriques_active", "service_rubriques", ["active"])


def downgrade() -> None:
    op.drop_index("ix_service_rubriques_active", table_name="service_rubriques")
    op.drop_column("service_rubriques", "active")
