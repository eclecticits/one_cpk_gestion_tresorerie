"""add service responsable

Revision ID: 20260223_service_responsable
Revises: 20260223_user_services
Create Date: 2026-02-23
"""

from alembic import op
import sqlalchemy as sa

revision = "20260223_service_responsable"
down_revision = "20260223_user_services"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("services", sa.Column("responsable_id", sa.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_services_responsable_id",
        "services",
        "users",
        ["responsable_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_services_responsable_id", "services", type_="foreignkey")
    op.drop_column("services", "responsable_id")
