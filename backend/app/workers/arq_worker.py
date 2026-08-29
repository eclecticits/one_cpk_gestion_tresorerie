"""Branchement arq : la file, les crons, les réglages du conteneur worker.

Lancé par :   arq app.workers.arq_worker.WorkerSettings

Tout ce qui est ici est de la plomberie. La logique vit dans
`app/workers/exports.py`, qui n'importe pas arq — c'est ce qui permet de tester
la reprise sur incident et le cloisonnement sans file ni Redis.
"""

from __future__ import annotations

import logging
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from app.core.config import settings
from app.db.session import engine
from app.services.export_queue import NOM_TACHE
from app.workers import exports as taches

logger = logging.getLogger("onec_cpk_api.worker_exports")


async def generer_export(ctx: dict[str, Any], job_id: str) -> str:
    """Enveloppe arq. Le nom DOIT rester `generer_export` : c'est celui que
    publie `app/services/export_queue.py` (arq résout les tâches par nom)."""
    return await taches.generer_export(job_id)


async def balayer_baux_expires(ctx: dict[str, Any]) -> int:
    """Reprend les jobs dont le worker est mort, et republie ce qui doit l'être.

    La republication passe par le pool que le worker a déjà (`ctx["redis"]`),
    pas par `export_queue.publier()` qui en ouvrirait un second pour rien.
    """

    async def republier(job_id: str, tentative: int) -> None:
        await ctx["redis"].enqueue_job(
            NOM_TACHE, job_id, _job_id=f"export:{job_id}:{tentative}"
        )

    return await taches.balayer_baux_expires(republier)


async def purger_artefacts_perimes(ctx: dict[str, Any]) -> int:
    return await taches.purger_artefacts_perimes()


async def au_demarrage(ctx: dict[str, Any]) -> None:
    logger.info(
        "Worker exports démarré : concurrence=%d, bail=%ds, timeout=%ds, rétention=%dj",
        settings.export_worker_concurrency,
        settings.export_job_lease_seconds,
        settings.export_job_timeout_seconds,
        settings.export_job_retention_days,
    )


async def a_l_arret(ctx: dict[str, Any]) -> None:
    # Le moteur SQLAlchemy tient des connexions ouvertes : les rendre
    # explicitement évite de laisser des sessions en attente côté PostgreSQL
    # quand le conteneur redémarre.
    await engine.dispose()
    logger.info("Worker exports arrêté, pool de connexions libéré.")


class WorkerSettings:
    functions = [generer_export]

    cron_jobs = [
        # Toutes les minutes à la seconde 0. Le balayage ne lit qu'une poignée
        # de lignes grâce aux index partiels sur (lease_until) et (expires_at) :
        # une fréquence élevée coûte peu et raccourcit d'autant la reprise après
        # la mort d'un worker.
        cron(balayer_baux_expires, second=0, unique=True),
        # Une fois par heure, à :07. Décalé de l'heure ronde, où se bousculent
        # déjà les autres traitements planifiés.
        cron(purger_artefacts_perimes, minute=7, second=0, unique=True),
    ]

    redis_settings = RedisSettings.from_dsn(settings.redis_url)

    # Un job à la fois par défaut, et ce n'est pas de la prudence de principe :
    # un seul export a été mesuré à +310 Mo de RSS, sur une VM de 3,7 Go
    # partagée avec PostgreSQL et le backend.
    max_jobs = settings.export_worker_concurrency
    job_timeout = settings.export_job_timeout_seconds

    # UNE seule tentative côté arq. La reprise est portée par le bail et le
    # balayage (`export_jobs.lease_until`), qui savent distinguer « le worker
    # est mort » de « le code a échoué ». Laisser arq réessayer en plus
    # produirait des reprises concurrentes sur le même job.
    max_tries = 1

    # Les résultats arq ne sont qu'un accusé : l'état fait foi en base. Une
    # heure suffit pour lire un incident dans les journaux.
    keep_result = 3600

    # Sonde de vitalité. Le worker écrit une clé Redis toutes les 20 s ;
    # `arq --check` la lit et sort en erreur si elle est absente ou périmée.
    # C'est la seule sonde possible pour un processus sans port HTTP — et sans
    # elle, un worker bloqué reste « up » aux yeux de Docker indéfiniment.
    health_check_interval = 20
    health_check_key = "arq:health-check:exports"

    on_startup = au_demarrage
    on_shutdown = a_l_arret
