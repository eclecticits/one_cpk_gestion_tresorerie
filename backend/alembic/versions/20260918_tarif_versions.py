"""Un tarif ne se modifie ni ne se supprime : il se clôt et se rouvre

Revision ID: 20260918_tarif_vers
Revises: 20260917_art_poste

Les chiffres du passé ne risquaient rien : un article d'encaissement garde sa
propre photo — libellé, prix, quantité, poste. Ce qui disparaissait, c'était la
DÉFINITION : une suppression franche (`DELETE`) effaçait le tarif, un renommage
écrasait celui d'hier, et plus personne ne pouvait dire qu'un reçu de l'an
dernier avait été émis au prix réglé de l'époque, ni distinguer un prix tarifé
d'un prix librement saisi.

Pire, le libellé étant la CLÉ d'application, renommer un tarif libérait
l'ancien nom : le caissier qui retapait « Cotisation annuelle » n'était plus
verrouillé du tout, et rien ne le signalait. La sécurité recherchée se
retournait en son contraire, en silence.

Trois choses changent donc :

- une version porte ses dates de validité (`effet_du`, `effet_au`) et chaîne
  celle qu'elle remplace (`remplace_id`). L'unicité du libellé ne vaut plus que
  pour les versions en vigueur, sans quoi un libellé clos serait interdit à
  jamais ;
- l'article grave le tarif sous lequel il a été émis (`tarif_id`) et dit si son
  prix fut forcé (`tarif_force`). La clé étrangère est en RESTRICT : la base
  interdit désormais d'elle-même la suppression franche, sans dépendre d'un
  contrôle applicatif qu'on pourrait oublier ;
- le passé est rattaché par correspondance de libellé normalisé, pour qu'un
  tarif déjà utilisé avant cette migration ne soit pas traité comme neuf.

Create Date: 2026-09-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "20260918_tarif_vers"
down_revision = "20260917_art_poste"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Les versions d'un tarif --------------------------------------------
    op.add_column("encaissement_tarifs", sa.Column("effet_du", sa.Date(), nullable=True))
    # Les tarifs existants valent depuis leur création : c'est la seule date
    # vraie dont on dispose, et la seule qui ne réécrive rien.
    op.execute("UPDATE encaissement_tarifs SET effet_du = created_at::date WHERE effet_du IS NULL")
    op.alter_column(
        "encaissement_tarifs",
        "effet_du",
        nullable=False,
        server_default=sa.text("CURRENT_DATE"),
    )
    op.add_column("encaissement_tarifs", sa.Column("effet_au", sa.Date(), nullable=True))
    op.add_column("encaissement_tarifs", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("encaissement_tarifs", sa.Column("archived_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("encaissement_tarifs", sa.Column("remplace_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_encaissement_tarifs_remplace",
        "encaissement_tarifs",
        "encaissement_tarifs",
        ["remplace_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Un libellé ne désigne qu'un tarif À LA FOIS. L'unicité pleine
    # interdirait de rouvrir un libellé clos, ou de garder deux versions
    # successives du même nom.
    op.drop_constraint("uq_encaissement_tarifs_org_libelle", "encaissement_tarifs", type_="unique")
    op.create_index(
        "uq_encaissement_tarifs_org_libelle_vivant",
        "encaissement_tarifs",
        ["organisation_id", "libelle_normalise"],
        unique=True,
        postgresql_where=sa.text("effet_au IS NULL"),
    )
    op.create_index(
        "ix_encaissement_tarifs_libelle_effet",
        "encaissement_tarifs",
        ["organisation_id", "libelle_normalise", "effet_du"],
    )

    # --- Le lien gravé dans le reçu -----------------------------------------
    op.add_column("encaissement_articles", sa.Column("tarif_id", sa.Integer(), nullable=True))
    op.add_column(
        "encaissement_articles",
        sa.Column("tarif_force", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_foreign_key(
        "fk_encaissement_articles_tarif",
        "encaissement_articles",
        "encaissement_tarifs",
        ["tarif_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_encaissement_articles_tarif_id", "encaissement_articles", ["tarif_id"])

    # Le passé se rattache par le libellé normalisé — mêmes règles que le
    # service (minuscules, espaces resserrés). Sans cela, un tarif qui a déjà
    # servi cent fois passerait pour neuf et se laisserait modifier en place.
    op.execute(
        r"""
        UPDATE encaissement_articles a
           SET tarif_id = t.id
          FROM encaissement_tarifs t
         WHERE t.organisation_id = a.organisation_id
           AND t.libelle_normalise = lower(btrim(regexp_replace(a.libelle, '\s+', ' ', 'g')))
           AND a.tarif_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_encaissement_articles_tarif_id", table_name="encaissement_articles")
    op.drop_constraint("fk_encaissement_articles_tarif", "encaissement_articles", type_="foreignkey")
    op.drop_column("encaissement_articles", "tarif_force")
    op.drop_column("encaissement_articles", "tarif_id")

    # Les versions closes disparaissent : sans elles, l'unicité pleine peut
    # revenir sans se heurter à deux homonymes.
    op.execute("DELETE FROM encaissement_tarifs WHERE effet_au IS NOT NULL")
    op.drop_index("ix_encaissement_tarifs_libelle_effet", table_name="encaissement_tarifs")
    op.drop_index("uq_encaissement_tarifs_org_libelle_vivant", table_name="encaissement_tarifs")
    op.create_unique_constraint(
        "uq_encaissement_tarifs_org_libelle",
        "encaissement_tarifs",
        ["organisation_id", "libelle_normalise"],
    )
    op.drop_constraint("fk_encaissement_tarifs_remplace", "encaissement_tarifs", type_="foreignkey")
    op.drop_column("encaissement_tarifs", "remplace_id")
    op.drop_column("encaissement_tarifs", "archived_by")
    op.drop_column("encaissement_tarifs", "archived_at")
    op.drop_column("encaissement_tarifs", "effet_au")
    op.drop_column("encaissement_tarifs", "effet_du")
