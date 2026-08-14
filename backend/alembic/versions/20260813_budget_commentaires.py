"""fil de commentaires sur les lignes budgetaires

Revision ID: 20260813_budget_commentaires
Revises: 20260813_enc_person_types
Create Date: 2026-08-13 12:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision = "20260813_budget_commentaires"
down_revision = "20260813_enc_person_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "budget_poste_commentaires",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("exercice_id", sa.Integer(), nullable=False),
        # Ancre metier : le code survit aux reimports en mode remplacement, qui
        # suppriment physiquement les budget_postes et les recreent avec de
        # nouveaux ids. Rattacher le commentaire a l'id le ferait disparaitre.
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("budget_poste_id", sa.Integer(), nullable=True),
        sa.Column("texte", sa.Text(), nullable=False),
        sa.Column("statut_budget", sa.String(length=20), nullable=True),
        sa.Column("auteur_id", UUID(as_uuid=True), nullable=True),
        sa.Column("auteur_nom", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["exercice_id"], ["budget_exercices.id"], ondelete="CASCADE"),
        # SET NULL et non CASCADE : la suppression d'un poste ne doit pas
        # emporter le commentaire, c'est tout l'interet de l'ancre par code.
        sa.ForeignKeyConstraint(["budget_poste_id"], ["budget_postes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["auteur_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_budget_commentaires_ancre",
        "budget_poste_commentaires",
        ["organisation_id", "exercice_id", "code"],
    )
    op.create_index(
        "ix_budget_poste_commentaires_organisation_id",
        "budget_poste_commentaires",
        ["organisation_id"],
    )
    op.create_index(
        "ix_budget_poste_commentaires_exercice_id",
        "budget_poste_commentaires",
        ["exercice_id"],
    )
    op.create_index(
        "ix_budget_poste_commentaires_budget_poste_id",
        "budget_poste_commentaires",
        ["budget_poste_id"],
    )
    op.create_index(
        "ix_budget_poste_commentaires_created_at",
        "budget_poste_commentaires",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_budget_poste_commentaires_created_at", table_name="budget_poste_commentaires")
    op.drop_index("ix_budget_poste_commentaires_budget_poste_id", table_name="budget_poste_commentaires")
    op.drop_index("ix_budget_poste_commentaires_exercice_id", table_name="budget_poste_commentaires")
    op.drop_index("ix_budget_poste_commentaires_organisation_id", table_name="budget_poste_commentaires")
    op.drop_index("ix_budget_commentaires_ancre", table_name="budget_poste_commentaires")
    op.drop_table("budget_poste_commentaires")
