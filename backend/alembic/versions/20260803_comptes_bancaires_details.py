"""Enrichit les details des comptes bancaires

Revision ID: 20260803_bank_details
Revises: 20260802_expert_province
Create Date: 2026-08-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260803_bank_details"
down_revision = "20260802_expert_province"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("comptes_bancaires", sa.Column("rib", sa.String(length=50), nullable=True))
    op.add_column("comptes_bancaires", sa.Column("identifiant_client", sa.String(length=50), nullable=True))
    op.add_column("comptes_bancaires", sa.Column("code_swift_bic", sa.String(length=20), nullable=True))
    op.add_column("comptes_bancaires", sa.Column("compte_comptable_associe", sa.String(length=50), nullable=True))
    op.add_column("comptes_bancaires", sa.Column("journal_comptable_associe", sa.String(length=50), nullable=True))
    op.add_column("comptes_bancaires", sa.Column("date_ouverture", sa.Date(), nullable=True))
    op.add_column(
        "comptes_bancaires",
        sa.Column("is_principal", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
    )
    op.add_column("comptes_bancaires", sa.Column("agence_bancaire", sa.String(length=150), nullable=True))
    op.add_column("comptes_bancaires", sa.Column("observations", sa.Text(), nullable=True))

    op.alter_column("comptes_bancaires", "numero_compte", type_=sa.String(length=50), existing_nullable=False)

    op.drop_constraint("uq_comptes_bancaires_org_numero_compte", "comptes_bancaires", type_="unique")
    op.create_unique_constraint(
        "uq_comptes_bancaires_org_banque_devise_numero",
        "comptes_bancaires",
        ["organisation_id", "banque_id", "devise", "numero_compte"],
    )
    op.create_index(
        "uq_comptes_bancaires_org_rib",
        "comptes_bancaires",
        ["organisation_id", "rib"],
        unique=True,
        postgresql_where=sa.text("rib IS NOT NULL"),
    )
    op.create_index(
        "uq_comptes_bancaires_principal_org_devise",
        "comptes_bancaires",
        ["organisation_id", "devise"],
        unique=True,
        postgresql_where=sa.text("is_principal IS TRUE AND account_type = 'BANK'"),
    )


def downgrade() -> None:
    op.drop_index("uq_comptes_bancaires_principal_org_devise", table_name="comptes_bancaires")
    op.drop_index("uq_comptes_bancaires_org_rib", table_name="comptes_bancaires")
    op.drop_constraint("uq_comptes_bancaires_org_banque_devise_numero", "comptes_bancaires", type_="unique")
    op.create_unique_constraint(
        "uq_comptes_bancaires_org_numero_compte",
        "comptes_bancaires",
        ["organisation_id", "numero_compte"],
    )

    op.alter_column("comptes_bancaires", "numero_compte", type_=sa.String(length=120), existing_nullable=False)

    op.drop_column("comptes_bancaires", "observations")
    op.drop_column("comptes_bancaires", "agence_bancaire")
    op.drop_column("comptes_bancaires", "is_principal")
    op.drop_column("comptes_bancaires", "date_ouverture")
    op.drop_column("comptes_bancaires", "journal_comptable_associe")
    op.drop_column("comptes_bancaires", "compte_comptable_associe")
    op.drop_column("comptes_bancaires", "code_swift_bic")
    op.drop_column("comptes_bancaires", "identifiant_client")
    op.drop_column("comptes_bancaires", "rib")
