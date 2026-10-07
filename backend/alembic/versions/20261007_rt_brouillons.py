"""brouillons de remboursement de transport

Revision ID: 20261007_rt_brouillons
Revises: 20261007_sortie_autorise_par
Create Date: 2026-10-07

Un remboursement de transport se prepare avant la reunion (liste de presence
imprimee) et se complete apres (presences, montants). Le brouillon vit dans
sa propre table : il ne consomme ni numero REM ni requisition, qui ne sont
crees qu'a la finalisation.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20261007_rt_brouillons"
down_revision = "20261007_sortie_autorise_par"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "remboursements_transport_brouillons",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "service_id",
            sa.Integer(),
            sa.ForeignKey("services.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("contenu", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_remboursements_transport_brouillons_organisation_id",
        "remboursements_transport_brouillons",
        ["organisation_id"],
    )
    op.create_index(
        "ix_remboursements_transport_brouillons_service_id",
        "remboursements_transport_brouillons",
        ["service_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_remboursements_transport_brouillons_service_id", table_name="remboursements_transport_brouillons")
    op.drop_index("ix_remboursements_transport_brouillons_organisation_id", table_name="remboursements_transport_brouillons")
    op.drop_table("remboursements_transport_brouillons")
