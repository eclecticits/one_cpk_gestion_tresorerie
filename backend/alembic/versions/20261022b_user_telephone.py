"""numéro de téléphone des utilisateurs

Un compte n'avait qu'une adresse e-mail : impossible de joindre un agent par
téléphone ou WhatsApp sans aller chercher son numéro ailleurs. Le numéro est
facultatif et stocké normalisé (E.164 sans « + »), comme celui des membres.

Revision ID: 20261022b_user_telephone
Revises: 20261022a_participant_ordre
Create Date: 2026-10-22
"""

from alembic import op
import sqlalchemy as sa


revision = "20261022b_user_telephone"
down_revision = "20261022a_participant_ordre"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("telephone", sa.String(length=30), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "telephone")
