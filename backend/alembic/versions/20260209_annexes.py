"""add requisition annexes and signataires

Revision ID: 20260209_annexes
Revises: 20260206_snapshots
Create Date: 2026-02-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260209_annexes"
down_revision = "20260206_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "requisition_annexes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("requisition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=100), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("upload_date", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["requisition_id"], ["requisitions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_requisition_annexes_requisition_id", "requisition_annexes", ["requisition_id"], unique=True)

    with op.batch_alter_table("requisitions") as batch:
        batch.add_column(sa.Column("signataire_g_label", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("signataire_g_nom", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("signataire_d_label", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("signataire_d_nom", sa.String(length=200), nullable=True))

    with op.batch_alter_table("remboursements_transport") as batch:
        batch.add_column(sa.Column("signataire_g_label", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("signataire_g_nom", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("signataire_d_label", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("signataire_d_nom", sa.String(length=200), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("remboursements_transport") as batch:
        batch.drop_column("signataire_d_nom")
        batch.drop_column("signataire_d_label")
        batch.drop_column("signataire_g_nom")
        batch.drop_column("signataire_g_label")

    with op.batch_alter_table("requisitions") as batch:
        batch.drop_column("signataire_d_nom")
        batch.drop_column("signataire_d_label")
        batch.drop_column("signataire_g_nom")
        batch.drop_column("signataire_g_label")

    op.drop_index("ix_requisition_annexes_requisition_id", table_name="requisition_annexes")
    op.drop_table("requisition_annexes")
