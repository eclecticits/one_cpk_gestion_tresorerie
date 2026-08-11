"""Date metier de la requisition, distincte de created_at

`created_at` est l'horodatage technique de l'enregistrement : il ne permet pas
d'antidater une requisition papier saisie plus tard, et son fuseau UTC peut
decaler le jour affiche. On ajoute une vraie date metier, initialisee sur
created_at pour l'existant afin qu'aucun etat ne change a la migration.

Revision ID: 20260808_req_date
Revises: 20260807_regul_caisse
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260808_req_date"
down_revision = "20260807_regul_caisse"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "requisitions",
        sa.Column("date_requisition", sa.DateTime(timezone=True), nullable=True),
    )
    # Reprise : l'existant conserve exactement la date qu'il affichait jusqu'ici.
    op.execute("UPDATE requisitions SET date_requisition = created_at")
    op.create_index(
        "ix_requisitions_date_requisition", "requisitions", ["date_requisition"]
    )


def downgrade() -> None:
    op.drop_index("ix_requisitions_date_requisition", table_name="requisitions")
    op.drop_column("requisitions", "date_requisition")
