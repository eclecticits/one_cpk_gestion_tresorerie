"""à valoir sur les sorties directes programmées

Une avance « à valoir » — dépense faite pour une autre instance, qui la
rembourse — ne pouvait naître que d'une réquisition. La sortie directe la porte
désormais elle aussi : la case, l'instance qui doit rembourser et la note.

Revision ID: 20261029a_ordre_direct_a_valoir
Revises: 20261028d_numero_trigram
Create Date: 2026-10-29
"""

from alembic import op
import sqlalchemy as sa


revision = "20261029a_ordre_direct_a_valoir"
down_revision = "20261028d_numero_trigram"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ordres_decaissement",
        sa.Column("a_valoir", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("ordres_decaissement", sa.Column("instance_beneficiaire", sa.String(200), nullable=True))
    op.add_column("ordres_decaissement", sa.Column("notes_a_valoir", sa.Text(), nullable=True))
    # Même règle que la réquisition : une avance à valoir sans instance qui la
    # rembourse est une créance orpheline.
    op.create_check_constraint(
        "ck_ordres_decaissement_a_valoir_instance",
        "ordres_decaissement",
        "NOT a_valoir OR (instance_beneficiaire IS NOT NULL AND btrim(instance_beneficiaire) <> '')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_ordres_decaissement_a_valoir_instance", "ordres_decaissement", type_="check")
    op.drop_column("ordres_decaissement", "notes_a_valoir")
    op.drop_column("ordres_decaissement", "instance_beneficiaire")
    op.drop_column("ordres_decaissement", "a_valoir")
