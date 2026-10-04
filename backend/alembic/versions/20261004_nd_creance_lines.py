"""Métadonnées métier des notes de débit et de leurs lignes.

Revision ID: 20261004_nd_creance_lines
Revises: 20261004_notes_debit_import
Create Date: 2026-10-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20261004_nd_creance_lines"
down_revision = "20261004_notes_debit_import"
branch_labels = None
depends_on = None


CATEGORIES_SQL = (
    "'COTISATION_ANNUELLE','ARRIERE_COTISATION','PENALITE_APO',"
    "'ARRIERE_PENALITE_APO','AUTRE_PENALITE','ARRIERE_AUTRE_PENALITE',"
    "'AUTRE_CREANCE','LEGACY'"
)


def upgrade() -> None:
    op.add_column("encaissements", sa.Column("numero_note_externe", sa.String(100), nullable=True))
    op.add_column("encaissements", sa.Column("exercice", sa.Integer(), nullable=True))
    op.add_column("encaissements", sa.Column("date_echeance", sa.Date(), nullable=True))
    op.add_column("encaissements", sa.Column("reference_decision", sa.String(255), nullable=True))
    op.create_index("ix_encaissements_exercice", "encaissements", ["exercice"])
    op.create_index(
        "uq_enc_org_num_note_externe",
        "encaissements",
        ["organisation_id", "numero_note_externe"],
        unique=True,
        postgresql_where=sa.text("numero_note_externe IS NOT NULL AND btrim(numero_note_externe) <> ''"),
    )

    op.add_column("encaissement_articles", sa.Column("categorie", sa.String(40), nullable=True))
    op.add_column("encaissement_articles", sa.Column("exercice", sa.Integer(), nullable=True))
    op.add_column("encaissement_articles", sa.Column("reference_decision", sa.String(255), nullable=True))
    op.create_index("ix_encaissement_articles_categorie", "encaissement_articles", ["categorie"])
    op.create_index("ix_encaissement_articles_exercice", "encaissement_articles", ["exercice"])

    # Compatibilité : les anciennes notes EC/SEC restent détaillables. Leur
    # année est la meilleure information disponible ; aucune valeur historique
    # n'est écrasée ou supprimée.
    op.execute(
        """
        UPDATE encaissements
        SET exercice = EXTRACT(YEAR FROM date_encaissement)::integer
        WHERE exercice IS NULL
          AND type_client IN ('expert_comptable', 'sec')
          AND est_proforma IS FALSE
        """
    )
    op.execute(
        """
        UPDATE encaissement_articles AS article
        SET categorie = CASE
                WHEN enc.type_client IN ('expert_comptable', 'sec') AND enc.est_proforma IS FALSE
                THEN 'LEGACY'
                ELSE article.categorie
            END,
            exercice = COALESCE(article.exercice, enc.exercice, EXTRACT(YEAR FROM enc.date_encaissement)::integer)
        FROM encaissements AS enc
        WHERE enc.id = article.encaissement_id
        """
    )

    op.create_check_constraint(
        "ck_encaissements_exercice",
        "encaissements",
        "exercice IS NULL OR exercice BETWEEN 1900 AND 2100",
    )
    op.create_check_constraint(
        "ck_enc_articles_exercice",
        "encaissement_articles",
        "exercice IS NULL OR exercice BETWEEN 1900 AND 2100",
    )
    op.create_check_constraint(
        "ck_enc_articles_categorie",
        "encaissement_articles",
        f"categorie IS NULL OR categorie IN ({CATEGORIES_SQL})",
    )


def downgrade() -> None:
    op.drop_constraint("ck_enc_articles_categorie", "encaissement_articles", type_="check")
    op.drop_constraint("ck_enc_articles_exercice", "encaissement_articles", type_="check")
    op.drop_constraint("ck_encaissements_exercice", "encaissements", type_="check")
    op.drop_index("ix_encaissement_articles_exercice", table_name="encaissement_articles")
    op.drop_index("ix_encaissement_articles_categorie", table_name="encaissement_articles")
    op.drop_column("encaissement_articles", "reference_decision")
    op.drop_column("encaissement_articles", "exercice")
    op.drop_column("encaissement_articles", "categorie")
    op.drop_index("uq_enc_org_num_note_externe", table_name="encaissements")
    op.drop_index("ix_encaissements_exercice", table_name="encaissements")
    op.drop_column("encaissements", "reference_decision")
    op.drop_column("encaissements", "date_echeance")
    op.drop_column("encaissements", "exercice")
    op.drop_column("encaissements", "numero_note_externe")
