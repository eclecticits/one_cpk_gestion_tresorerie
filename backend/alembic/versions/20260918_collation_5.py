"""Cinq dollars par personne, cent par réunion

Revision ID: 20260918_collation5
Revises: 20260918_collation24

Les deux bornes étaient posées faute de connaître les usages : dix dollars par
tête, deux cents par réunion. Ce sont cinq et cent — le prix d'une collation
ici, et ce qu'une salle peut coûter.

Comme précédemment, une valeur ne se réécrit que là où elle valait encore celle
posée par défaut : une organisation qui l'aurait déjà réglée a décidé pour
elle-même, et son réglage n'est pas à reprendre.

Create Date: 2026-09-18
"""

from __future__ import annotations

from alembic import op


revision = "20260918_collation5"
down_revision = "20260918_collation24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "organisation_settings",
        "collation_plafond_par_personne_usd",
        server_default="5",
    )
    op.alter_column(
        "organisation_settings",
        "collation_plafond_total_usd",
        server_default="100",
    )
    op.execute(
        "UPDATE organisation_settings SET collation_plafond_par_personne_usd = 5 "
        "WHERE collation_plafond_par_personne_usd = 10"
    )
    op.execute(
        "UPDATE organisation_settings SET collation_plafond_total_usd = 100 "
        "WHERE collation_plafond_total_usd = 200"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE organisation_settings SET collation_plafond_total_usd = 200 "
        "WHERE collation_plafond_total_usd = 100"
    )
    op.execute(
        "UPDATE organisation_settings SET collation_plafond_par_personne_usd = 10 "
        "WHERE collation_plafond_par_personne_usd = 5"
    )
    op.alter_column(
        "organisation_settings",
        "collation_plafond_total_usd",
        server_default="200",
    )
    op.alter_column(
        "organisation_settings",
        "collation_plafond_par_personne_usd",
        server_default="10",
    )
