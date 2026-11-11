"""Créances constatées à l'émission des notes de débit

Deux réglages sur la société comptable (constater ou non, et sous quel compte
ouvrir les comptes des membres) et le lien entre un compte et le membre qu'il
représente : un compte par membre, comme dans le logiciel comptable en place.

Revision ID: 20261111b_compta_creances
Revises: 20261111_compta_lettrage
Create Date: 2026-11-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20261111b_compta_creances"
down_revision = "20261111_compta_lettrage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "compta_societes",
        sa.Column("creances_actives", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "compta_societes",
        sa.Column(
            "compte_creances_racine_id",
            sa.Integer(),
            sa.ForeignKey("compta_comptes.id", ondelete="SET NULL", name="fk_compta_societe_racine_creances"),
            nullable=True,
        ),
    )
    # Racine des comptes des autres clients (non membres) ; vide, ils
    # s'ouvrent sous la même racine que les membres.
    op.add_column(
        "compta_societes",
        sa.Column(
            "compte_creances_clients_racine_id",
            sa.Integer(),
            sa.ForeignKey("compta_comptes.id", ondelete="SET NULL", name="fk_compta_societe_racine_clients"),
            nullable=True,
        ),
    )
    # Vocabulaire de l'organisation : un ordre parle de « membres », une
    # association d'« adhérents », une entreprise de « clients ».
    op.add_column(
        "compta_societes",
        sa.Column("libelle_tiers", sa.String(40), nullable=False, server_default="membre"),
    )
    op.add_column(
        "compta_societes",
        sa.Column("libelle_journal_creances", sa.String(100), nullable=False, server_default="Adhérents"),
    )
    op.add_column(
        "compta_comptes",
        sa.Column(
            "tiers_expert_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("experts_comptables.id", ondelete="SET NULL", name="fk_compta_compte_tiers_expert"),
            nullable=True,
        ),
    )
    op.add_column(
        "compta_comptes",
        sa.Column(
            "tiers_client_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clients.id", ondelete="SET NULL", name="fk_compta_compte_tiers_client"),
            nullable=True,
        ),
    )
    op.create_index(
        "uq_compta_compte_tiers_client",
        "compta_comptes",
        ["organisation_id", "tiers_client_id"],
        unique=True,
        postgresql_where=sa.text("tiers_client_id IS NOT NULL"),
    )
    op.create_index(
        "uq_compta_compte_tiers_expert",
        "compta_comptes",
        ["organisation_id", "tiers_expert_id"],
        unique=True,
        postgresql_where=sa.text("tiers_expert_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_compta_compte_tiers_expert", table_name="compta_comptes")
    op.drop_index("uq_compta_compte_tiers_client", table_name="compta_comptes")
    op.drop_column("compta_comptes", "tiers_client_id")
    op.drop_column("compta_societes", "compte_creances_clients_racine_id")
    op.drop_column("compta_comptes", "tiers_expert_id")
    op.drop_column("compta_societes", "libelle_journal_creances")
    op.drop_column("compta_societes", "libelle_tiers")
    op.drop_column("compta_societes", "compte_creances_racine_id")
    op.drop_column("compta_societes", "creances_actives")
