"""add budget poste snapshot fields

Revision ID: 20260217_budget_poste_snapshots
Revises: 20260217_budget_postes
Create Date: 2026-02-17
"""

from alembic import op
import sqlalchemy as sa

revision = "20260217_budget_poste_snapshots"
down_revision = "20260217_budget_postes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("encaissements", sa.Column("budget_poste_code", sa.String(length=20), nullable=True))
    op.add_column("encaissements", sa.Column("budget_poste_libelle", sa.String(length=255), nullable=True))
    op.add_column("sorties_fonds", sa.Column("budget_poste_code", sa.String(length=20), nullable=True))
    op.add_column("sorties_fonds", sa.Column("budget_poste_libelle", sa.String(length=255), nullable=True))

    op.execute(
        """
        UPDATE encaissements e
        SET budget_poste_code = b.code,
            budget_poste_libelle = b.libelle
        FROM budget_postes b
        WHERE e.budget_poste_id = b.id
        """
    )
    op.execute(
        """
        UPDATE sorties_fonds s
        SET budget_poste_code = b.code,
            budget_poste_libelle = b.libelle
        FROM budget_postes b
        WHERE s.budget_poste_id = b.id
        """
    )


def downgrade() -> None:
    op.drop_column("sorties_fonds", "budget_poste_libelle")
    op.drop_column("sorties_fonds", "budget_poste_code")
    op.drop_column("encaissements", "budget_poste_libelle")
    op.drop_column("encaissements", "budget_poste_code")
