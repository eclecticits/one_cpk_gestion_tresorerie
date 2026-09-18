"""Une collation de réunion se compte par tête, pas par ordre

Revision ID: 20260918_collation
Revises: 20260918_tarif_vers

La sortie directe est plafonnée à 100 USD, et ce plafond a un sens : elle
n'échappe à la réquisition que parce qu'elle est petite. C'est sa petitesse qui
la justifie, jamais son intitulé.

Une collation de réunion échoue pourtant à ce test sans rien avoir d'abusif :
quarante participants à cinq dollars font deux cents dollars, et la dépense
reste ce qu'elle est — une collation. Le montant n'est pas la bonne unité de
mesure ; le prix PAR TÊTE l'est.

L'ordre porte donc, pour ce type, ce qui le rend vérifiable : la réunion, sa
date, le nombre de participants et le montant par personne. Le total cesse
d'être un chiffre tapé à la main dont la description dirait « collation CA ».

Le garde-fou anti-fractionnement suit le même déplacement. Il regroupe les
ordres directs par (service, bénéficiaire) sur 24 h ; une collation y resterait
comme un bloc de deux cents dollars et bloquerait pour la journée toute sortie
directe du même responsable. Elle obtient donc sa propre clé — la réunion et sa
date —, sans quoi une assemblée de quarante-cinq personnes se découperait en
trois ordres de quinze et le plafond par tête ne protégerait plus rien.

Create Date: 2026-09-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260918_collation"
down_revision = "20260918_tarif_vers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ordres_decaissement",
        sa.Column("type_sortie", sa.String(length=20), nullable=False, server_default="SIMPLE"),
    )
    op.add_column("ordres_decaissement", sa.Column("reunion_intitule", sa.String(length=200), nullable=True))
    op.add_column("ordres_decaissement", sa.Column("reunion_date", sa.Date(), nullable=True))
    # Clé de regroupement propre à la collation, normalisée en Python comme
    # l'est déjà celle du bénéficiaire : deux normalisations, une par langage,
    # ne peuvent être tenues identiques, et leur écart rouvrirait le plafond.
    op.add_column("ordres_decaissement", sa.Column("reunion_normalisee", sa.String(length=200), nullable=True))
    op.add_column("ordres_decaissement", sa.Column("participants", sa.Integer(), nullable=True))
    op.add_column("ordres_decaissement", sa.Column("montant_par_personne", sa.Numeric(14, 2), nullable=True))

    op.create_check_constraint(
        "ck_ordres_decaissement_type_sortie",
        "ordres_decaissement",
        "type_sortie IN ('SIMPLE','COLLATION')",
    )
    # Une collation sans nombre de têtes ni prix unitaire n'est qu'un montant
    # qui se réclame d'un nom : ce qui la distingue doit être présent, ou elle
    # n'est pas une collation.
    op.create_check_constraint(
        "ck_ordres_decaissement_collation_complete",
        "ordres_decaissement",
        """
        type_sortie <> 'COLLATION' OR (
            participants IS NOT NULL AND participants > 0
            AND montant_par_personne IS NOT NULL AND montant_par_personne > 0
            AND reunion_intitule IS NOT NULL
            AND reunion_date IS NOT NULL
            AND reunion_normalisee IS NOT NULL
        )
        """,
    )

    op.create_index(
        "ix_ordres_collation_fractionnement",
        "ordres_decaissement",
        ["organisation_id", "reunion_normalisee", "reunion_date"],
        postgresql_where=sa.text("requisition_id IS NULL AND type_sortie = 'COLLATION'"),
    )

    # Les deux bornes de la collation, réglables par l'organisation : le prix
    # par tête dit que c'en est bien une, le total dit qu'elle reste une sortie
    # directe. Figées dans le code, il faudrait une mise en production pour
    # ajuster ce qu'un traiteur fait varier.
    op.add_column(
        "organisation_settings",
        sa.Column(
            "collation_plafond_par_personne_usd",
            sa.Numeric(10, 2),
            nullable=False,
            server_default="10",
        ),
    )
    op.add_column(
        "organisation_settings",
        sa.Column(
            "collation_plafond_total_usd",
            sa.Numeric(14, 2),
            nullable=False,
            server_default="500",
        ),
    )


def downgrade() -> None:
    op.drop_column("organisation_settings", "collation_plafond_total_usd")
    op.drop_column("organisation_settings", "collation_plafond_par_personne_usd")
    op.drop_index("ix_ordres_collation_fractionnement", table_name="ordres_decaissement")
    op.drop_constraint("ck_ordres_decaissement_collation_complete", "ordres_decaissement", type_="check")
    op.drop_constraint("ck_ordres_decaissement_type_sortie", "ordres_decaissement", type_="check")
    op.drop_column("ordres_decaissement", "montant_par_personne")
    op.drop_column("ordres_decaissement", "participants")
    op.drop_column("ordres_decaissement", "reunion_normalisee")
    op.drop_column("ordres_decaissement", "reunion_date")
    op.drop_column("ordres_decaissement", "reunion_intitule")
    op.drop_column("ordres_decaissement", "type_sortie")
