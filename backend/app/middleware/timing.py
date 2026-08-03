from __future__ import annotations

import logging
import time

from app.core.db_perf import get_db_perf_stats, reset_db_perf_stats
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("onec_cpk_perf")

# Seuil en millisecondes au-delà duquel une requête est considérée lente
SLOW_THRESHOLD_MS: int = 500

# Routes exclues du log de performance (sondages fréquents)
_SKIP_PATHS = frozenset([
    "/health", "/health/live", "/health/ready", "/metrics", "/",
])


def _get_slow_counter():
    """Retourne le compteur Prometheus, ou None si prometheus_client absent."""
    try:
        from prometheus_client import Counter
        return Counter(
            "onec_cpk_slow_requests_total",
            "Nombre de requêtes HTTP dépassant le seuil de latence",
            ["method", "path"],
        )
    except Exception:
        return None


# Instancié une seule fois au chargement du module (lazy, fail-safe)
_slow_counter = None
_slow_counter_initialized = False


def _inc_slow(method: str, path: str) -> None:
    """Incrémente le compteur Prometheus si disponible."""
    global _slow_counter, _slow_counter_initialized
    if not _slow_counter_initialized:
        _slow_counter = _get_slow_counter()
        _slow_counter_initialized = True
    if _slow_counter is not None:
        try:
            _slow_counter.labels(method=method, path=path).inc()
        except Exception:
            pass


class SlowRequestMiddleware(BaseHTTPMiddleware):
    """Logue toute requête dépassant SLOW_THRESHOLD_MS millisecondes.

    Incrémente également le compteur Prometheus onec_cpk_slow_requests_total.

    Format du log :
        SLOW_REQUEST method=GET path=/api/v1/dashboard/stats
                     status=200 duration_ms=843 tenant_id=12
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        reset_db_perf_stats()
        t0 = time.monotonic()
        response = await call_next(request)
        elapsed_ms = (time.monotonic() - t0) * 1000

        if elapsed_ms >= SLOW_THRESHOLD_MS:
            tenant_id = getattr(request.state, "tenant_id", None)
            db_stats = get_db_perf_stats()
            logger.warning(
                "SLOW_REQUEST method=%s path=%s status=%s duration_ms=%.0f tenant_id=%s "
                "db_queries=%s db_total_ms=%.0f db_slowest_ms=%.0f db_slowest_statement=%s",
                request.method,
                request.url.path,
                response.status_code,
                elapsed_ms,
                tenant_id,
                db_stats.query_count if db_stats else 0,
                db_stats.total_ms if db_stats else 0,
                db_stats.slowest_ms if db_stats else 0,
                db_stats.slowest_statement if db_stats else None,
            )
            _inc_slow(request.method, request.url.path)

        return response
