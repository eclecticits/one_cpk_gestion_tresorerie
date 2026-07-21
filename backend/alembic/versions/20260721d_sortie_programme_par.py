"""Traçabilité du programmeur d'une sortie directe.

Ajoute sorties_fonds.programme_par_id : la personne qui a programmé la sortie
directe (le « demandeur »), distincte du caissier (created_by) qui exécute le
paiement. Alimenté depuis l'ordre de décaissement à l'exécution.

Revision ID: 20260721d_sortie_programme_par
Revises: 20260721c_ordre_service_lignes
Create Date: 2026-07-21
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "20260721d_sortie_programme_par"
down_revision = "20260721c_ordre_service_lignes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sorties_fonds",
        sa.Column("programme_par_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_sorties_fonds_programme_par_id", "sorties_fonds", ["programme_par_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_sorties_fonds_programme_par_id", table_name="sorties_fonds")
    op.drop_column("sorties_fonds", "programme_par_id")
