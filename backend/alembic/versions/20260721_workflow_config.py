"""Circuit de validation configurable par organisation.

Ajoute :
- organisation_settings.workflow_config (JSONB) : réglage du circuit par tenant.
- requisitions.workflow_snapshot (JSONB) : photo du circuit à la création de la
  réquisition (le circuit la suit jusqu'au bout, indépendamment des réglages
  ultérieurs). Null => circuit complet par défaut.

Revision ID: 20260721_workflow_config
Revises: 20260720_tableau_conclusion_cols
Create Date: 2026-07-21
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "20260721_workflow_config"
down_revision = "20260720_tableau_conclusion_cols"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organisation_settings",
        sa.Column("workflow_config", JSONB(), nullable=True),
    )
    op.add_column(
        "requisitions",
        sa.Column("workflow_snapshot", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("requisitions", "workflow_snapshot")
    op.drop_column("organisation_settings", "workflow_config")
