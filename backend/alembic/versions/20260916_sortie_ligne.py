"""Une sortie de fonds peut dire quelle ligne de réquisition elle a payée.

Sans ce lien, le décaissement ne connaît que la réquisition. Tant qu'une
réquisition n'a qu'une ligne, cela suffit ; dès qu'elle en a plusieurs, plus
rien ne dit quelle part du paiement revient à quel poste budgétaire, et corriger
l'imputation d'une seule ligne laisse son réalisé sur l'ancien poste.

La colonne est facultative, et le restera. Les sorties déjà en base gardent
`NULL` : aucune reprise ne peut deviner rétroactivement quelle ligne un
décaissement a payée, et en inventer une serait pire que de l'ignorer. `NULL` a
donc un sens plein — « cette sortie couvre la réquisition entière » — et la
ré-imputation partielle répartit alors son imputation au prorata des montants.

Revision ID: 20260916_sortie_ligne
Revises: 20260916_jonction
Create Date: 2026-09-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision = "20260916_sortie_ligne"
down_revision = "20260916_jonction"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sorties_fonds",
        sa.Column("ligne_requisition_id", UUID(as_uuid=True), nullable=True),
    )
    # ON DELETE SET NULL : supprimer une ligne ne doit pas retenir un
    # décaissement déjà passé. La sortie retombe alors sur le sens « couvre la
    # réquisition entière », qui reste exact.
    op.create_foreign_key(
        "fk_sorties_fonds_ligne_requisition",
        "sorties_fonds",
        "lignes_requisition",
        ["ligne_requisition_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_sorties_fonds_ligne_requisition_id",
        "sorties_fonds",
        ["ligne_requisition_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_sorties_fonds_ligne_requisition_id", table_name="sorties_fonds")
    op.drop_constraint("fk_sorties_fonds_ligne_requisition", "sorties_fonds", type_="foreignkey")
    op.drop_column("sorties_fonds", "ligne_requisition_id")
