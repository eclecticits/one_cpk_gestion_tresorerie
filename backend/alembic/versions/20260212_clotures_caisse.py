"""add clotures caisse table

Revision ID: 20260212_clotures_caisse
Revises: 20260212_merge_audit_heads
Create Date: 2026-02-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260212_clotures_caisse"
down_revision = "20260212_merge_audit_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clotures",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("reference_numero", sa.String(length=50), nullable=False),
        sa.Column("date_cloture", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("caissier_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("solde_initial_usd", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("solde_initial_cdf", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("total_entrees_usd", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("total_entrees_cdf", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("total_sorties_usd", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("total_sorties_cdf", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("solde_theorique_usd", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("solde_theorique_cdf", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("solde_physique_usd", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("solde_physique_cdf", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("ecart_usd", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("ecart_cdf", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("billetage_usd", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("billetage_cdf", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("observation", sa.String(length=500), nullable=True),
        sa.Column("statut", sa.String(length=30), nullable=False, server_default="VALIDEE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["caissier_id"], ["users.id"]),
        sa.UniqueConstraint("reference_numero", name="uq_clotures_reference_numero"),
    )
    op.create_index("ix_clotures_reference_numero", "clotures", ["reference_numero"])
    op.create_index("ix_clotures_caissier_id", "clotures", ["caissier_id"])
    op.create_index("ix_clotures_date_cloture", "clotures", ["date_cloture"])

    op.alter_column("clotures", "solde_initial_usd", server_default=None)
    op.alter_column("clotures", "solde_initial_cdf", server_default=None)
    op.alter_column("clotures", "total_entrees_usd", server_default=None)
    op.alter_column("clotures", "total_entrees_cdf", server_default=None)
    op.alter_column("clotures", "total_sorties_usd", server_default=None)
    op.alter_column("clotures", "total_sorties_cdf", server_default=None)
    op.alter_column("clotures", "solde_theorique_usd", server_default=None)
    op.alter_column("clotures", "solde_theorique_cdf", server_default=None)
    op.alter_column("clotures", "solde_physique_usd", server_default=None)
    op.alter_column("clotures", "solde_physique_cdf", server_default=None)
    op.alter_column("clotures", "ecart_usd", server_default=None)
    op.alter_column("clotures", "ecart_cdf", server_default=None)
    op.alter_column("clotures", "statut", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_clotures_date_cloture", table_name="clotures")
    op.drop_index("ix_clotures_caissier_id", table_name="clotures")
    op.drop_index("ix_clotures_reference_numero", table_name="clotures")
    op.drop_table("clotures")
