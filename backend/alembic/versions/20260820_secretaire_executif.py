"""parametre du secretaire executif sur les pieces signees

Revision ID: 20260820_secretaire_exec
Revises: 20260818_engagements_derives
Create Date: 2026-08-20

Le bon de requisition et l'etat de frais reservent desormais un emplacement de
signature au demandeur et au Secretaire executif. Le titulaire du poste change
au fil des mandats : son nom se parametre au lieu d'etre code dans le gabarit.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260820_secretaire_exec"
down_revision = "20260818_engagements_derives"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "print_settings",
        sa.Column(
            "secretaire_executif_label",
            sa.String(length=200),
            nullable=False,
            server_default="Le Secrétaire exécutif",
        ),
    )
    op.add_column(
        "print_settings",
        sa.Column(
            "secretaire_executif_nom",
            sa.String(length=200),
            nullable=False,
            server_default="",
        ),
    )


def downgrade() -> None:
    op.drop_column("print_settings", "secretaire_executif_nom")
    op.drop_column("print_settings", "secretaire_executif_label")
