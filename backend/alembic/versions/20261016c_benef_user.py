"""bénéficiaire : un utilisateur de l'application

Revision ID: 20261016c_benef_user
Revises: 20261016b_benef_amont
Create Date: 2026-10-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261016c_benef_user"
down_revision = "20261016b_benef_amont"
branch_labels = None
depends_on = None

TABLES = ("sorties_fonds", "requisitions", "ordres_decaissement")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column(
                "beneficiaire_utilisateur_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, "beneficiaire_utilisateur_id")
