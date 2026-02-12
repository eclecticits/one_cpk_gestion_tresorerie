"""move budget lines from 2027 to 2026 and set 2026 draft

Revision ID: 20260211_budget_2027_2026
Revises: 20260211_sortie_exrate
Create Date: 2026-02-11
"""

from alembic import op

revision = "20260211_budget_2027_2026"
down_revision = "20260211_sortie_exrate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
          ex2026_id integer;
          ex2027_id integer;
        BEGIN
          SELECT id INTO ex2026_id FROM budget_exercices WHERE annee = 2026 LIMIT 1;
          IF ex2026_id IS NULL THEN
            INSERT INTO budget_exercices (annee, statut)
            VALUES (2026, 'Brouillon')
            RETURNING id INTO ex2026_id;
          ELSE
            UPDATE budget_exercices SET statut = 'Brouillon' WHERE id = ex2026_id;
          END IF;

          SELECT id INTO ex2027_id FROM budget_exercices WHERE annee = 2027 LIMIT 1;
          IF ex2027_id IS NOT NULL THEN
            UPDATE budget_lignes
            SET exercice_id = ex2026_id
            WHERE exercice_id = ex2027_id;
            UPDATE budget_audit_logs
            SET exercice_id = ex2026_id
            WHERE exercice_id = ex2027_id;
            DELETE FROM budget_exercices WHERE id = ex2027_id;
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Irreversible data move; no-op.
    pass
