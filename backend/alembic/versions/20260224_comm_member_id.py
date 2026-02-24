"""add email and matricule to commission members

Revision ID: 20260224_comm_member_id
Revises: 20260224_req_status_2step
Create Date: 2026-02-24
"""

from alembic import op
import sqlalchemy as sa


revision = "20260224_comm_member_id"
down_revision = "20260224_req_status_2step"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("commission_members", sa.Column("email", sa.String(length=255), nullable=True))
    op.add_column("commission_members", sa.Column("matricule", sa.String(length=50), nullable=True))
    op.create_index("ix_commission_members_email", "commission_members", ["email"])
    op.create_index("ix_commission_members_matricule", "commission_members", ["matricule"])


def downgrade() -> None:
    op.drop_index("ix_commission_members_matricule", table_name="commission_members")
    op.drop_index("ix_commission_members_email", table_name="commission_members")
    op.drop_column("commission_members", "matricule")
    op.drop_column("commission_members", "email")
