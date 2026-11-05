from __future__ import annotations

"""Clés et invalidation du cache des rapports agrégés.

Le résumé ``/reports/summary`` est mis en cache quelques secondes pour absorber
les rafraîchissements du tableau de bord. Sans invalidation explicite, une
opération financière n'apparaîtrait qu'après expiration du TTL — l'utilisateur
qui vient de saisir un encaissement ne le verrait pas dans ses totaux.

Les statistiques du tableau de bord (``/dashboard/stats``) sont mémorisées de
la même façon et purgées par la même fonction : toute opération qui change un
total change aussi un solde affiché sur le tableau de bord.
"""

import hashlib

from app.core.cache import cache_delete_pattern

REPORT_SUMMARY_PREFIX = "reports:summary"
DASHBOARD_STATS_PREFIX = "dashboard:stats"


def report_summary_cache_key(
    tenant_id: int,
    date_debut: str | None,
    date_fin: str | None,
    canal: str | None,
    devise: str | None = None,
) -> str:
    """Clé d'un résumé. TOUT filtre qui change les chiffres doit y figurer :
    deux vues qui partagent une clé se servent mutuellement leurs totaux."""
    raw = f"{tenant_id}|{date_debut or ''}|{date_fin or ''}|{canal or ''}|{devise or ''}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{REPORT_SUMMARY_PREFIX}:{tenant_id}:{digest}"


async def invalidate_report_summary_cache(tenant_id: int) -> int:
    """Purge les résumés et les statistiques du tableau de bord mémorisés
    d'une organisation (toutes périodes, canaux, comptes et devises).

    Sans la purge du tableau de bord, le solde d'un compte bancaire choisi
    restait figé jusqu'à 60 s après une opération, alors que « Tous les
    comptes », lu en direct sur ``/tresorerie/soldes``, était déjà à jour :
    changer de compte donnait des chiffres qui ne se recoupaient pas.
    """
    purged = await cache_delete_pattern(f"{REPORT_SUMMARY_PREFIX}:{tenant_id}:*")
    purged += await cache_delete_pattern(f"{DASHBOARD_STATS_PREFIX}:{tenant_id}:*")
    return purged
