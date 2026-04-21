"""Add article lines to encaissements.

Revision ID: 20260421_enc_articles
Revises: 20260421_saas_invoices_alerts
Create Date: 2026-04-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260421_enc_articles"
down_revision = "20260421_saas_invoices_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.create_table(
        "encaissement_articles",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("encaissement_id", sa.UUID(), nullable=False),
        sa.Column("libelle", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("quantite", sa.Numeric(12, 2), nullable=False, server_default="1"),
        sa.Column("prix_unitaire", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("montant", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("montant >= 0", name="ck_encaissement_articles_montant_nonneg"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["encaissement_id"], ["encaissements.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_encaissement_articles_organisation_id", "encaissement_articles", ["organisation_id"])
    op.create_index("ix_encaissement_articles_encaissement_id", "encaissement_articles", ["encaissement_id"])

    op.execute(
        """
        INSERT INTO encaissement_articles (
            id,
            organisation_id,
            encaissement_id,
            libelle,
            description,
            quantite,
            prix_unitaire,
            montant,
            sort_order,
            created_at
        )
        SELECT
            gen_random_uuid(),
            organisation_id,
            id,
            COALESCE(NULLIF(trim(libelle), ''), 'Article encaissement'),
            description,
            1,
            COALESCE(montant_total, montant, 0),
            COALESCE(montant_total, montant, 0),
            0,
            created_at
        FROM encaissements
        WHERE is_deleted IS DISTINCT FROM true
        """
    )


def downgrade() -> None:
    op.drop_index("ix_encaissement_articles_encaissement_id", table_name="encaissement_articles")
    op.drop_index("ix_encaissement_articles_organisation_id", table_name="encaissement_articles")
    op.drop_table("encaissement_articles")
