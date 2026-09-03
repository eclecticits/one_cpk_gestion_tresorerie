"""store the normalized beneficiary key on ordres_decaissement

Revision ID: 20260909_od_benef_norm
Revises: 20260908_req_sources

Le plafond anti-fractionnement des ordres directs regroupe les ordres
« similaires » par bénéficiaire normalisé. Cette clé était calculée DEUX fois —
en Python pour la requête, en SQL pour la colonne — et les deux normalisations
ne peuvent pas être tenues identiques : `\\s` de Python couvre l'espace Unicode
(insécable comprise), `[[:space:]]` de Postgres dépend du ctype et exclut
l'insécable sous glibc. « ACME<NBSP>SARL » et « ACME SARL » donnaient donc deux
clés distinctes d'un côté et une seule de l'autre : deux ordres identiques
cessaient d'être vus comme similaires, et le plafond se contournait en collant
un nom porteur d'une espace insécable.

La clé est désormais calculée une seule fois, en Python, et stockée. Il n'y a
plus deux normalisations à tenir alignées — il n'y en a qu'une. Bénéfice
secondaire : la comparaison porte sur une colonne nue, donc indexable, là où
`trim(regexp_replace(lower(...)))` imposait un parcours de tous les ordres du
tenant à chaque programmation d'ordre direct.

Le backfill ci-dessous est une APPROXIMATION SQL de la normalisation Python,
pour les lignes déjà en base. Elle en diffère sur les espaces non-ASCII, seul
cas où les deux divergeaient : une ligne ancienne dont le bénéficiaire porte
une insécable gardera une clé légèrement différente de celle qu'un nouvel ordre
au même nom recevrait. C'est le résidu assumé de la reprise, borné à
l'historique ; toute ligne écrite après cette migration passe par Python.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260909_od_benef_norm"
down_revision = "20260908_req_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ordres_decaissement",
        sa.Column("beneficiaire_normalise", sa.String(length=200), nullable=True),
    )
    # `beneficiaire` est NOT NULL : toute ligne existante reçoit donc une clé,
    # et la colonne peut passer NOT NULL juste après. Sans cela une ligne à clé
    # nulle échapperait au regroupement, donc au plafond.
    op.execute(
        """
        UPDATE ordres_decaissement
        SET beneficiaire_normalise =
            btrim(regexp_replace(lower(coalesce(beneficiaire, '')), '[[:space:]]+', ' ', 'g'))
        WHERE beneficiaire_normalise IS NULL
        """
    )
    op.alter_column(
        "ordres_decaissement",
        "beneficiaire_normalise",
        existing_type=sa.String(length=200),
        nullable=False,
    )
    # Index servant exactement le cumul anti-fractionnement : restreint aux
    # ordres directs (les seuls concernés), colonnes dans l'ordre du filtre puis
    # de la borne temporelle.
    op.create_index(
        "ix_ordres_direct_fractionnement",
        "ordres_decaissement",
        ["organisation_id", "service_id", "beneficiaire_normalise", "created_at"],
        postgresql_where=sa.text("requisition_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_ordres_direct_fractionnement", table_name="ordres_decaissement")
    op.drop_column("ordres_decaissement", "beneficiaire_normalise")
