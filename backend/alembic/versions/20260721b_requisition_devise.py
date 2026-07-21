"""Devise explicite sur la réquisition.

Ajoute `requisitions.devise` (défaut 'USD') : la devise dans laquelle
`montant_total` est exprimé. Rend fiable la conversion vers la devise pivot
(notamment pour le seuil de la 2e validation). Les réquisitions existantes
sont initialisées à 'USD' (convention historique).

Revision ID: 20260721b_requisition_devise
Revises: 20260721_workflow_config
Create Date: 2026-07-21
"""

from alembic import op
import sqlalchemy as sa


revision = "20260721b_requisition_devise"
down_revision = "20260721_workflow_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "requisitions",
        sa.Column("devise", sa.String(length=3), nullable=False, server_default="USD"),
    )
    # Retire le server_default après remplissage : la valeur est désormais
    # gérée par l'application.
    op.alter_column("requisitions", "devise", server_default=None)


def downgrade() -> None:
    op.drop_column("requisitions", "devise")
