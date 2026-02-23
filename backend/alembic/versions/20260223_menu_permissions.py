"""add menu permissions for matrix

Revision ID: 20260223_menu_permissions
Revises: f1b0b5ff77bb
Create Date: 2026-02-23
"""

from alembic import op

revision = "20260223_menu_permissions"
down_revision = "f1b0b5ff77bb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO permissions (code, description, created_at)
        VALUES
          ('menu_requisitions', 'Accès au module Réquisitions', NOW()),
          ('menu_services', 'Accès aux commissions (Services)', NOW()),
          ('menu_mon_espace', 'Accès au portail Commission (Mon espace)', NOW())
        ON CONFLICT (code) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM permissions
        WHERE code IN ('menu_requisitions', 'menu_services', 'menu_mon_espace');
        """
    )
