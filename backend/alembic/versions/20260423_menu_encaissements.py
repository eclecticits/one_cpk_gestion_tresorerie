"""add encaissements menu permission

Revision ID: 20260423_menu_encaissements
Revises: 20260422_docseq_service_fix
Create Date: 2026-04-23
"""

from __future__ import annotations

from alembic import op


revision = "20260423_menu_encaissements"
down_revision = "20260422_docseq_service_fix"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO permissions (code, description, created_at)
        VALUES ('menu_encaissements', 'Accès au module Encaissements', NOW())
        ON CONFLICT (code) DO UPDATE
        SET description = EXCLUDED.description;
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT DISTINCT rp.role_id, enc_perm.id
        FROM role_permissions rp
        JOIN permissions report_perm
          ON report_perm.id = rp.permission_id
         AND report_perm.code = 'can_view_reports'
        JOIN permissions enc_perm
          ON enc_perm.code = 'menu_encaissements'
        ON CONFLICT DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE permission_id = (
            SELECT id FROM permissions WHERE code = 'menu_encaissements'
        );
        """
    )
    op.execute("DELETE FROM permissions WHERE code = 'menu_encaissements';")
