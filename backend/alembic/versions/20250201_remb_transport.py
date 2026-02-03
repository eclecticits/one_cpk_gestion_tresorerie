"""add remboursements transport tables

Revision ID: 20250201_remb_transport
Revises: 0003_experts_encaissements
Create Date: 2026-01-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20250201_remb_transport"
down_revision = "0003_experts_encaissements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "remboursements_transport",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("numero_remboursement", sa.String(length=50), nullable=False, unique=True),
        sa.Column("instance", sa.String(length=100), nullable=False),
        sa.Column("type_reunion", sa.String(length=30), nullable=False),
        sa.Column("nature_reunion", sa.String(length=200), nullable=False),
        sa.Column("nature_travail", postgresql.JSONB, nullable=True),
        sa.Column("lieu", sa.String(length=200), nullable=False),
        sa.Column("date_reunion", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heure_debut", sa.String(length=20), nullable=True),
        sa.Column("heure_fin", sa.String(length=20), nullable=True),
        sa.Column("montant_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("requisition_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "participants_transport",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("remboursement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("nom", sa.String(length=200), nullable=False),
        sa.Column("titre_fonction", sa.String(length=200), nullable=False),
        sa.Column("montant", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("type_participant", sa.String(length=20), nullable=False),
        sa.Column("expert_comptable_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["remboursement_id"], ["remboursements_transport.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["expert_comptable_id"], ["experts_comptables.id"], ondelete="SET NULL"),
    )


def downgrade() -> None:
    op.drop_table("participants_transport")
    op.drop_table("remboursements_transport")
