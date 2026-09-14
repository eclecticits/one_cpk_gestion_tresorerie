"""Fiabilise la base consolidée et ses instantanés d'analyse.

Revision ID: 20260914_tableau_snapshot
Revises: 20260914_tableau_numeros
Create Date: 2026-09-14
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260914_tableau_snapshot"
down_revision = "20260914_tableau_numeros"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Une seule notion de date effective pour le code Python et les requêtes SQL.
    op.execute("""
        UPDATE secretariat_tableau_imports
           SET date_situation = created_at::date
         WHERE date_situation IS NULL
    """)
    op.alter_column("secretariat_tableau_imports", "date_situation", nullable=False)

    # Les colonnes ajoutées après les premiers imports sont alimentées également
    # pour l'historique afin que la vue consolidée ne montre pas de faux manques.
    op.execute(r"""
        UPDATE secretariat_tableau_dossiers
           SET annee_inscription = 2000 + substring(numero_ordre from '/([0-9]{2})\.')::integer
         WHERE annee_inscription IS NULL
           AND numero_ordre ~ '/[0-9]{2}\.'
    """)
    op.execute(r"""
        UPDATE secretariat_tableau_dossiers
           SET anciennete_annees = greatest(
               0,
               substring(exercice from '(20[0-9]{2})')::integer - annee_inscription
           )
         WHERE anciennete_annees IS NULL
           AND annee_inscription IS NOT NULL
           AND exercice ~ '20[0-9]{2}'
    """)

    op.add_column(
        "secretariat_tableau_analyses",
        sa.Column("scope", sa.String(20), nullable=False, server_default="import"),
    )
    op.add_column(
        "secretariat_tableau_analyses",
        sa.Column("source_dossier_ids", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "secretariat_tableau_analyses",
        sa.Column("source_import_ids", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "secretariat_tableau_analyses",
        sa.Column("source_decision_ids", postgresql.JSONB(), nullable=True),
    )
    op.create_index("ix_secretariat_tableau_analyses_scope", "secretariat_tableau_analyses", ["scope"])
    op.execute("""
        DELETE FROM secretariat_tableau_analyses ancien
         USING secretariat_tableau_analyses recent
         WHERE ancien.organisation_id = recent.organisation_id
           AND ancien.import_id = recent.import_id
           AND ancien.scope = recent.scope
           AND ancien.id < recent.id
    """)
    op.create_unique_constraint(
        "uq_tableau_analyse_scope",
        "secretariat_tableau_analyses",
        ["organisation_id", "import_id", "scope"],
    )

    op.add_column(
        "secretariat_tableau_anomalies",
        sa.Column(
            "analyse_id",
            sa.Integer(),
            sa.ForeignKey("secretariat_tableau_analyses.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_secretariat_tableau_anomalies_analyse_id",
        "secretariat_tableau_anomalies",
        ["analyse_id"],
    )

    op.execute("""
        INSERT INTO permissions (code, description, created_at)
        VALUES
            ('secretariat.tableau.decide', 'Secrétariat - Tableau : enregistrer une décision', now()),
            ('secretariat.tableau.correct', 'Secrétariat - Tableau : corriger un dossier', now())
        ON CONFLICT (code) DO NOTHING
    """)
    op.execute("""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
          FROM roles r
          JOIN permissions p
            ON p.code IN ('secretariat.tableau.decide', 'secretariat.tableau.correct')
         WHERE r.code IN ('admin', 'administrateur_secretariat')
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM role_permissions
         WHERE permission_id IN (
             SELECT id FROM permissions
              WHERE code IN ('secretariat.tableau.decide', 'secretariat.tableau.correct')
         )
    """)
    op.execute("""
        DELETE FROM permissions
         WHERE code IN ('secretariat.tableau.decide', 'secretariat.tableau.correct')
    """)
    op.drop_index("ix_secretariat_tableau_anomalies_analyse_id", table_name="secretariat_tableau_anomalies")
    op.drop_column("secretariat_tableau_anomalies", "analyse_id")
    op.drop_constraint("uq_tableau_analyse_scope", "secretariat_tableau_analyses", type_="unique")
    op.drop_index("ix_secretariat_tableau_analyses_scope", table_name="secretariat_tableau_analyses")
    op.drop_column("secretariat_tableau_analyses", "source_decision_ids")
    op.drop_column("secretariat_tableau_analyses", "source_import_ids")
    op.drop_column("secretariat_tableau_analyses", "source_dossier_ids")
    op.drop_column("secretariat_tableau_analyses", "scope")
    op.alter_column("secretariat_tableau_imports", "date_situation", nullable=True)
