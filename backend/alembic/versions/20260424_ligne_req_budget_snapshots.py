"""add budget snapshots to lignes requisition

Revision ID: 20260424_lig_req_snap
Revises: 20260423_module_permissions
Create Date: 2026-04-24
"""

from alembic import op
import sqlalchemy as sa


revision = "20260424_lig_req_snap"
down_revision = "20260423_module_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lignes_requisition", sa.Column("budget_poste_code_snapshot", sa.String(length=20), nullable=True))
    op.add_column("lignes_requisition", sa.Column("budget_poste_libelle_snapshot", sa.String(length=255), nullable=True))
    op.add_column("lignes_requisition", sa.Column("montant_alloue_snapshot", sa.Numeric(15, 2), nullable=True))
    op.add_column("lignes_requisition", sa.Column("montant_disponible_snapshot", sa.Numeric(15, 2), nullable=True))

    op.execute(
        """
        UPDATE lignes_requisition lr
        SET budget_poste_code_snapshot = bp.code,
            budget_poste_libelle_snapshot = bp.libelle,
            montant_alloue_snapshot = bp.montant_prevu,
            montant_disponible_snapshot = bp.montant_prevu - bp.montant_engage
        FROM budget_postes bp
        WHERE lr.budget_poste_id = bp.id
        """
    )


def downgrade() -> None:
    op.drop_column("lignes_requisition", "montant_disponible_snapshot")
    op.drop_column("lignes_requisition", "montant_alloue_snapshot")
    op.drop_column("lignes_requisition", "budget_poste_libelle_snapshot")
    op.drop_column("lignes_requisition", "budget_poste_code_snapshot")
