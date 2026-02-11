"""drop legacy menu permissions tables

Revision ID: 20260211_drop_menu_permissions
Revises: 20260211_workflow_settings
Create Date: 2026-02-11
"""

from alembic import op

revision = "20260211_drop_menu_permissions"
down_revision = "20260211_workflow_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS role_menu_permissions;")
    op.execute("DROP TABLE IF EXISTS user_menu_permissions;")


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS role_menu_permissions (
            id SERIAL PRIMARY KEY,
            role VARCHAR(50) NOT NULL,
            menu_name VARCHAR(100) NOT NULL,
            can_access BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_menu_permissions (
            id SERIAL PRIMARY KEY,
            user_id UUID NOT NULL,
            menu_name VARCHAR(100) NOT NULL,
            can_access BOOLEAN DEFAULT TRUE,
            created_by UUID,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        );
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_role_menu_permissions_role_menu ON role_menu_permissions(role, menu_name);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_role_menu_permissions_role ON role_menu_permissions(role);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_role_menu_permissions_menu_name ON role_menu_permissions(menu_name);"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_menu_permissions_user_menu ON user_menu_permissions(user_id, menu_name);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_menu_permissions_user_id ON user_menu_permissions(user_id);"
    )
