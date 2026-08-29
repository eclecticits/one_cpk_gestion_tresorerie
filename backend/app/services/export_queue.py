"""Publication des jobs dans la file Redis (arq).

Redis n'est ici QUE le signal : la file transporte un identifiant, rien d'autre.
La vérité est en base (`export_jobs`). C'est ce qui permet à ce module d'être
tolérant à la panne sans rien perdre — si la publication échoue, le job reste
`QUEUED` et le balayage de réconciliation du worker le reprendra. Une
publication ratée retarde un export ; elle ne l'efface pas.

`arq` est importé PARESSEUSEMENT, à dessein : la génération asynchrone est
derrière un drapeau fermé par défaut, et un backend déployé sans la dépendance
ne doit ni refuser de démarrer ni casser le chemin synchrone. L'absence se
signale dans les journaux au moment où on en a besoin, pas au chargement.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger("onec_cpk_api.export_queue")

# Nom de la tâche côté worker. Doit correspondre au nom de la coroutine
# enregistrée dans app/workers/exports.py : arq résout par NOM, une faute de
# frappe ici produit un job qui part dans la file et n'est jamais exécuté.
NOM_TACHE = "generer_export"

_pool: Any | None = None
# Sérialise la création du pool. Sans ce verrou, deux requêtes concurrentes qui
# trouvent `_pool is None` en même temps ouvrent chacune un pool Redis : le
# second écrase le premier dans la globale, et le premier n'est plus fermé par
# personne — ses connexions restent ouvertes jusqu'à la mort du processus. Un
# `asyncio.Lock` construit à l'import est sûr depuis Python 3.10 : il ne
# capture plus la boucle d'événements à la construction.
_verrou_pool = asyncio.Lock()


def _reglages_redis() -> Any | None:
    try:
        from arq.connections import RedisSettings
    except ImportError:
        logger.error(
            "arq n'est pas installé : impossible de publier un job d'export. "
            "Ajoutez-le (requirements.txt) ou refermez EXPORT_ASYNC_TYPES."
        )
        return None
    reglages = RedisSettings.from_dsn(settings.redis_url)
    # Échouer vite. Les valeurs par défaut d'arq (5 tentatives, 1 s d'attente)
    # feraient patienter la requête HTTP cinq secondes quand Redis est absent —
    # pour un résultat qu'on sait déjà : on repartira sur le balayage.
    reglages.conn_retries = 1
    reglages.conn_timeout = 2
    return reglages


async def obtenir_pool() -> Any | None:
    """Pool arq partagé par le processus, ou None si Redis est hors d'atteinte."""
    global _pool
    if _pool is not None:
        return _pool
    async with _verrou_pool:
        # Relu sous verrou : le premier test sert à ne pas payer le verrou sur
        # le chemin normal, celui-ci à ne pas créer deux pools.
        if _pool is not None:
            return _pool
        reglages = _reglages_redis()
        if reglages is None:
            return None
        try:
            from arq import create_pool

            _pool = await create_pool(reglages)
        except Exception as exc:  # noqa: BLE001 - toute panne Redis vaut repli
            logger.warning("Pool arq indisponible (%s) : le job restera en file.", exc)
            return None
        return _pool


async def fermer_pool() -> None:
    global _pool
    if _pool is not None:
        try:
            await _pool.aclose()
        except Exception:  # noqa: BLE001 - la fermeture ne doit jamais faire échouer l'arrêt
            logger.debug("Fermeture du pool arq en erreur", exc_info=True)
        _pool = None


async def publier(job_id: str, *, tentative: int = 1) -> bool:
    """Signale un job au worker. Rend False si le signal n'est pas parti.

    L'identifiant arq inclut le numéro de tentative. Sans lui, une reprise après
    expiration de bail serait refusée par arq — qui déduplique sur l'identifiant
    de job et garde une trace des jobs terminés. Avec lui, chaque tentative est
    un message distinct, et une double publication de la MÊME tentative reste
    dédupliquée : exactement le comportement voulu.
    """
    pool = await obtenir_pool()
    if pool is None:
        return False
    try:
        resultat = await pool.enqueue_job(NOM_TACHE, job_id, _job_id=f"export:{job_id}:{tentative}")
    except Exception as exc:  # noqa: BLE001
        # Le pool est mis au rebut, pas seulement l'appel. Un Redis redemarre
        # laisse un pool en cache dont toutes les connexions sont mortes : sans
        # cette invalidation, TOUTES les publications suivantes echouent
        # jusqu'au redemarrage du worker gunicorn, et chaque export attend le
        # balayage. La prochaine publication en reconstruira un.
        global _pool
        _pool = None
        logger.warning(
            "Publication du job %s impossible (%s) : pool rejete, le job reste en file.",
            job_id,
            exc,
        )
        return False
    if resultat is None:
        # arq refuse un identifiant déjà connu : le message est déjà passé.
        logger.info("Job %s (tentative %s) déjà publié.", job_id, tentative)
        return True
    logger.info("EXPORT_JOB_PUBLIE job=%s tentative=%s", job_id, tentative)
    return True
