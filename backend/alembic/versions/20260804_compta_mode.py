"""Mode d integration comptable configurable.

Revision ID: 20260804_compta_mode
Revises: 20260804_encaissement_pieces
Create Date: 2026-08-04
"""

from alembic import op
import sqlalchemy as sa


revision = "20260804_compta_mode"
down_revision = "20260804_encaissement_pieces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organisation_settings",
        sa.Column("accounting_integration_mode", sa.String(length=20), nullable=False, server_default="manual"),
    )
    op.add_column(
        "encaissements",
        sa.Column(
            "statut_comptabilisation",
            sa.String(length=40),
            nullable=False,
            server_default="NON_COMPTABILISEE",
        ),
    )
    op.add_column("encaissements", sa.Column("message_comptabilisation", sa.Text(), nullable=True))
    op.add_column(
        "sorties_fonds",
        sa.Column(
            "statut_comptabilisation",
            sa.String(length=40),
            nullable=False,
            server_default="NON_COMPTABILISEE",
        ),
    )
    op.add_column("sorties_fonds", sa.Column("message_comptabilisation", sa.Text(), nullable=True))
    op.create_index("ix_encaissements_statut_comptabilisation", "encaissements", ["statut_comptabilisation"])
    op.create_index("ix_sorties_fonds_statut_comptabilisation", "sorties_fonds", ["statut_comptabilisation"])


def downgrade() -> None:
    op.drop_index("ix_sorties_fonds_statut_comptabilisation", table_name="sorties_fonds")
    op.drop_index("ix_encaissements_statut_comptabilisation", table_name="encaissements")
    op.drop_column("sorties_fonds", "message_comptabilisation")
    op.drop_column("sorties_fonds", "statut_comptabilisation")
    op.drop_column("encaissements", "message_comptabilisation")
    op.drop_column("encaissements", "statut_comptabilisation")
    op.drop_column("organisation_settings", "accounting_integration_mode")
