"""Un article d'encaissement porte son poste

Revision ID: 20260917_art_poste
Revises: 20260917_enc_tarifs

Un encaissement n'imputait qu'un poste, choisi une fois pour toutes avant la
saisie des articles. Or un même reçu porte souvent des lignes de natures
différentes — une cotisation et des frais d'inscription ne tombent pas au même
endroit —, et les tarifs rendent ce mélange courant : chacun apporte son poste.

L'article porte donc son imputation, comme une ligne de réquisition porte la
sienne. Le poste de l'encaissement demeure : il reste vrai lorsqu'il n'y en a
qu'un, et sert de repli à toute ligne qui n'en désigne pas.

Les articles déjà enregistrés reçoivent le poste de leur encaissement : c'est
exactement ce qu'ils imputaient, écrit là où on le lit désormais. Aucun montant
ne bouge, aucune imputation n'est rejouée.

Create Date: 2026-09-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260917_art_poste"
down_revision = "20260917_enc_tarifs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "encaissement_articles",
        sa.Column("budget_poste_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_encaissement_articles_budget_poste",
        "encaissement_articles",
        "budget_postes",
        ["budget_poste_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_encaissement_articles_budget_poste_id",
        "encaissement_articles",
        ["budget_poste_id"],
    )
    op.execute(
        """
        UPDATE encaissement_articles a
           SET budget_poste_id = e.budget_poste_id
          FROM encaissements e
         WHERE e.id = a.encaissement_id
           AND e.budget_poste_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_encaissement_articles_budget_poste_id", table_name="encaissement_articles")
    op.drop_constraint("fk_encaissement_articles_budget_poste", "encaissement_articles", type_="foreignkey")
    op.drop_column("encaissement_articles", "budget_poste_id")
