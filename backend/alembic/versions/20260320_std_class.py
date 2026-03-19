"""Add standard classifications memory table.

Revision ID: 20260320_std_class
Revises: 20260313_saas_alignment
Create Date: 2026-03-20 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260320_std_class"
down_revision = "20260313_saas_alignment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "standard_classifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("raw_label", sa.String(length=255), nullable=False),
        sa.Column("assigned_account", sa.String(length=10), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_used", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("organisation_id", "raw_label", name="uq_std_class_org_label"),
    )
    op.create_index("ix_standard_classifications_org", "standard_classifications", ["organisation_id"])
    op.create_index("ix_standard_classifications_label", "standard_classifications", ["raw_label"])


def downgrade() -> None:
    op.drop_index("ix_standard_classifications_label", table_name="standard_classifications")
    op.drop_index("ix_standard_classifications_org", table_name="standard_classifications")
    op.drop_table("standard_classifications")
