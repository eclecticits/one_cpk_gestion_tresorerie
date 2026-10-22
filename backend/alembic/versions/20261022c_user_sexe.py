"""sexe des utilisateurs

Facultatif en base : les comptes existants n'en ont pas, et NULL est la seule
façon honnête de le dire. Le formulaire de création l'exige pour les nouveaux.
Même codage que les clients et les experts : « M » ou « F ».

Revision ID: 20261022c_user_sexe
Revises: 20261022b_user_telephone
Create Date: 2026-10-22
"""

from alembic import op
import sqlalchemy as sa


revision = "20261022c_user_sexe"
down_revision = "20261022b_user_telephone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("sexe", sa.String(length=1), nullable=True))
    op.create_check_constraint("ck_users_sexe", "users", "sexe IS NULL OR sexe IN ('M', 'F')")


def downgrade() -> None:
    op.drop_constraint("ck_users_sexe", "users", type_="check")
    op.drop_column("users", "sexe")
