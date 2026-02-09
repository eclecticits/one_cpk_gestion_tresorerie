"""add document sequences and reference numbers

Revision ID: 20260209_document_sequences
Revises: 20260209_annexes
Create Date: 2026-02-09
"""

from alembic import op
import sqlalchemy as sa


revision = "20260209_document_sequences"
down_revision = "20260209_annexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_sequences",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("doc_type", sa.String(length=10), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("counter", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("doc_type", "year", name="uq_doc_type_year"),
    )

    with op.batch_alter_table("requisitions") as batch:
        batch.add_column(sa.Column("reference_numero", sa.String(length=50), nullable=True))
        batch.create_index("uq_requisitions_reference_numero", ["reference_numero"], unique=True)

    with op.batch_alter_table("remboursements_transport") as batch:
        batch.add_column(sa.Column("reference_numero", sa.String(length=50), nullable=True))
        batch.create_index("uq_remboursements_transport_reference_numero", ["reference_numero"], unique=True)

    with op.batch_alter_table("sorties_fonds") as batch:
        batch.add_column(sa.Column("reference_numero", sa.String(length=50), nullable=True))
        batch.create_index("uq_sorties_fonds_reference_numero", ["reference_numero"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("sorties_fonds") as batch:
        batch.drop_index("uq_sorties_fonds_reference_numero")
        batch.drop_column("reference_numero")

    with op.batch_alter_table("remboursements_transport") as batch:
        batch.drop_index("uq_remboursements_transport_reference_numero")
        batch.drop_column("reference_numero")

    with op.batch_alter_table("requisitions") as batch:
        batch.drop_index("uq_requisitions_reference_numero")
        batch.drop_column("reference_numero")

    op.drop_table("document_sequences")
