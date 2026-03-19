"""unique email per organisation

Revision ID: 20260320_users_email_org_unique
Revises: 20260320_std_class
Create Date: 2026-03-19
"""

from alembic import op
from sqlalchemy import inspect


revision = "20260320_users_email_org_unique"
down_revision = "20260320_std_class"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    for constraint in inspector.get_unique_constraints("users"):
        cols = set(constraint.get("column_names") or [])
        if cols == {"email"}:
            op.drop_constraint(constraint["name"], "users", type_="unique")
            break
    op.create_unique_constraint("uq_users_org_email", "users", ["organisation_id", "email"])


def downgrade() -> None:
    op.drop_constraint("uq_users_org_email", "users", type_="unique")
    op.create_unique_constraint("uq_users_email", "users", ["email"])
