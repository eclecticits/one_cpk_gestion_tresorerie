"""Engagements budgétaires dérivés : remise à niveau des compteurs.

`budget_postes.montant_engage` n'était qu'incrémenté, jamais rendu : une
réquisition rejetée (« annulée » dans le vocabulaire métier) continuait de geler
son montant indéfiniment. Le compteur devient une valeur dérivée des lignes des
réquisitions réellement engageantes ; cette migration le recale une fois pour
toutes les organisations.

Règle appliquée, identique à `app/services/budget_engagement.py` :
engagée = réquisition non supprimée, dont l'examen est EN_EXAMEN ou EXAMINE,
et dont le statut n'est pas REJETEE.

Revision ID: 20260818_engagements_derives
Revises: 20260818_perf_indexes
Create Date: 2026-08-18
"""

from alembic import op


revision = "20260818_engagements_derives"
down_revision = "20260818_perf_indexes"
branch_labels = None
depends_on = None


RECALCUL = """
    UPDATE budget_postes bp
    SET montant_engage = COALESCE(sub.total, 0)
    FROM (
        SELECT p.id AS poste_id,
               COALESCE(SUM(lr.montant_total) FILTER (WHERE r.id IS NOT NULL), 0) AS total
        FROM budget_postes p
        LEFT JOIN lignes_requisition lr
               ON lr.budget_poste_id = p.id
              AND lr.organisation_id = p.organisation_id
        LEFT JOIN requisitions r
               ON r.id = lr.requisition_id
              AND r.is_deleted = false
              AND UPPER(COALESCE(r.examen_status, '')) IN ('EN_EXAMEN', 'EXAMINE')
              AND UPPER(COALESCE(r.status, '')) NOT IN ('REJETEE')
        WHERE p.is_deleted = false
        GROUP BY p.id
    ) AS sub
    WHERE bp.id = sub.poste_id
      AND bp.montant_engage IS DISTINCT FROM COALESCE(sub.total, 0)
"""


def upgrade() -> None:
    op.execute(RECALCUL)


def downgrade() -> None:
    # Rien à défaire : le compteur reste une valeur dérivée, et l'état
    # antérieur (des engagements jamais libérés) n'est pas un état à restaurer.
    pass
