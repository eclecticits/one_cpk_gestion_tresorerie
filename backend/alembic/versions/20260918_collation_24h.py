"""Deux cents dollars par réunion, quatre cents sur vingt-quatre heures

Revision ID: 20260918_collation24
Revises: 20260918_collation

Le plafond par réunion borne une dépense ; il ne borne pas une journée. Rien
n'empêchait d'aligner les réunions — une le matin, une l'après-midi, une autre
le soir — et de vider la caisse par petites salles successives, chacune dans
les clous.

La collation reçoit donc deux bornes de plus que le prix par tête : deux cents
dollars pour une réunion, quatre cents pour l'ensemble des collations d'une
journée glissante. La première dit ce qu'une salle peut coûter, la seconde ce
qu'une journée peut coûter.

Le plafond par réunion passe de cinq cents à deux cents, mais seulement là où il
valait encore la valeur posée par défaut : une organisation qui l'aurait déjà
réglé a décidé pour elle-même, et son réglage n'est pas à réécrire.

Create Date: 2026-09-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260918_collation24"
down_revision = "20260918_collation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organisation_settings",
        sa.Column(
            "collation_plafond_24h_usd",
            sa.Numeric(14, 2),
            nullable=False,
            server_default="400",
        ),
    )
    op.alter_column(
        "organisation_settings",
        "collation_plafond_total_usd",
        server_default="200",
    )
    op.execute(
        "UPDATE organisation_settings SET collation_plafond_total_usd = 200 "
        "WHERE collation_plafond_total_usd = 500"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE organisation_settings SET collation_plafond_total_usd = 500 "
        "WHERE collation_plafond_total_usd = 200"
    )
    op.alter_column(
        "organisation_settings",
        "collation_plafond_total_usd",
        server_default="500",
    )
    op.drop_column("organisation_settings", "collation_plafond_24h_usd")
