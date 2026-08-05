from __future__ import annotations

"""Clés et invalidation du cache des rapports agrégés.

Le résumé ``/reports/summary`` est mis en cache quelques secondes pour absorber
les rafraîchissements du tableau de bord. Sans invalidation explicite, une
opération financière n'apparaîtrait qu'après expiration du TTL — l'utilisateur
qui vient de saisir un encaissement ne le verrait pas dans ses totaux.
"""

import hashlib

from app.core.cache import cache_delete_pattern

REPORT_SUMMARY_PREFIX = "reports:summary"


def report_summary_cache_key(
    tenant_id: int,
    date_debut: str | None,
    date_fin: str | None,
    canal: str | None,
) -> str:
    raw = f"{tenant_id}|{date_debut or ''}|{date_fin or ''}|{canal or ''}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{REPORT_SUMMARY_PREFIX}:{tenant_id}:{digest}"


async def invalidate_report_summary_cache(tenant_id: int) -> int:
    """Purge les résumés mémorisés d'une organisation (toutes périodes/canaux)."""
    return await cache_delete_pattern(f"{REPORT_SUMMARY_PREFIX}:{tenant_id}:*")
