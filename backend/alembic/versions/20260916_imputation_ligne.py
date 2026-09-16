"""L'impact budgétaire d'un paiement dit de quelle ligne il vient.

Le décaissement raisonnait par poste : une réquisition multi-postes produisait
une imputation par poste, et la part de chaque ligne à l'intérieur d'un poste
était perdue. Corriger l'imputation d'une seule ligne obligeait alors à
répartir le réalisé au prorata — juste en moyenne, faux dans le détail dès que
les lignes d'un même poste ne partent pas ensemble.

La ligne est portée par l'imputation, pas par la sortie de fonds. Une sortie est
une pièce de décaissement : elle est émise une fois, pour un montant, et peut
couvrir plusieurs lignes ; lui attribuer une ligne unique serait faux. Une
imputation, elle, est un enregistrement de budget, déjà découpé par poste : la
découper par ligne ne change pas sa nature, elle la précise.

La colonne reste facultative. Les imputations déjà en base gardent `NULL`, et ce
`NULL` a son sens plein — « on ne sait pas quelle ligne » —, que la
ré-imputation traite en répartissant au prorata du poste. Aucune reprise ne peut
deviner après coup ce que le circuit n'a jamais enregistré.

Revision ID: 20260916_imputation_ligne
Revises: 20260916_sortie_ligne
Create Date: 2026-09-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision = "20260916_imputation_ligne"
down_revision = "20260916_sortie_ligne"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mouvement_budget_imputations",
        sa.Column("ligne_requisition_id", UUID(as_uuid=True), nullable=True),
    )
    # ON DELETE SET NULL : supprimer une ligne ne doit pas retenir un impact
    # budgétaire déjà figé. L'imputation retombe sur « ligne inconnue », qui
    # reste exact.
    op.create_foreign_key(
        "fk_imputations_ligne_requisition",
        "mouvement_budget_imputations",
        "lignes_requisition",
        ["ligne_requisition_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_imputations_ligne_requisition_id",
        "mouvement_budget_imputations",
        ["ligne_requisition_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_imputations_ligne_requisition_id", table_name="mouvement_budget_imputations")
    op.drop_constraint("fk_imputations_ligne_requisition", "mouvement_budget_imputations", type_="foreignkey")
    op.drop_column("mouvement_budget_imputations", "ligne_requisition_id")
