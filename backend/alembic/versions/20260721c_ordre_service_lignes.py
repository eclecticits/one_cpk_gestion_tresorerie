"""Sortie directe programmée « type réquisition » : service + lignes budget.

Ajoute à ordres_decaissement :
- service_id (FK services, nullable) : service/commission responsable.
- lignes (JSONB, nullable) : lignes budgétaires (postes) définies en amont.

Revision ID: 20260721c_ordre_service_lignes
Revises: 20260721b_requisition_devise
Create Date: 2026-07-21
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "20260721c_ordre_service_lignes"
down_revision = "20260721b_requisition_devise"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ordres_decaissement",
        sa.Column("service_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "ordres_decaissement",
        sa.Column("lignes", JSONB(), nullable=True),
    )
    op.create_index(
        "ix_ordres_decaissement_service_id", "ordres_decaissement", ["service_id"]
    )
    op.create_foreign_key(
        "fk_ordres_decaissement_service_id",
        "ordres_decaissement",
        "services",
        ["service_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_ordres_decaissement_service_id", "ordres_decaissement", type_="foreignkey")
    op.drop_index("ix_ordres_decaissement_service_id", table_name="ordres_decaissement")
    op.drop_column("ordres_decaissement", "lignes")
    op.drop_column("ordres_decaissement", "service_id")
