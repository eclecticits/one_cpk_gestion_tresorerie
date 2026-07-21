"""Sortie directe (max 100$) : privilège dédié can_direct_disbursement

La sortie directe sans réquisition n'est plus accessible à la caissière par
défaut : elle requiert le rôle admin ou le privilège can_direct_disbursement,
attribuable à un utilisateur via la gestion des rôles. Aucun rôle ne le reçoit
automatiquement.

Revision ID: 20260719_sortie_directe_priv
Revises: 20260719_decaissement_progressif
Create Date: 2026-07-19
"""

from __future__ import annotations

from alembic import op


revision = "20260719_sortie_directe_priv"
down_revision = "20260719_decaissement_progressif"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO permissions (code, description, created_at)
        VALUES (
            'can_direct_disbursement',
            'Effectuer une sortie directe sans réquisition (plafond 100 USD)',
            NOW()
        )
        ON CONFLICT (code) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE permission_id IN (SELECT id FROM permissions WHERE code = 'can_direct_disbursement');
        """
    )
    op.execute("DELETE FROM permissions WHERE code = 'can_direct_disbursement';")
