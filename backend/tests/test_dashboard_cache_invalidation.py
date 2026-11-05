"""Une opération financière doit purger aussi les stats du tableau de bord.

Sans cela, le solde d'un compte bancaire choisi sur le tableau de bord restait
figé jusqu'à l'expiration du cache (60 s), alors que « Tous les comptes », lu
en direct, était déjà à jour.
"""

from __future__ import annotations

import fnmatch

import pytest

from app.api.v1.endpoints.dashboard import _dashboard_cache_key
from app.services import report_cache
from app.services.report_cache import (
    invalidate_report_summary_cache,
    report_summary_cache_key,
)


class _FakeRedis:
    def __init__(self, keys: set[str]) -> None:
        self.keys = set(keys)

    async def scan(self, cursor: int = 0, match: str = "*", count: int = 500):
        return 0, [k for k in self.keys if fnmatch.fnmatchcase(k, match)]

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self.keys:
                self.keys.remove(key)
                removed += 1
        return removed


@pytest.mark.asyncio
async def test_invalidation_purge_le_tableau_de_bord(monkeypatch):
    compte_t1 = _dashboard_cache_key(1, "month", None, None, False, "BANQUE", 7, "USD")
    tous_t1 = _dashboard_cache_key(1, "month", None, None, False, None, None, None)
    resume_t1 = report_summary_cache_key(1, None, None, None)
    compte_t2 = _dashboard_cache_key(2, "month", None, None, False, "BANQUE", 9, "USD")
    fake = _FakeRedis({compte_t1, tous_t1, resume_t1, compte_t2})
    monkeypatch.setattr("app.core.cache.get_redis", lambda: fake)

    purged = await invalidate_report_summary_cache(1)

    assert purged == 3
    # L'autre organisation garde son cache.
    assert fake.keys == {compte_t2}
    assert compte_t1.startswith(f"{report_cache.DASHBOARD_STATS_PREFIX}:1:")
