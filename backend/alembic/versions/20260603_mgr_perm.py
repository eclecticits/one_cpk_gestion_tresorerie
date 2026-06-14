"""add secretariat manager permissions

Revision ID: 20260603_mgr_perm
Revises: 20260603_gdraft
Create Date: 2026-06-03
"""

from __future__ import annotations

from alembic import op
from app.modules.secretariat.permissions import (
    SECRETARIAT_MANAGER_PERMISSION_CODES,
    SECRETARIAT_PERMISSION_DESCRIPTIONS,
)


revision = "20260603_mgr_perm"
down_revision = "20260603_gdraft"
branch_labels = None
depends_on = None


def upgrade() -> None:
    values = ",\n".join(
        f"('{code}', '{SECRETARIAT_PERMISSION_DESCRIPTIONS[code].replace(chr(39), chr(39) + chr(39))}', NOW())"
        for code in SECRETARIAT_MANAGER_PERMISSION_CODES
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
    codes = ", ".join(f"'{code}'" for code in SECRETARIAT_MANAGER_PERMISSION_CODES)
    op.execute(
        f"""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r
        JOIN permissions p ON p.code IN ({codes})
        WHERE r.code = 'admin'
        ON CONFLICT DO NOTHING;
        """
    )


def downgrade() -> None:
    codes = ", ".join(f"'{code}'" for code in SECRETARIAT_MANAGER_PERMISSION_CODES)
    op.execute(f"DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code IN ({codes}));")
    op.execute(f"DELETE FROM permissions WHERE code IN ({codes});")
