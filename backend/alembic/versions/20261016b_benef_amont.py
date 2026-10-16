"""bénéficiaire identifié dès la réquisition et l'ordre de décaissement

Revision ID: 20261016b_benef_amont
Revises: 20261016_benef_justif
Create Date: 2026-10-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261016b_benef_amont"
down_revision = "20261016_benef_justif"
branch_labels = None
depends_on = None

TABLES = ("requisitions", "ordres_decaissement")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("beneficiaire_type", sa.String(20), nullable=True))
        op.add_column(
            table,
            sa.Column(
                "beneficiaire_expert_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("experts_comptables.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.add_column(
            table,
            sa.Column(
                "beneficiaire_employe_id",
                sa.Integer(),
                sa.ForeignKey("hr_employees.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.add_column(
            table,
            sa.Column(
                "beneficiaire_externe_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("beneficiaires_externes.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.add_column(table, sa.Column("beneficiaire_email", sa.String(200), nullable=True))
        op.add_column(table, sa.Column("beneficiaire_telephone", sa.String(50), nullable=True))


def downgrade() -> None:
    for table in TABLES:
        for column in (
            "beneficiaire_telephone",
            "beneficiaire_email",
            "beneficiaire_externe_id",
            "beneficiaire_employe_id",
            "beneficiaire_expert_id",
            "beneficiaire_type",
        ):
            op.drop_column(table, column)
