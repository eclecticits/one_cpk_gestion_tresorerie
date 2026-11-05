"""Notes de débit : actualisation par réimport et report des avances

Revision ID: 20261105_avance_reportee
Revises: 20261104_compte_volet

Quand une note de débit est actualisée à la baisse sous ce que le membre a déjà
payé, le surplus n'est pas rendu : il règle sa note suivante. L'argent ne
quitte pas la trésorerie, il est déplacé d'un versement à l'autre, à la même
date et sur la même caisse ou le même compte. `avance_source_id` relie le
versement de destination à celui d'où l'argent vient : l'annuler le rend à ce
versement d'origine, jamais à la caisse.

`notes_debit_imports.nb_notes_actualisees` compte, pour un import, les notes
déjà en base dont il a remplacé une famille de créances.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20261105_avance_reportee"
down_revision = "20261104_compte_volet"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payment_history",
        sa.Column("avance_source_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_payment_history_avance_source",
        "payment_history",
        "payment_history",
        ["avance_source_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_payment_history_avance_source_id", "payment_history", ["avance_source_id"])
    op.add_column(
        "notes_debit_imports",
        sa.Column("nb_notes_actualisees", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("notes_debit_imports", "nb_notes_actualisees")
    op.drop_index("ix_payment_history_avance_source_id", table_name="payment_history")
    op.drop_constraint("fk_payment_history_avance_source", "payment_history", type_="foreignkey")
    op.drop_column("payment_history", "avance_source_id")
