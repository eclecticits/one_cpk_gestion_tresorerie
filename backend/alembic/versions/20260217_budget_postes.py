"""rename budget lignes to postes

Revision ID: 20260217_budget_postes
Revises: 20260217_budget_parent
Create Date: 2026-02-17
"""

from alembic import op

revision = "20260217_budget_postes"
down_revision = "20260217_budget_parent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("budget_lignes", "budget_postes")

    op.alter_column("encaissements", "budget_ligne_id", new_column_name="budget_poste_id")
    op.alter_column("sorties_fonds", "budget_ligne_id", new_column_name="budget_poste_id")
    op.alter_column("lignes_requisition", "budget_ligne_id", new_column_name="budget_poste_id")
    op.alter_column("budget_audit_logs", "budget_ligne_id", new_column_name="budget_poste_id")

    op.execute("ALTER INDEX IF EXISTS ix_budget_lignes_is_deleted RENAME TO ix_budget_postes_is_deleted;")
    op.execute("ALTER INDEX IF EXISTS ix_budget_lignes_parent_id RENAME TO ix_budget_postes_parent_id;")


def downgrade() -> None:
    op.execute("ALTER INDEX IF EXISTS ix_budget_postes_is_deleted RENAME TO ix_budget_lignes_is_deleted;")
    op.execute("ALTER INDEX IF EXISTS ix_budget_postes_parent_id RENAME TO ix_budget_lignes_parent_id;")

    op.alter_column("budget_audit_logs", "budget_poste_id", new_column_name="budget_ligne_id")
    op.alter_column("lignes_requisition", "budget_poste_id", new_column_name="budget_ligne_id")
    op.alter_column("sorties_fonds", "budget_poste_id", new_column_name="budget_ligne_id")
    op.alter_column("encaissements", "budget_poste_id", new_column_name="budget_ligne_id")

    op.rename_table("budget_postes", "budget_lignes")
