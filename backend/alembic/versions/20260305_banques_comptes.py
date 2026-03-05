"""banques comptes and canal on encaissements/sorties

Revision ID: 20260305_banques_comptes
Revises: 20260302_perm_examens
Create Date: 2026-03-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260305_banques_comptes"
down_revision = "20260302_perm_examens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "banques",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("nom", sa.String(length=150), nullable=False, unique=True),
        sa.Column("code", sa.String(length=50), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
    )
    op.create_table(
        "comptes_bancaires",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("banque_id", sa.Integer(), nullable=False),
        sa.Column("intitule", sa.String(length=200), nullable=False),
        sa.Column("numero_compte", sa.String(length=120), nullable=False, unique=True),
        sa.Column("devise", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("solde_initial", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.ForeignKeyConstraint(["banque_id"], ["banques.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_comptes_bancaires_banque_id", "comptes_bancaires", ["banque_id"])

    op.add_column(
        "encaissements",
        sa.Column("canal", sa.String(length=10), nullable=False, server_default="CAISSE"),
    )
    op.add_column(
        "encaissements",
        sa.Column("compte_bancaire_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "encaissements",
        sa.Column("piece_jointe", sa.String(length=250), nullable=True),
    )
    op.create_index("ix_encaissements_compte_bancaire_id", "encaissements", ["compte_bancaire_id"])
    op.create_foreign_key(
        "fk_encaissements_compte_bancaire_id",
        "encaissements",
        "comptes_bancaires",
        ["compte_bancaire_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_encaissements_canal",
        "encaissements",
        "canal IN ('CAISSE','BANQUE')",
    )
    op.create_check_constraint(
        "ck_encaissements_compte_bancaire",
        "encaissements",
        "(canal = 'CAISSE' AND compte_bancaire_id IS NULL) OR "
        "(canal = 'BANQUE' AND compte_bancaire_id IS NOT NULL)",
    )

    op.add_column(
        "sorties_fonds",
        sa.Column("canal", sa.String(length=10), nullable=False, server_default="CAISSE"),
    )
    op.add_column(
        "sorties_fonds",
        sa.Column("compte_bancaire_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_sorties_fonds_compte_bancaire_id", "sorties_fonds", ["compte_bancaire_id"])
    op.create_foreign_key(
        "fk_sorties_fonds_compte_bancaire_id",
        "sorties_fonds",
        "comptes_bancaires",
        ["compte_bancaire_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_sorties_fonds_canal",
        "sorties_fonds",
        "canal IN ('CAISSE','BANQUE')",
    )
    op.create_check_constraint(
        "ck_sorties_fonds_compte_bancaire",
        "sorties_fonds",
        "(canal = 'CAISSE' AND compte_bancaire_id IS NULL) OR "
        "(canal = 'BANQUE' AND compte_bancaire_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_sorties_fonds_compte_bancaire", "sorties_fonds", type_="check")
    op.drop_constraint("ck_sorties_fonds_canal", "sorties_fonds", type_="check")
    op.drop_constraint("fk_sorties_fonds_compte_bancaire_id", "sorties_fonds", type_="foreignkey")
    op.drop_index("ix_sorties_fonds_compte_bancaire_id", table_name="sorties_fonds")
    op.drop_column("sorties_fonds", "compte_bancaire_id")
    op.drop_column("sorties_fonds", "canal")

    op.drop_constraint("ck_encaissements_compte_bancaire", "encaissements", type_="check")
    op.drop_constraint("ck_encaissements_canal", "encaissements", type_="check")
    op.drop_constraint("fk_encaissements_compte_bancaire_id", "encaissements", type_="foreignkey")
    op.drop_index("ix_encaissements_compte_bancaire_id", table_name="encaissements")
    op.drop_column("encaissements", "piece_jointe")
    op.drop_column("encaissements", "compte_bancaire_id")
    op.drop_column("encaissements", "canal")

    op.drop_index("ix_comptes_bancaires_banque_id", table_name="comptes_bancaires")
    op.drop_table("comptes_bancaires")
    op.drop_table("banques")
