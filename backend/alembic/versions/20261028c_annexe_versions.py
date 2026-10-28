"""versionnement et audit des pièces de réunion

Revision ID: 20261028c_annexe_versions
Revises: 20261028b_projet_tarif_encaisse
Create Date: 2026-10-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261028c_annexe_versions"
down_revision = "20261028b_projet_tarif_encaisse"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("requisition_annexes", sa.Column("document_kind", sa.String(50), nullable=True))
    op.add_column("requisition_annexes", sa.Column("document_version", sa.Integer(), nullable=True))
    op.add_column(
        "requisition_annexes",
        sa.Column(
            "supersedes_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("requisition_annexes.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "requisition_annexes",
        sa.Column(
            "uploaded_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("requisition_annexes", sa.Column("document_source", sa.String(40), nullable=True))
    op.add_column("requisition_annexes", sa.Column("content_sha256", sa.String(64), nullable=True))
    op.create_index("ix_requisition_annexes_document_kind", "requisition_annexes", ["document_kind"])
    op.create_index("ix_requisition_annexes_supersedes_id", "requisition_annexes", ["supersedes_id"])
    op.create_index("ix_requisition_annexes_uploaded_by", "requisition_annexes", ["uploaded_by"])
    op.create_unique_constraint(
        "uq_req_annexe_kind_version",
        "requisition_annexes",
        ["requisition_id", "document_kind", "document_version"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_req_annexe_kind_version", "requisition_annexes", type_="unique")
    op.drop_index("ix_requisition_annexes_uploaded_by", table_name="requisition_annexes")
    op.drop_index("ix_requisition_annexes_supersedes_id", table_name="requisition_annexes")
    op.drop_index("ix_requisition_annexes_document_kind", table_name="requisition_annexes")
    op.drop_column("requisition_annexes", "content_sha256")
    op.drop_column("requisition_annexes", "document_source")
    op.drop_column("requisition_annexes", "uploaded_by")
    op.drop_column("requisition_annexes", "supersedes_id")
    op.drop_column("requisition_annexes", "document_version")
    op.drop_column("requisition_annexes", "document_kind")
