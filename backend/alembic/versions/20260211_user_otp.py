"""add otp fields to users

Revision ID: 20260211_user_otp
Revises: 678847c0d8e0
Create Date: 2026-02-11
"""

from alembic import op
import sqlalchemy as sa


revision = "20260211_user_otp"
down_revision = "678847c0d8e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_first_login", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "users",
        sa.Column("is_email_verified", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column("users", sa.Column("otp_code", sa.String(length=20), nullable=True))
    op.add_column("users", sa.Column("otp_created_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users",
        sa.Column("otp_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )

    op.execute("UPDATE users SET is_first_login = false WHERE is_first_login IS NULL")
    op.execute("UPDATE users SET is_email_verified = true WHERE is_email_verified IS NULL")

    op.alter_column("users", "is_first_login", server_default=None)
    op.alter_column("users", "is_email_verified", server_default=None)
    op.alter_column("users", "otp_attempts", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "otp_attempts")
    op.drop_column("users", "otp_created_at")
    op.drop_column("users", "otp_code")
    op.drop_column("users", "is_email_verified")
    op.drop_column("users", "is_first_login")
