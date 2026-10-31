"""dates du modèle Déclarations assurance gestionnaire CP

Revision ID: 20261031_tableau_assurance_cp
Revises: 20261031_tableau_pm_cp
Create Date: 2026-10-31
"""

from alembic import op
import sqlalchemy as sa


revision = "20261031_tableau_assurance_cp"
down_revision = "20261031_tableau_pm_cp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tableau_insurance_declarations",
        sa.Column("date_declaration", sa.Date(), nullable=True),
    )
    op.add_column(
        "tableau_insurance_declarations",
        sa.Column("date_souscription", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tableau_insurance_declarations", "date_souscription")
    op.drop_column("tableau_insurance_declarations", "date_declaration")
