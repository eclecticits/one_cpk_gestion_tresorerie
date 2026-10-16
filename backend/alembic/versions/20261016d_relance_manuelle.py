"""relances de justificatif à la main du caissier

Revision ID: 20261016d_relance_manuelle
Revises: 20261016c_benef_user
Create Date: 2026-10-16
"""

from alembic import op
import sqlalchemy as sa


revision = "20261016d_relance_manuelle"
down_revision = "20261016c_benef_user"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sorties_fonds",
        sa.Column("justificatif_derniere_relance_le", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "sorties_fonds",
        sa.Column("justificatif_nb_relances", sa.Integer(), nullable=False, server_default="0"),
    )
    # La relance automatique déjà partie compte pour une.
    op.execute(
        "UPDATE sorties_fonds SET justificatif_derniere_relance_le = justificatif_relance_le, "
        "justificatif_nb_relances = 1 WHERE justificatif_relance_le IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("sorties_fonds", "justificatif_nb_relances")
    op.drop_column("sorties_fonds", "justificatif_derniere_relance_le")
