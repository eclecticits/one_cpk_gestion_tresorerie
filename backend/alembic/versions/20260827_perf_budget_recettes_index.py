"""Index couvrant pour l'agregat des recettes par poste budgetaire

Revision ID: 20260827_perf_budget_recettes
Revises: 20260823_whatsapp_notifs
Create Date: 2026-08-27 00:00:00.000000

MESURE sous charge, pas deduit. Pendant la campagne du 27/08 (preset
production : 120 000 encaissements), l'agregat de `_active_recettes_by_poste`
(app/api/v1/endpoints/budget.py:159) est la requete la plus lente relevee :
194 secondes. Elle tient une connexion du pool pendant tout ce temps, le pool
(4 workers x 10) s'epuise, et le reste part en file : un simple SELECT users
d'authentification a ete mesure a 97 s, l'arbitre gunicorn a tue 17 workers.

Cause : aucun index ne couvre (organisation_id, budget_poste_id). Le plan est
un Parallel Seq Scan des 120 000 lignes. Machine au repos il coute deja 448 ms
et 4 782 buffers ; sous charge, prive de workers paralleles, il explose.

Cet index est COUVRANT (INCLUDE montant_paye) et PARTIEL sur exactement le
predicat de la requete, donc le plan devient un Parallel Index Only Scan :

    448 ms / 4 782 buffers  ->  26,9 ms / 533 buffers   (x17)

L'index pese 3,7 Mo contre 37 Mo pour la table : c'est de la que vient le gain,
pas de la selectivite (dans une organisation donnee, toutes les lignes
correspondent). Le predicat partiel doit rester identique a celui du code ;
s'il change dans budget.py, cet index cesse d'etre utilise silencieusement.

CREATE INDEX classique (non CONCURRENTLY) : alembic/env.py execute chaque
migration dans une transaction, incompatible avec CONCURRENTLY. Sur une table
volumineuse en production, prevoir une fenetre de maintenance — le verrou SHARE
bloque les ecritures le temps de la construction.
"""

from __future__ import annotations

from alembic import op


revision = "20260827_perf_budget_recettes"
down_revision = "20260823_whatsapp_notifs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_enc_org_poste_actif "
        "ON encaissements (organisation_id, budget_poste_id) "
        "INCLUDE (montant_paye) "
        "WHERE est_proforma IS false AND is_deleted IS false "
        "AND (statut_operation IS NULL OR statut_operation = 'ACTIVE')"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_enc_org_poste_actif")
