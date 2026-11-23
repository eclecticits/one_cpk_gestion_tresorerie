"""Tableau : réglages rangés par conseil, à part des imports

Revision ID: 20261123_tableau_reglages
Revises: 20261114_cotis_attestations

Les réglages vivaient dans `metadata_json` de chaque import. Un import de
fichier source arrivait sans eux et, étant le plus récent, faisait revenir la
page et la Base aux valeurs initiales. Table `tableau_reglages_conseil` : un
jeu par conseil, valable pour tous les exercices, repris du dernier import qui
en portait. Les anciennes copies dans les imports restent, inertes.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20261123_tableau_reglages"
down_revision = "20261114_cotis_attestations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tableau_reglages_conseil",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="CASCADE"),
                  nullable=False, unique=True),
        sa.Column("reglages", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("modifie_par", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    # Les derniers réglages enregistrés par chaque conseil, tous exercices
    # confondus : un import source plus récent, sans réglages, ne compte pas.
    op.execute(
        """
        INSERT INTO tableau_reglages_conseil (organisation_id, reglages, updated_at)
        SELECT DISTINCT ON (organisation_id)
               organisation_id, metadata_json -> 'reglages', updated_at
          FROM secretariat_tableau_imports
         WHERE jsonb_typeof(metadata_json -> 'reglages') = 'object'
           AND metadata_json -> 'reglages' <> '{}'::jsonb
         ORDER BY organisation_id, updated_at DESC, id DESC
        """
    )


def downgrade() -> None:
    op.drop_table("tableau_reglages_conseil")
