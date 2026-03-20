"""Seed core budget postes for initial organisations.

Revision ID: 20260325_seed_core_budget_postes
Revises: 20260324_budget_poste_is_global
Create Date: 2026-03-25
"""

from alembic import op


revision = "20260325_seed_core_budget_postes"
down_revision = "20260324_budget_poste_is_global"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        WITH orgs AS (
            SELECT id, slug
            FROM organisations
            WHERE slug IN ('kinshasa', 'haut-katanga', 'sud-kivu')
        ),
        year_cte AS (
            SELECT EXTRACT(YEAR FROM CURRENT_DATE)::int AS annee
        )
        INSERT INTO budget_exercices (organisation_id, annee, statut)
        SELECT orgs.id, year_cte.annee, 'Brouillon'
        FROM orgs, year_cte
        ON CONFLICT (organisation_id, annee) DO NOTHING;
        """
    )

    op.execute(
        """
        WITH orgs AS (
            SELECT id, slug
            FROM organisations
            WHERE slug IN ('kinshasa', 'haut-katanga', 'sud-kivu')
        ),
        year_cte AS (
            SELECT EXTRACT(YEAR FROM CURRENT_DATE)::int AS annee
        ),
        exs AS (
            SELECT be.id AS exercice_id, be.organisation_id
            FROM budget_exercices be
            JOIN orgs ON orgs.id = be.organisation_id
            JOIN year_cte yc ON yc.annee = be.annee
        )
        INSERT INTO budget_postes (
            organisation_id,
            exercice_id,
            code,
            libelle,
            type,
            active,
            montant_prevu,
            montant_engage,
            montant_paye,
            is_global
        )
        SELECT
            exs.organisation_id,
            exs.exercice_id,
            payload.code,
            payload.libelle,
            'DEPENSE',
            TRUE,
            0,
            0,
            0,
            TRUE
        FROM exs
        CROSS JOIN (
            VALUES
                ('ADM-01', 'Loyer et Charges Locatives'),
                ('PERS-01', 'Salaires et Gratifications'),
                ('TRA-01', 'Carburant et Maintenance'),
                ('COM-01', 'Communication et Internet'),
                ('MISS-01', 'Missions et Per Diem'),
                ('DIV-01', 'Divers et Imprévus')
        ) AS payload(code, libelle)
        WHERE NOT EXISTS (
            SELECT 1
            FROM budget_postes bp
            WHERE bp.organisation_id = exs.organisation_id
              AND bp.exercice_id = exs.exercice_id
              AND bp.code = payload.code
              AND bp.is_deleted IS NOT TRUE
        );
        """
    )


def downgrade() -> None:
    # Pas de suppression pour éviter toute perte ou incohérence.
    pass
