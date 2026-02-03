"""add print settings assets and format options

Revision ID: 0009_print_settings_assets
Revises: 0008_sorties_fonds_constraints
Create Date: 2026-01-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0009_print_settings_assets"
down_revision = "0008_sorties_fonds_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "print_settings",
        sa.Column("logo_url", sa.String(length=500), nullable=False, server_default=""),
    )
    op.add_column(
        "print_settings",
        sa.Column("stamp_url", sa.String(length=500), nullable=False, server_default=""),
    )
    op.add_column(
        "print_settings",
        sa.Column("signature_name", sa.String(length=200), nullable=False, server_default=""),
    )
    op.add_column(
        "print_settings",
        sa.Column("signature_title", sa.String(length=200), nullable=False, server_default=""),
    )
    op.add_column(
        "print_settings",
        sa.Column("paper_format", sa.String(length=3), nullable=False, server_default="A5"),
    )
    op.add_column(
        "print_settings",
        sa.Column("compact_header", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("print_settings", "compact_header")
    op.drop_column("print_settings", "paper_format")
    op.drop_column("print_settings", "signature_title")
    op.drop_column("print_settings", "signature_name")
    op.drop_column("print_settings", "stamp_url")
    op.drop_column("print_settings", "logo_url")
