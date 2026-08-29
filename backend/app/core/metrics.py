from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from prometheus_fastapi_instrumentator import Instrumentator

from app.core.config import settings
from app.core.export_metrics import rafraichir_depuis_base

_EXCLUDED = [
    "/metrics",
    "/health",
    "/health/live",
    "/health/ready",
    "/",
    "/static",
    "/uploads",
]

logger = logging.getLogger("onec_cpk_api.metrics")

_bearer = HTTPBearer(auto_error=False)


def _metrics_auth(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> None:
    """Vérifie le Bearer token si METRICS_TOKEN est configuré."""
    token = settings.metrics_token
    if not token:
        return  # pas de token configuré → accès libre (mode dev / réseau privé)
    if not credentials or credentials.credentials != token:
        raise HTTPException(status_code=403, detail="Forbidden")


def setup_metrics(app: FastAPI) -> None:
    """Configure Prometheus.

    Comportement selon les variables d'environnement :

    ENABLE_METRICS=false  → /metrics non monté, aucune instrumentation.
    ENABLE_METRICS=true (défaut)
      + METRICS_TOKEN absent → route publique (dev, réseau privé).
      + METRICS_TOKEN=<secret> → route protégée par Bearer token.

    Exemple d'appel protégé :
        curl -H "Authorization: Bearer <token>" http://host:8000/metrics
    """
    if not settings.enable_metrics:
        return

    en_production = settings.env.lower() in {"prod", "production"}
    if en_production and not settings.metrics_token:
        # Échec FERMÉ, et pas au démarrage. Refuser de booter mettrait l'API à
        # terre pour une erreur de configuration de supervision, ce qui est
        # disproportionné ; servir /metrics sans jeton exposerait la volumétrie
        # de la plateforme à qui atteint le port. On ne monte donc pas la route,
        # et on le dit assez fort pour que ce soit corrigé.
        logger.error(
            "ENABLE_METRICS=true en production SANS METRICS_TOKEN : /metrics n'est "
            "PAS monté. Définissez METRICS_TOKEN (openssl rand -hex 32) pour "
            "rétablir la supervision."
        )
        return

    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        excluded_handlers=_EXCLUDED,
    ).instrument(app)

    @app.get("/metrics", include_in_schema=False, tags=["monitoring"])
    async def metrics_endpoint(_: None = Depends(_metrics_auth)) -> Response:
        # Les métriques d'export sont lues en base au moment du scrape : les
        # jobs sont produits par un AUTRE processus (le conteneur worker), donc
        # aucun compteur en mémoire de ce processus-ci ne pourrait les décrire.
        # Un cache borne la fréquence des agrégats.
        try:
            await rafraichir_depuis_base()
        except Exception:  # noqa: BLE001
            # Un endpoint de supervision qui échoue emporte la supervision
            # elle-même : on préfère servir les autres séries et signaler
            # l'incident dans les journaux plutôt que rendre 500 à Prometheus.
            logger.warning("Rafraîchissement des métriques d'export impossible", exc_info=True)
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
