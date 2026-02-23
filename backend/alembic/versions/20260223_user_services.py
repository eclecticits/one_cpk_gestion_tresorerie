"""add user_services m2m

Revision ID: 20260223_user_services
Revises: 20260223_menu_permissions
Create Date: 2026-02-23
"""

from alembic import op
import sqlalchemy as sa

revision = "20260223_user_services"
down_revision = "20260223_menu_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_services",
        sa.Column("user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("service_id", sa.Integer(), sa.ForeignKey("services.id", ondelete="CASCADE"), primary_key=True),
    )

    # Backfill from legacy users.service_id
    op.execute(
        """
        INSERT INTO user_services (user_id, service_id)
        SELECT id, service_id
        FROM users
        WHERE service_id IS NOT NULL
        ON CONFLICT DO NOTHING;
        """
    )


def downgrade() -> None:
    op.drop_table("user_services")
