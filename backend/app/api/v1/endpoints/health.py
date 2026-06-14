from __future__ import annotations

from fastapi import APIRouter, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.cache import redis_ping
from app.core.config import settings

router = APIRouter()


@router.get("/health", tags=["health"])
async def health() -> dict:
    """Liveness probe — confirme que le processus répond."""
    return {"status": "ok"}


@router.get("/health/live", tags=["health"])
async def liveness() -> dict:
    """Alias liveness probe (kubectl / docker HEALTHCHECK)."""
    return {"status": "ok"}


@router.get("/health/ready", tags=["health"])
async def readiness(response: Response) -> dict:
    """Readiness probe — vérifie PostgreSQL et Redis.

    Retourne 200 si tout est OK, 503 en état dégradé.
    Format : {"status": "ok|degraded", "database": "ok|error: ...", "redis": "ok|error: ..."}

    NullPool : chaque appel ouvre puis ferme sa propre connexion, ce qui évite
    les conflits d'event-loop en environnement de test et garantit un résultat
    frais (pas de connexion obsolète en pool).
    """
    db_status = "ok"
    redis_status = "ok"

    # Sonde PostgreSQL — connexion dédiée sans pool
    try:
        probe_engine = create_async_engine(settings.database_url, poolclass=NullPool)
        async with probe_engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        await probe_engine.dispose()
    except Exception as exc:
        db_status = f"error: {exc}"

    # Sonde Redis (optionnelle : état dégradé, pas d'arrêt total)
    if not await redis_ping():
        redis_status = "error: unreachable"

    overall = "ok" if db_status == "ok" and redis_status == "ok" else "degraded"
    if overall != "ok":
        response.status_code = 503

    return {
        "status": overall,
        "database": db_status,
        "redis": redis_status,
    }
