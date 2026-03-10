"""Add tenant to system settings and clotures.

Revision ID: 20260310_tenant_settings
Revises: 20260310_multi_tenant_orgs
Create Date: 2026-03-10
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260310_tenant_settings"
down_revision = "20260310_multi_tenant_orgs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("system_settings", sa.Column("organisation_id", sa.Integer(), nullable=True))
    op.add_column("clotures", sa.Column("organisation_id", sa.Integer(), nullable=True))

    op.create_index("ix_system_settings_organisation_id", "system_settings", ["organisation_id"])
    op.create_index("ix_clotures_organisation_id", "clotures", ["organisation_id"])

    op.create_foreign_key(
        "fk_system_settings_organisation_id",
        "system_settings",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_clotures_organisation_id",
        "clotures",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.execute("UPDATE system_settings SET organisation_id = 1 WHERE organisation_id IS NULL")
    op.execute("UPDATE clotures SET organisation_id = 1 WHERE organisation_id IS NULL")

    op.alter_column("system_settings", "organisation_id", nullable=False)
    op.alter_column("clotures", "organisation_id", nullable=False)


def downgrade() -> None:
    op.drop_constraint("fk_clotures_organisation_id", "clotures", type_="foreignkey")
    op.drop_constraint("fk_system_settings_organisation_id", "system_settings", type_="foreignkey")

    op.drop_index("ix_clotures_organisation_id", table_name="clotures")
    op.drop_index("ix_system_settings_organisation_id", table_name="system_settings")

    op.drop_column("clotures", "organisation_id")
    op.drop_column("system_settings", "organisation_id")
