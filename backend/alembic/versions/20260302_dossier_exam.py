"""add dossier requisition and examen fields

Revision ID: 20260302_dossier_exam
Revises: 0ab0d11a512f
Create Date: 2026-03-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260302_dossier_exam"
down_revision = "0ab0d11a512f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dossiers_requisition",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("reference", sa.String(length=60), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("commentaires_examen", sa.Text(), nullable=True),
        sa.Column("created_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference"),
    )
    op.create_index("ix_dossiers_requisition_reference", "dossiers_requisition", ["reference"], unique=True)
    op.create_index("ix_dossiers_requisition_status", "dossiers_requisition", ["status"], unique=False)
    op.create_index("ix_dossiers_requisition_created_by", "dossiers_requisition", ["created_by"], unique=False)

    op.add_column(
        "requisitions",
        sa.Column("dossier_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "requisitions",
        sa.Column("examen_status", sa.String(length=30), nullable=False, server_default="NON_EXAMINE"),
    )
    op.add_column("requisitions", sa.Column("examen_commentaire", sa.Text(), nullable=True))
    op.add_column("requisitions", sa.Column("examen_par", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("requisitions", sa.Column("examen_le", sa.DateTime(timezone=True), nullable=True))

    op.create_index("ix_requisitions_dossier_id", "requisitions", ["dossier_id"], unique=False)
    op.create_index("ix_requisitions_examen_status", "requisitions", ["examen_status"], unique=False)
    op.create_foreign_key(
        "fk_requisitions_dossier_id",
        "requisitions",
        "dossiers_requisition",
        ["dossier_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_requisitions_dossier_id", "requisitions", type_="foreignkey")
    op.drop_index("ix_requisitions_examen_status", table_name="requisitions")
    op.drop_index("ix_requisitions_dossier_id", table_name="requisitions")
    op.drop_column("requisitions", "examen_le")
    op.drop_column("requisitions", "examen_par")
    op.drop_column("requisitions", "examen_commentaire")
    op.drop_column("requisitions", "examen_status")
    op.drop_column("requisitions", "dossier_id")

    op.drop_index("ix_dossiers_requisition_created_by", table_name="dossiers_requisition")
    op.drop_index("ix_dossiers_requisition_status", table_name="dossiers_requisition")
    op.drop_index("ix_dossiers_requisition_reference", table_name="dossiers_requisition")
    op.drop_table("dossiers_requisition")
