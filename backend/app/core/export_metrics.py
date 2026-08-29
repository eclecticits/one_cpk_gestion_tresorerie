"""Métriques Prometheus des exports, dérivées de la base et non de la mémoire.

POURQUOI DE LA BASE. Les jobs sont produits par le conteneur `exports-worker`,
et `/metrics` est servi par le backend HTTP : deux processus, deux conteneurs.
Des compteurs tenus en mémoire par le worker ne seraient jamais visibles à
l'endroit où Prometheus vient les chercher, et les publier depuis le worker
supposerait un serveur HTTP de plus ou un pushgateway.

La table `export_jobs` porte déjà tout ce qu'il faut — c'est la conséquence
directe du choix d'architecture « PostgreSQL = la vérité » : durée
(`started_at` → `finished_at`), volumétrie (`row_count`), taille d'artefact,
statut, horodatages. Une requête d'agrégat au moment du scrape suffit.

EFFET DE BORD HEUREUX. Des valeurs lues en base sont IDENTIQUES dans les quatre
workers gunicorn. Le défaut classique du scrape multi-processus — Prometheus
tombe sur un worker au hasard et lit ses compteurs à lui — ne s'applique donc
pas à ces séries : n'importe quel worker répond la même chose, la bonne.

CE QUI N'EST PAS LIVRÉ. Le plan mentionnait « durée, lignes, mémoire ». La
mémoire par job n'est mesurée nulle part : rien ne l'échantillonne pendant la
génération, et publier une valeur inventée serait pire que son absence. Le seul
chiffre dont on dispose est global (+310 Mo de RSS pour un export, mesuré au
`docker stats`), et il appartient au conteneur, pas au job.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from prometheus_client import Gauge
from sqlalchemy import Numeric, cast, func, select
from sqlalchemy.exc import ProgrammingError

from app.core.config import settings
from app.models.export_job import STATUT_EN_FILE, STATUT_TERMINE, ExportJob

logger = logging.getLogger("onec_cpk_api.export_metrics")

# Code SQLSTATE d'une table inexistante : la migration peut ne pas être passée.
CODE_TABLE_ABSENTE = "42P01"

_PREFIXE = "onec_export"

JOBS_PAR_ETAT = Gauge(
    f"{_PREFIXE}_jobs",
    "Nombre de jobs d'export, par type et par état (instantané, lu en base).",
    ["type", "etat"],
)
# LA métrique d'alerte. Si le worker meurt, la profondeur de file monte et
# l'âge du plus vieux job en attente grimpe sans redescendre — c'est ce couple
# qui distingue « beaucoup de demandes » de « plus personne ne les traite ».
ATTENTE_MAX_SECONDES = Gauge(
    f"{_PREFIXE}_attente_max_secondes",
    "Âge du plus ancien job encore en file. Monte indéfiniment si aucun worker ne consomme.",
)
DUREE_MOYENNE_SECONDES = Gauge(
    f"{_PREFIXE}_duree_moyenne_secondes",
    "Durée moyenne de génération sur les 24 dernières heures, par type.",
    ["type"],
)
DUREE_MAX_SECONDES = Gauge(
    f"{_PREFIXE}_duree_max_secondes",
    "Durée maximale de génération sur les 24 dernières heures, par type.",
    ["type"],
)
LIGNES_MOYENNES = Gauge(
    f"{_PREFIXE}_lignes_moyennes",
    "Nombre moyen de lignes des exports produits sur 24 h, par type. "
    "Sert à placer EXPORT_ASYNC_ROW_THRESHOLD sur une distribution réelle.",
    ["type"],
)
ARTEFACTS_OCTETS = Gauge(
    f"{_PREFIXE}_artefacts_octets",
    "Octets occupés sur disque par les artefacts encore disponibles. "
    "Sert à vérifier que la purge de rétention fait bien son travail.",
)

# Instantané mémorisé : Prometheus peut scraper toutes les 15 s, et plusieurs
# workers peuvent être scrapés de front. Sans ce cache, chaque scrape
# déclencherait deux agrégats par worker.
_dernier_calcul: float = 0.0

FENETRE_HEURES = 24


def _fenetre_recente() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=FENETRE_HEURES)



async def rafraichir_depuis_base() -> bool:
    """Ouvre une session et rafraîchit. C'est ce que la route /metrics appelle.

    `session_technique` est réutilisée plutôt que d'ouvrir une session non
    filtrée à la main : son module la déclare comme le SEUL chemin autorisé vers
    une session sans cloisonnement, et en écrire un second ici viderait cette
    règle de son sens. Ces métriques sont transverses aux organisations par
    nature — elles décrivent la plateforme, pas un tenant — et ne lisent que des
    agrégats de `export_jobs`, jamais une donnée métier.
    """
    from app.workers.tenant_session import session_technique

    async with session_technique() as db:
        return await rafraichir(db)


async def rafraichir(db: Any) -> bool:
    """Recalcule les jauges depuis la base. Rend False si rien n'a été fait.

    Tolère l'absence de la table — et uniquement cela : le backend peut
    démarrer avant que la migration `20260828_export_jobs` ne soit appliquée, et
    `/metrics` ne doit pas répondre 500 pour autant. Une autre erreur SQL reste
    bruyante, comme dans les balayages du worker.
    """
    global _dernier_calcul
    maintenant = time.monotonic()
    if maintenant - _dernier_calcul < settings.metrics_export_refresh_seconds:
        return False

    age = func.extract("epoch", func.now() - ExportJob.created_at)
    duree = func.extract("epoch", ExportJob.finished_at - ExportJob.started_at)

    try:
        etats = (
            await db.execute(
                select(ExportJob.type, ExportJob.status, func.count(ExportJob.id))
                .group_by(ExportJob.type, ExportJob.status)
            )
        ).all()

        attente = (
            await db.execute(
                select(func.max(age)).where(ExportJob.status == STATUT_EN_FILE)
            )
        ).scalar_one_or_none()

        recents = (
            await db.execute(
                select(
                    ExportJob.type,
                    func.avg(duree),
                    func.max(duree),
                    func.avg(cast(ExportJob.row_count, Numeric)),
                )
                .where(
                    ExportJob.started_at.is_not(None),
                    # Fenetre calculee en Python plutot qu'en `interval '24 hours'` :
                    # pas de SQL propre a PostgreSQL, et une borne qu'un test peut
                    # fixer. Vingt-quatre heures parce que ces jauges servent a
                    # regler EXPORT_ASYNC_ROW_THRESHOLD sur l'usage recent, pas a
                    # decrire l'historique.
                    ExportJob.finished_at >= _fenetre_recente(),
                )
                .group_by(ExportJob.type)
            )
        ).all()

        octets = (
            await db.execute(
                select(func.coalesce(func.sum(ExportJob.file_size), 0)).where(
                    ExportJob.status == STATUT_TERMINE,
                    ExportJob.file_path.is_not(None),
                )
            )
        ).scalar_one()
    except ProgrammingError as exc:
        if getattr(getattr(exc, "orig", None), "sqlstate", None) != CODE_TABLE_ABSENTE:
            raise
        logger.warning("Table export_jobs absente : métriques d'export non publiées.")
        _dernier_calcul = maintenant
        return False

    # `clear()` avant réécriture : un couple (type, état) qui n'a plus aucune
    # ligne doit DISPARAÎTRE, pas rester figé à sa dernière valeur. Une jauge
    # oubliée à 12 jobs en file est exactement le genre de fausse alerte qui
    # apprend à ignorer les alertes.
    JOBS_PAR_ETAT.clear()
    for type_export, etat, nombre in etats:
        JOBS_PAR_ETAT.labels(type=type_export, etat=etat).set(nombre)

    ATTENTE_MAX_SECONDES.set(float(attente or 0))
    ARTEFACTS_OCTETS.set(float(octets or 0))

    DUREE_MOYENNE_SECONDES.clear()
    DUREE_MAX_SECONDES.clear()
    LIGNES_MOYENNES.clear()
    for type_export, moyenne, maximum, lignes in recents:
        if moyenne is not None:
            DUREE_MOYENNE_SECONDES.labels(type=type_export).set(float(moyenne))
        if maximum is not None:
            DUREE_MAX_SECONDES.labels(type=type_export).set(float(maximum))
        if lignes is not None:
            LIGNES_MOYENNES.labels(type=type_export).set(float(lignes))

    _dernier_calcul = maintenant
    return True
