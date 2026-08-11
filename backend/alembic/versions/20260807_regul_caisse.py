"""Regularisation des ecarts de caisse : table de tracabilite + postes budgetaires

Un comptage physique ne remplace plus le solde theorique : l'ecart donne lieu a
une operation financiere identifiable (encaissement si excedent, sortie si
deficit). Cette revision cree la table qui relie l'ecart a son operation, et les
deux reglages qui designent les postes budgetaires a imputer.

Revision ID: 20260807_regul_caisse
Revises: 20260806_service_rubrique_active
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260807_regul_caisse"
down_revision = "20260806_service_rubrique_active"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "regularisations_caisse",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("source_reference", sa.String(length=50), nullable=True),
        sa.Column("devise", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("sens", sa.String(length=20), nullable=False),
        sa.Column("montant", sa.Numeric(15, 2), nullable=False),
        sa.Column("solde_theorique", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("solde_physique", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("encaissement_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sortie_fonds_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("motif", sa.Text(), nullable=False),
        sa.Column("created_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["encaissement_id"], ["encaissements.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sortie_fonds_id"], ["sorties_fonds.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "source_type IN ('OUVERTURE','CLOTURE')",
            name="ck_regularisations_caisse_source_type",
        ),
        sa.CheckConstraint("sens IN ('EXCEDENT','DEFICIT')", name="ck_regularisations_caisse_sens"),
        sa.CheckConstraint("devise IN ('USD','CDF')", name="ck_regularisations_caisse_devise"),
        sa.CheckConstraint("montant > 0", name="ck_regularisations_caisse_montant_positif"),
        sa.CheckConstraint(
            "(encaissement_id IS NOT NULL AND sortie_fonds_id IS NULL) OR "
            "(encaissement_id IS NULL AND sortie_fonds_id IS NOT NULL)",
            name="ck_regularisations_caisse_operation_unique",
        ),
    )
    op.create_index(
        "ix_regularisations_caisse_organisation_id",
        "regularisations_caisse",
        ["organisation_id"],
    )
    op.create_index(
        "ix_regularisations_caisse_source",
        "regularisations_caisse",
        ["organisation_id", "source_type", "source_id"],
    )
    op.create_index(
        "ix_regularisations_caisse_encaissement_id",
        "regularisations_caisse",
        ["encaissement_id"],
    )
    op.create_index(
        "ix_regularisations_caisse_sortie_fonds_id",
        "regularisations_caisse",
        ["sortie_fonds_id"],
    )

    # Postes budgetaires imputes par les regularisations. Nullables : tant qu'ils
    # ne sont pas configures, l'ecart reste simplement non regularise.
    op.add_column(
        "system_settings",
        sa.Column("budget_poste_excedent_caisse_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "system_settings",
        sa.Column("budget_poste_deficit_caisse_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_system_settings_poste_excedent_caisse",
        "system_settings",
        "budget_postes",
        ["budget_poste_excedent_caisse_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_system_settings_poste_deficit_caisse",
        "system_settings",
        "budget_postes",
        ["budget_poste_deficit_caisse_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_system_settings_poste_deficit_caisse", "system_settings", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_system_settings_poste_excedent_caisse", "system_settings", type_="foreignkey"
    )
    op.drop_column("system_settings", "budget_poste_deficit_caisse_id")
    op.drop_column("system_settings", "budget_poste_excedent_caisse_id")

    op.drop_index("ix_regularisations_caisse_sortie_fonds_id", table_name="regularisations_caisse")
    op.drop_index("ix_regularisations_caisse_encaissement_id", table_name="regularisations_caisse")
    op.drop_index("ix_regularisations_caisse_source", table_name="regularisations_caisse")
    op.drop_index(
        "ix_regularisations_caisse_organisation_id", table_name="regularisations_caisse"
    )
    op.drop_table("regularisations_caisse")
