"""Un libellé d'encaissement peut porter son prix et son imputation

Revision ID: 20260917_enc_tarifs
Revises: 20260916_verrous_tableau

La pré-liste des libellés d'encaissement vivait dans une colonne de texte,
un libellé par ligne. Elle faisait gagner de la frappe et rien d'autre : le
montant et le poste restaient à la main du caissier, et deux encaissements de
la même cotisation pouvaient différer sur l'un comme sur l'autre.

Un libellé devient un tarif, qui peut fixer un prix, une imputation, ou les
deux — les deux champs sont indépendants et facultatifs. Ce qui est défini
s'impose à la saisie ; ce qui ne l'est pas reste libre.

Le poste est désigné par son CODE et non par un identifiant : les postes
appartiennent à un exercice et changent d'identifiant chaque année. Le code se
résout à l'exercice courant au moment de servir, si bien qu'un tarif survit à
l'ouverture d'un nouvel exercice.

Les libellés déjà saisis sont repris tels quels, dans leur ordre, sans prix ni
poste : ils continuent de se comporter comme aujourd'hui. `print_settings.
encaissement_libelle_presets` n'est pas supprimée — les anciens clients la
lisent encore, et la vider ferait disparaître leur auto-complétion avant leur
mise à jour.

Create Date: 2026-09-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260917_enc_tarifs"
down_revision = "20260916_verrous_tableau"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "encaissement_tarifs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("libelle", sa.String(length=255), nullable=False),
        sa.Column("libelle_normalise", sa.String(length=255), nullable=False),
        sa.Column("montant", sa.Numeric(15, 2), nullable=True),
        sa.Column("devise", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("budget_poste_code", sa.String(length=50), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organisation_id", "libelle_normalise", name="uq_encaissement_tarifs_org_libelle"),
        sa.CheckConstraint("montant IS NULL OR montant > 0", name="ck_encaissement_tarifs_montant_positif"),
        sa.CheckConstraint("devise IN ('USD','CDF')", name="ck_encaissement_tarifs_devise"),
    )
    op.create_index("ix_encaissement_tarifs_organisation_id", "encaissement_tarifs", ["organisation_id"])
    op.create_index("ix_encaissement_tarifs_is_active", "encaissement_tarifs", ["is_active"])

    # Reprise de la pré-liste existante, ordre compris. `regexp_split_to_table`
    # avec `WITH ORDINALITY` donne la position de chaque ligne : c'est l'ordre
    # que l'administrateur a réglé à la main avec ses flèches, et le perdre lui
    # ferait tout reclasser. Les doublons de libellé (à la casse et aux espaces
    # près) sont écartés : la table exige l'unicité, et deux lignes identiques
    # ne désignaient déjà qu'un seul choix dans la liste.
    op.execute(
        """
        INSERT INTO encaissement_tarifs
            (organisation_id, libelle, libelle_normalise, position, is_active, devise)
        SELECT DISTINCT ON (ps.organisation_id, lower(btrim(ligne.valeur)))
               ps.organisation_id,
               btrim(ligne.valeur),
               lower(btrim(ligne.valeur)),
               ligne.position,
               true,
               'USD'
          FROM print_settings ps
          CROSS JOIN LATERAL regexp_split_to_table(
                   COALESCE(ps.encaissement_libelle_presets, ''), E'\\r?\\n'
               ) WITH ORDINALITY AS ligne(valeur, position)
         WHERE btrim(ligne.valeur) <> ''
         ORDER BY ps.organisation_id, lower(btrim(ligne.valeur)), ligne.position
        """
    )


def downgrade() -> None:
    op.drop_index("ix_encaissement_tarifs_is_active", table_name="encaissement_tarifs")
    op.drop_index("ix_encaissement_tarifs_organisation_id", table_name="encaissement_tarifs")
    op.drop_table("encaissement_tarifs")
