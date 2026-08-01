from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


def _rate_limit_key(request: Request) -> str:
    """Clé de limitation basée sur l'IP réelle du client.

    On ne fait PAS confiance au premier élément de X-Forwarded-For (contrôlé par
    le client, donc usurpable pour contourner le rate-limiting). On lit l'entrée
    ajoutée par notre reverse-proxy de confiance, en partant de la droite selon
    le nombre de proxies configuré (`TRUSTED_PROXY_HOPS`). En cas d'incohérence,
    on retombe sur l'adresse du socket.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            hops = max(1, int(getattr(settings, "trusted_proxy_hops", 1) or 1))
            idx = len(parts) - hops
            if 0 <= idx < len(parts):
                return parts[idx]
            # Chaîne plus courte qu'attendu : prendre l'entrée la plus à droite
            # (celle posée par le proxy le plus proche), jamais la plus à gauche.
            return parts[-1]
    return get_remote_address(request)


limiter = Limiter(key_func=_rate_limit_key, default_limits=[])
