"""Index de performance pour le dashboard et les rapports.

Les agrégations datées (dashboard/stats, reports) filtraient sur des
expressions type CAST(date AS date) / func.date(), ce qui empêchait tout index
et provoquait des balayages complets (22 s, timeouts gunicorn). Les requêtes
ont été réécrites en comparaisons de plage sur la colonne brute ; on ajoute ici
les index composites (organisation_id, date) correspondants, dont un index
fonctionnel sur COALESCE(date_paiement, created_at) pour les sorties.

Revision ID: 20260722d_perf_indexes
Revises: 20260722c_sortie_montant_positif
Create Date: 2026-07-22
"""

from alembic import op


revision = "20260722d_perf_indexes"
down_revision = "20260722c_sortie_montant_positif"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_enc_org_date "
        "ON encaissements (organisation_id, date_encaissement)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_sorties_org_paiement_ts "
        "ON sorties_fonds (organisation_id, (COALESCE(date_paiement, created_at)))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_sorties_org_created "
        "ON sorties_fonds (organisation_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_requisitions_org_created "
        "ON requisitions (organisation_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_requisitions_org_created")
    op.execute("DROP INDEX IF EXISTS ix_sorties_org_created")
    op.execute("DROP INDEX IF EXISTS ix_sorties_org_paiement_ts")
    op.execute("DROP INDEX IF EXISTS ix_enc_org_date")
