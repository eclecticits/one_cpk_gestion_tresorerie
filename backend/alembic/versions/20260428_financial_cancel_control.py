"""Add controlled cancellation metadata and permissions for financial operations.

Revision ID: 20260428_fin_cancel
Revises: 20260428_enc_mode_cheque
Create Date: 2026-04-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260428_fin_cancel"
down_revision = "20260428_enc_mode_cheque"
branch_labels = None
depends_on = None


PERMISSIONS = [
    ("cancel_encaissement", "Annuler un encaissement"),
    ("cancel_sortie_fonds", "Annuler une sortie de fonds"),
    ("view_cancelled_financial_operations", "Voir les opérations financières annulées"),
]


def upgrade() -> None:
    op.add_column("encaissements", sa.Column("statut_operation", sa.String(length=20), nullable=False, server_default="ACTIVE"))
    op.add_column("encaissements", sa.Column("motif_annulation", sa.Text(), nullable=True))
    op.add_column("encaissements", sa.Column("annulee_le", sa.DateTime(timezone=True), nullable=True))
    op.add_column("encaissements", sa.Column("annulee_par_id", sa.UUID(), nullable=True))
    op.add_column("encaissements", sa.Column("annulation_ip", sa.String(length=64), nullable=True))
    op.add_column("encaissements", sa.Column("ancien_statut_operation", sa.String(length=20), nullable=True))
    op.create_index("ix_encaissements_statut_operation", "encaissements", ["statut_operation"])
    op.create_foreign_key(
        "fk_encaissements_annulee_par",
        "encaissements",
        "users",
        ["annulee_par_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute("UPDATE encaissements SET statut_operation = 'ACTIVE' WHERE statut_operation IS NULL")
    op.alter_column("encaissements", "statut_operation", server_default=None)

    op.add_column("sorties_fonds", sa.Column("annulee_par_id", sa.UUID(), nullable=True))
    op.add_column("sorties_fonds", sa.Column("annulation_ip", sa.String(length=64), nullable=True))
    op.add_column("sorties_fonds", sa.Column("ancien_statut", sa.String(length=20), nullable=True))
    op.create_foreign_key(
        "fk_sorties_fonds_annulee_par",
        "sorties_fonds",
        "users",
        ["annulee_par_id"],
        ["id"],
        ondelete="SET NULL",
    )

    values = ",\n".join(
        f"('{code}', '{description}', NOW())" for code, description in PERMISSIONS
    )
    op.execute(
        f"""
        INSERT INTO permissions (code, description, created_at)
        VALUES
        {values}
        ON CONFLICT (code) DO UPDATE
        SET description = EXCLUDED.description;
        """
    )


def downgrade() -> None:
    codes = ", ".join(f"'{code}'" for code, _ in PERMISSIONS)
    op.execute(
        f"""
        DELETE FROM role_permissions
        WHERE permission_id IN (
            SELECT id FROM permissions WHERE code IN ({codes})
        );
        """
    )
    op.execute(f"DELETE FROM permissions WHERE code IN ({codes});")

    op.drop_constraint("fk_sorties_fonds_annulee_par", "sorties_fonds", type_="foreignkey")
    op.drop_column("sorties_fonds", "ancien_statut")
    op.drop_column("sorties_fonds", "annulation_ip")
    op.drop_column("sorties_fonds", "annulee_par_id")

    op.drop_constraint("fk_encaissements_annulee_par", "encaissements", type_="foreignkey")
    op.drop_index("ix_encaissements_statut_operation", table_name="encaissements")
    op.drop_column("encaissements", "ancien_statut_operation")
    op.drop_column("encaissements", "annulation_ip")
    op.drop_column("encaissements", "annulee_par_id")
    op.drop_column("encaissements", "annulee_le")
    op.drop_column("encaissements", "motif_annulation")
    op.drop_column("encaissements", "statut_operation")
