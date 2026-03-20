"""Scope banques by organisation.

Revision ID: 20260321_banques_tenant_scope
Revises: 20260320_users_email_org_unique
Create Date: 2026-03-21
"""

from alembic import op
import sqlalchemy as sa


revision = "20260321_banques_tenant_scope"
down_revision = "20260320_users_email_org_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("banques", sa.Column("organisation_id", sa.Integer(), nullable=True))
    op.create_index("ix_banques_organisation_id", "banques", ["organisation_id"])
    op.create_foreign_key(
        "fk_banques_organisation_id",
        "banques",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.execute("UPDATE banques SET organisation_id = 1 WHERE organisation_id IS NULL")
    op.drop_constraint("banques_nom_key", "banques", type_="unique")
    op.create_unique_constraint("uq_banques_org_nom", "banques", ["organisation_id", "nom"])
    op.alter_column("banques", "organisation_id", nullable=False)


def downgrade() -> None:
    op.alter_column("banques", "organisation_id", nullable=True)
    op.drop_constraint("uq_banques_org_nom", "banques", type_="unique")
    op.create_unique_constraint("banques_nom_key", "banques", ["nom"])
    op.drop_constraint("fk_banques_organisation_id", "banques", type_="foreignkey")
    op.drop_index("ix_banques_organisation_id", table_name="banques")
    op.drop_column("banques", "organisation_id")
