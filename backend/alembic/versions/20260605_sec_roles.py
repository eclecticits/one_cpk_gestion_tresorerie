"""seed secretariat role templates

Revision ID: 20260605_sec_roles
Revises: 20260604_sec_documents
Create Date: 2026-06-05
"""

from __future__ import annotations

from alembic import op

from app.modules.secretariat.permissions import SECRETARIAT_ROLE_TEMPLATES


revision = "20260605_sec_roles"
down_revision = "20260604_sec_documents"
branch_labels = None
depends_on = None


def _escape(value: str) -> str:
    return value.replace("'", "''")


def upgrade() -> None:
    for role_code, template in SECRETARIAT_ROLE_TEMPLATES.items():
        label = _escape(str(template["label"]))
        description = _escape(f"Secrétariat - {template['label']}")
        op.execute(
            f"""
            INSERT INTO roles (code, label, description, created_at)
            VALUES ('{_escape(role_code)}', '{label}', '{description}', NOW())
            ON CONFLICT (code) DO UPDATE
            SET label = EXCLUDED.label,
                description = EXCLUDED.description;
            """
        )

        permissions = template["permissions"]
        codes = ", ".join(f"'{_escape(code)}'" for code in permissions)
        op.execute(
            f"""
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT r.id, p.id
            FROM roles r
            JOIN permissions p ON p.code IN ({codes})
            WHERE r.code = '{_escape(role_code)}'
            ON CONFLICT DO NOTHING;
            """
        )


def downgrade() -> None:
    role_codes = ", ".join(f"'{_escape(code)}'" for code in SECRETARIAT_ROLE_TEMPLATES.keys())
    op.execute(
        f"""
        DELETE FROM role_permissions
        WHERE role_id IN (SELECT id FROM roles WHERE code IN ({role_codes}));
        """
    )
    op.execute(
        f"""
        DELETE FROM roles
        WHERE code IN ({role_codes})
          AND id NOT IN (SELECT DISTINCT role_id FROM users WHERE role_id IS NOT NULL);
        """
    )
