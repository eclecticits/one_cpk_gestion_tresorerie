"""Ajoute les pièces justificatives tracées des encaissements."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260804_encaissement_pieces"
down_revision = "20260804_projets_activites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "encaissement_pieces_jointes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("encaissement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("encaissements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("stored_path", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=False, server_default="application/octet-stream"),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_encaissement_pieces_jointes_organisation_id", "encaissement_pieces_jointes", ["organisation_id"])
    op.create_index("ix_encaissement_pieces_jointes_encaissement_id", "encaissement_pieces_jointes", ["encaissement_id"])


def downgrade() -> None:
    op.drop_index("ix_encaissement_pieces_jointes_encaissement_id", table_name="encaissement_pieces_jointes")
    op.drop_index("ix_encaissement_pieces_jointes_organisation_id", table_name="encaissement_pieces_jointes")
    op.drop_table("encaissement_pieces_jointes")
