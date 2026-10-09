"""délai de décision après rejet d'un dossier

Revision ID: 20261010_dossier_rejet_delai
Revises: 20261009_paiement_cc
Create Date: 2026-10-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261010_dossier_rejet_delai"
down_revision = "20261009_paiement_cc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("dossiers_requisition", sa.Column("rejete_le", sa.DateTime(timezone=True), nullable=True))
    op.add_column("dossiers_requisition", sa.Column("rejet_accepte_le", sa.DateTime(timezone=True), nullable=True))
    op.add_column("dossiers_requisition", sa.Column("rejet_accepte_par", postgresql.UUID(as_uuid=True), nullable=True))
    # Dossiers déjà rejetés : le délai court à partir de leur dernière mise à jour.
    op.execute("UPDATE dossiers_requisition SET rejete_le = updated_at WHERE status = 'REJETE'")


def downgrade() -> None:
    op.drop_column("dossiers_requisition", "rejet_accepte_par")
    op.drop_column("dossiers_requisition", "rejet_accepte_le")
    op.drop_column("dossiers_requisition", "rejete_le")
