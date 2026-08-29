"""Génération des exports hors du chemin HTTP.

Ce module ne connaît pas arq : il expose des coroutines ordinaires, et
`app/workers/arq_worker.py` les branche sur la file. La séparation n'est pas
cosmétique — elle permet de tester la logique de reprise et de cloisonnement
sans installer ni lancer quoi que ce soit.

Ce qui est réutilisé tel quel, et c'est le point : `construire_classeur_budget`
est LA fonction qu'appelle aussi `GET /exports/budget`. Le chemin asynchrone ne
réimplémente aucune règle métier, donc il ne peut pas en diverger.

Cf. docs/architecture-exports-asynchrones-20260828.md, §4.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import anyio
from fastapi import HTTPException
from openpyxl import Workbook
from sqlalchemy import select, update
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.tenant_context import get_current_tenant_id
from app.models.export_job import (
    STATUT_ECHOUE,
    STATUT_EN_COURS,
    STATUT_EN_FILE,
    STATUT_EXPIRE,
    STATUT_TERMINE,
    ExportJob,
)
from app.models.organisation import Organisation
from app.services.export_jobs import (
    CheminArtefactInvalide,
    chemin_absolu,
    chemin_relatif_artefact,
    horodatage_peremption,
)
# `_volumetrie` est privé, et importé quand même : `row_count` doit compter
# EXACTEMENT ce que compte la trace `EXPORT_WORKBOOK` (utils/excel_io.py). Deux
# comptages différents du même classeur, c'est la certitude qu'un jour on
# comparera le nombre affiché à l'utilisateur avec celui des journaux pour
# conclure à un bug qui n'existe pas.
from app.utils.excel_io import _volumetrie, save_workbook_sync
from app.workers.tenant_session import (
    ContexteTenantManquant,
    session_tenant,
    session_technique,
)

logger = logging.getLogger("onec_cpk_api.worker_exports")

# Identité du processus, écrite sur le job pendant son exécution. Sert au
# diagnostic quand un job reste bloqué : on sait quel conteneur interroger.
IDENTITE_WORKER = f"{socket.gethostname()}:{os.getpid()}"

# Le bail est renouvelé trois fois plus souvent qu'il n'expire : deux
# renouvellements peuvent être manqués (pause GC, latence base) sans que le job
# soit déclaré mort et repris en parallèle par un autre worker.
INTERVALLE_RENOUVELLEMENT_S = max(10, settings.export_job_lease_seconds // 3)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Construction, par type ───────────────────────────────────────────────────


async def construire(db: AsyncSession, job: ExportJob) -> tuple[Workbook, str]:
    """Aiguille vers le constructeur du type demande, avec ses filtres.

    L'import est fait ICI et non en tete de module : `exports.py` importe le
    routeur FastAPI et la moitie des modeles, et le worker n'a besoin de tout
    cela qu'au moment de construire. Cela garde aussi le module importable dans
    un test qui ne veut verifier que la reprise sur incident.

    LES FILTRES SONT VERIFIES AVANT D'ETRE TRANSMIS. Un parametre stocke que le
    constructeur n'accepte pas fait echouer le job avec un message explicite,
    au lieu d'etre ignore. Un filtre silencieusement perdu produirait un
    classeur FAUX — davantage de lignes que ce qui a ete demande, donc des
    donnees qu'un utilisateur n'avait pas le droit de voir dans le cas d'un
    filtre de service — et rien ne le signalerait. Le cas se presente des qu'un
    job survit a un deploiement qui a change la signature d'un export.

    `seuil_bascule` n'est jamais transmis : dans le worker il doit rester None,
    sinon un job depassant le seuil se remettrait en file lui-meme, sans fin.
    """
    from app.api.v1.endpoints.exports import (
        construire_classeur_budget,
        construire_classeur_encaissements,
        construire_classeur_experts,
        construire_classeur_requisitions,
        construire_classeur_sorties_fonds,
    )

    constructeurs = {
        "budget": construire_classeur_budget,
        "encaissements": construire_classeur_encaissements,
        "sorties-fonds": construire_classeur_sorties_fonds,
        "requisitions": construire_classeur_requisitions,
        "experts-comptables": construire_classeur_experts,
    }
    fabrique = constructeurs.get(job.type)
    if fabrique is None:
        raise ValueError(f"Type d'export non pris en charge par le worker : {job.type}")

    params: dict[str, Any] = job.params or {}
    acceptes = set(inspect.signature(fabrique).parameters) - {
        "db",
        "organisation_id",
        "seuil_bascule",
    }
    inconnus = sorted(set(params) - acceptes)
    if inconnus:
        raise ValueError(
            f"Filtres inconnus pour l'export {job.type} : {', '.join(inconnus)}. "
            "Ce job a vraisemblablement ete cree par une version anterieure du code."
        )
    return await fabrique(db, job.organisation_id, **params)


def _ecrire_artefact(wb: Workbook, destination: Path) -> int:
    """Sérialise le classeur et l'écrit de façon atomique. Rend sa taille.

    Écriture dans un `.tmp` puis `os.replace` : le renommage est atomique sur le
    même système de fichiers. Sans cela, l'endpoint de téléchargement — qui ne
    teste que l'existence du fichier — pourrait servir un classeur à moitié
    écrit à quelqu'un qui interroge au mauvais moment.

    À n'appeler que depuis un thread : `save_workbook_sync` est du CPU Python
    pur et gèlerait la boucle d'événements du worker.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    flux = save_workbook_sync(wb)
    donnees = flux.getvalue()
    temporaire = destination.with_name(destination.name + ".tmp")
    with open(temporaire, "wb") as fichier:
        fichier.write(donnees)
    os.replace(temporaire, destination)
    return len(donnees)


# ── Bail ─────────────────────────────────────────────────────────────────────


# Le job n'est « le nôtre » que tant que ces trois conditions tiennent. Elles
# sont réutilisées telles quelles par le renouvellement du bail ET par l'écriture
# du résultat : c'est la même question posée deux fois, et deux formulations
# divergentes seraient une porte ouverte à ce que l'une des deux oublie
# `worker_id`.
def _condition_propriete(job_id: uuid.UUID):
    return (
        ExportJob.id == job_id,
        ExportJob.status == STATUT_EN_COURS,
        ExportJob.worker_id == IDENTITE_WORKER,
    )


async def _renouveler_bail(job_id: uuid.UUID) -> None:
    """Repousse `lease_until` tant que le job tourne, et NOUS appartient encore.

    Tourne dans sa propre session : deux coroutines ne peuvent pas se partager
    une `AsyncSession` sans corrompre son état. C'est la deuxième (et dernière)
    connexion que le worker prend au pool pendant un job.

    La condition sur `worker_id` n'est pas décorative. Sans elle, un worker dont
    le bail a déjà expiré — job repris par le balayage, puis réservé par un
    second worker — continuerait de repousser le bail du NOUVEAU propriétaire.
    La mort de ce second worker deviendrait alors invisible : le balayage ne
    verrait jamais le bail expirer, et le job resterait `RUNNING` pour toujours,
    exactement le blocage que le bail existe pour empêcher. Quand la mise à jour
    ne touche plus rien, la boucle s'arrête : il n'y a plus rien à renouveler.
    """
    while True:
        try:
            await asyncio.sleep(INTERVALLE_RENOUVELLEMENT_S)
            async with session_technique() as db:
                resultat = await db.execute(
                    update(ExportJob)
                    .where(*_condition_propriete(job_id))
                    .values(lease_until=utcnow() + timedelta(seconds=settings.export_job_lease_seconds))
                )
                await db.commit()
                if resultat.rowcount == 0:
                    logger.warning(
                        "EXPORT_JOB_BAIL_PERDU job=%s : le job ne nous appartient plus.", job_id
                    )
                    return
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - un bail non renouvelé se rattrape au balayage
            logger.warning("Renouvellement du bail impossible pour %s", job_id, exc_info=True)


# ── Tâche principale ─────────────────────────────────────────────────────────


async def generer_export(job_id: str) -> str:
    """Produit l'artefact d'un job. Rend un mot d'état, pour les journaux d'arq.

    Le déroulé est volontairement en deux temps :

    1. une session TECHNIQUE (non filtrée) lit et réserve la ligne `export_jobs`
       par clé primaire — on ne peut pas poser de contexte tenant avant de
       savoir à quelle organisation le job appartient ;
    2. tout le reste se passe dans une session TENANT, qui refuse de s'ouvrir
       sans organisation.

    C'est la première des trois barrières du §4.1 : hors HTTP, l'absence de
    contexte doit lever, pas se replier sur « toutes les organisations ».
    """
    identifiant = uuid.UUID(str(job_id))

    # --- 1. Réservation atomique -------------------------------------------
    async with session_technique() as db:
        job = (await db.execute(select(ExportJob).where(ExportJob.id == identifiant))).scalar_one_or_none()
        if job is None:
            logger.error("EXPORT_JOB_INTROUVABLE job=%s", identifiant)
            return "introuvable"
        if job.status != STATUT_EN_FILE:
            # Message rejoué, ou job déjà pris par un autre worker. Ne rien
            # faire est le bon comportement : la file est « au moins une fois ».
            logger.info("EXPORT_JOB_IGNORE job=%s statut=%s", identifiant, job.status)
            return f"ignore:{job.status}"

        bail = utcnow() + timedelta(seconds=settings.export_job_lease_seconds)
        reserve = await db.execute(
            update(ExportJob)
            .where(ExportJob.id == identifiant, ExportJob.status == STATUT_EN_FILE)
            .values(
                status=STATUT_EN_COURS,
                started_at=utcnow(),
                attempts=ExportJob.attempts + 1,
                lease_until=bail,
                worker_id=IDENTITE_WORKER,
                progress=5,
                error_code=None,
                error_message=None,
            )
            .returning(ExportJob.id)
        )
        if reserve.scalar_one_or_none() is None:
            # Course perdue : un autre worker a réservé entre le SELECT et
            # l'UPDATE. Le `WHERE status = QUEUED` est ce qui rend ce cas
            # inoffensif — deux workers ne peuvent pas produire le même job.
            await db.rollback()
            logger.info("EXPORT_JOB_DEJA_RESERVE job=%s", identifiant)
            return "deja_reserve"
        await db.commit()
        organisation_id = job.organisation_id
        type_export = job.type

    logger.info("EXPORT_JOB_DEBUT job=%s type=%s org=%s", identifiant, type_export, organisation_id)
    renouvellement = asyncio.create_task(_renouveler_bail(identifiant))
    try:
        # --- 2. Génération, sous contexte tenant ---------------------------
        async with session_tenant(organisation_id) as db:
            job = (await db.execute(select(ExportJob).where(ExportJob.id == identifiant))).scalar_one()

            org_uuid = (
                await db.execute(select(Organisation.uuid).where(Organisation.id == organisation_id))
            ).scalar_one_or_none()
            if org_uuid is None:
                # Le listener filtre `Organisation` sur `id == tenant_id` : ne
                # rien trouver ici signifie que le contexte ne correspond pas au
                # job. On refuse plutôt que d'écrire un fichier au hasard.
                raise ContexteTenantManquant(
                    f"Organisation {organisation_id} introuvable sous le contexte tenant courant."
                )

            wb, nom_fichier = await construire(db, job)

            # Troisième barrière du §4.1, dans la limite de ce qu'elle prouve :
            # le contexte tenant est TOUJOURS celui du job au moment d'écrire.
            # Elle n'atteste pas que chaque requête de construction a filtré —
            # c'est le rôle du listener — mais elle attrape le contexte qui
            # aurait dérivé en cours de route, ce qu'aucun filtre ne verrait.
            if get_current_tenant_id() != organisation_id:
                raise ContexteTenantManquant(
                    f"Contexte tenant perdu pendant la génération du job {identifiant}."
                )

            # `row_count` et `progress` sont déclarés sur le modèle et rendus
            # au client à chaque interrogation : rien ne les alimentait. La
            # barre restait donc figée à 5 % du premier SELECT à la dernière
            # cellule, et le nombre de lignes n'était jamais qu'un `null`. Ce
            # point d'étape est posé AVANT la sérialisation, qui pèse ~80 % du
            # coût d'un export (utils/excel_io.py) : l'écrire après n'aurait
            # informé personne.
            await db.execute(
                update(ExportJob)
                .where(*_condition_propriete(identifiant))
                .values(row_count=_volumetrie(wb)[1], progress=60)
            )
            await db.commit()

            relatif = chemin_relatif_artefact(org_uuid, identifiant)
            taille = await anyio.to_thread.run_sync(_ecrire_artefact, wb, chemin_absolu(relatif))

            fini = utcnow()
            # L'écriture du résultat est CONDITIONNÉE à la propriété du job,
            # exactement comme celle de l'échec. Le cas n'est pas théorique : un
            # bail non renouvelé pendant une génération longue fait repartir le
            # job en file, un second worker le réserve, et deux exécutions
            # courent en parallèle. Sans cette condition, la première à finir
            # écrirait `DONE` par-dessus le `RUNNING` du propriétaire courant,
            # qui écrirait `DONE` à son tour : `worker_id`, `attempts` et
            # `started_at` décriraient alors une exécution, `file_size` une
            # autre.
            ecrit = await db.execute(
                update(ExportJob)
                .where(*_condition_propriete(identifiant))
                .values(
                    status=STATUT_TERMINE,
                    progress=100,
                    file_path=relatif,
                    file_name=nom_fichier,
                    file_size=taille,
                    finished_at=fini,
                    expires_at=horodatage_peremption(fini),
                    lease_until=None,
                )
                .returning(ExportJob.id)
            )
            gagne = ecrit.scalar_one_or_none() is not None
            await db.commit()
            if not gagne:
                # Le classeur vient d'être écrit à l'emplacement que le
                # propriétaire actuel utilisera lui aussi — même job, mêmes
                # paramètres, même chemin, et `os.replace` est atomique. Le
                # laisser ne coûte rien ; l'effacer risquerait d'emporter le
                # sien.
                logger.warning(
                    "EXPORT_JOB_REPRIS_AILLEURS job=%s : le résultat de cette exécution est ignoré.",
                    identifiant,
                )
                return "repris_ailleurs"

        logger.info(
            "EXPORT_JOB_TERMINE job=%s type=%s org=%s octets=%d",
            identifiant,
            type_export,
            organisation_id,
            taille,
        )
        return "termine"

    except Exception as exc:  # noqa: BLE001 - tout échec doit devenir un état lisible
        logger.exception("EXPORT_JOB_ECHEC job=%s type=%s", identifiant, type_export)
        await _marquer_echec(identifiant, exc)
        return "echec"
    finally:
        renouvellement.cancel()
        try:
            await renouvellement
        except asyncio.CancelledError:
            pass


MESSAGE_ECHEC_GENERIQUE = (
    "La génération de cet export a échoué. "
    "Réessayez ; si le problème persiste, signalez-le à votre administrateur."
)


def _traduire_echec(exc: BaseException) -> tuple[str, str]:
    """Rend `(error_code, error_message)` à partir de l'exception attrapée.

    Les 4xx levées par le chemin de construction sont DÉJÀ des messages écrits
    pour l'utilisateur, et le chemin synchrone les lui rend tels quels : « Aucun
    exercice budgétaire disponible », ou le refus de plafond qui porte les deux
    nombres et l'action qui débloque. Les remplacer par « réessayez » supprime
    la seule information qui permet d'agir — et le réflexe observé dans les tirs
    de charge est précisément de recliquer à l'identique.

    Tout le reste reste générique : `repr(exc)` ferait fuiter des noms de tables
    et des fragments de SQL dans une interface. Le détail technique va dans les
    journaux, où il a sa place. Les 5xx suivent le régime générique : une erreur
    serveur ne dit rien d'actionnable à celui qui la lit.
    """
    if isinstance(exc, HTTPException) and 400 <= exc.status_code < 500:
        return f"HTTP_{exc.status_code}"[:60], str(exc.detail)[:500]
    return type(exc).__name__[:60], MESSAGE_ECHEC_GENERIQUE


async def _marquer_echec(job_id: uuid.UUID, exc: BaseException) -> None:
    """Écrit l'échec sur le job, sans jamais réessayer ici.

    POURQUOI PAS DE REPRISE À CET ENDROIT : une exception attrapée signifie que
    le worker est vivant et que le code a échoué — mauvais paramètres, données
    incohérentes, plafond dépassé. Rejouer produirait la même erreur, trois
    fois plus vite. La reprise ne concerne QUE la mort du worker, qui par
    définition ne passe pas par ce bloc : c'est le balayage des baux expirés qui
    la traite (§4.4).
    """
    code, message = _traduire_echec(exc)
    async with session_technique() as db:
        await db.execute(
            update(ExportJob)
            # Même condition de propriété que l'écriture du succès : si le
            # balayage a remis ce job en file (bail expiré pendant que
            # l'exception remontait) et qu'un autre worker l'a réservé, sa
            # reprise ne doit pas être écrasée par notre échec définitif.
            .where(*_condition_propriete(job_id))
            .values(
                status=STATUT_ECHOUE,
                finished_at=utcnow(),
                lease_until=None,
                error_code=code,
                error_message=message,
            )
        )
        await db.commit()


# Code SQLSTATE PostgreSQL d'une table inexistante.
CODE_TABLE_ABSENTE = "42P01"


def _table_absente(exc: BaseException) -> bool:
    """Vrai si l'erreur est « la table n'existe pas », et rien d'autre.

    On lit le SQLSTATE plutot que le message : le texte depend de la locale du
    serveur, le code non. Et on ne se contente PAS d'attraper ProgrammingError,
    qui couvre aussi une colonne absente ou une faute de syntaxe — des erreurs
    qui doivent rester bruyantes.
    """
    return getattr(getattr(exc, "orig", None), "sqlstate", None) == CODE_TABLE_ABSENTE


async def balayer_baux_expires(republier=None) -> int:
    """Balayage tolerant a l'absence de la table.

    POURQUOI CETTE TOLERANCE. Le worker ne depend que de `db` et `redis` sains,
    pas du backend : rien ne garantit qu'`alembic upgrade` ait deja tourne quand
    son cron se declenche — et ce cron se declenche a la minute. Sans cette
    garde, le premier demarrage d'une pile neuve ecrit une trace complete toutes
    les soixante secondes jusqu'a ce que la migration passe. Le bruit finit par
    couvrir les incidents reels, ce qui est pire que le probleme.

    La tolerance est etroite a dessein : ce SQLSTATE-la, et rien d'autre.
    """
    try:
        return await _balayer_baux_expires(republier)
    except ProgrammingError as exc:
        if not _table_absente(exc):
            raise
        logger.warning("Table export_jobs absente : balayage reporte, en attente de la migration.")
        return 0


async def purger_artefacts_perimes() -> int:
    """Purge tolerante a l'absence de la table (meme raison que ci-dessus)."""
    try:
        return await _purger_artefacts_perimes()
    except ProgrammingError as exc:
        if not _table_absente(exc):
            raise
        logger.warning("Table export_jobs absente : purge reportee, en attente de la migration.")
        return 0


# ── Balayages ────────────────────────────────────────────────────────────────
#
# Ces deux traitements sont TRANSVERSES aux organisations, et c'est assumé : ils
# ne lisent que la table `export_jobs`, par statut et par horodatage, et ne
# touchent à aucune donnée métier. Les faire tourner par organisation
# supposerait de les réveiller autant de fois qu'il y a de tenants pour ne rien
# trouver la plupart du temps.


async def _balayer_baux_expires(republier=None) -> int:
    """Reprend les jobs dont le worker est mort, et réconcilie la file.

    Deux cas, un seul balayage :

    1. `RUNNING` dont le bail a expiré — le worker qui le tenait n'est plus là.
       Le générateur a DÉJÀ été tué par l'OOM-killer pendant la campagne du
       27/08 : ce n'est pas une hypothèse. Sous le plafond de tentatives, le job
       repart en file ; au-delà, il échoue avec un message exploitable.
    2. `QUEUED` plus vieux que le bail — le message Redis s'est perdu (flush,
       redémarrage sans persistance). C'est ce qui rend acceptable de traiter
       Redis comme faillible : rien n'est perdu, tout est repris.

    `republier` est injecté pour que le test n'ait pas besoin d'un Redis.
    """
    maintenant = utcnow()
    repris = 0
    async with session_technique() as db:
        expires = (
            await db.execute(
                select(ExportJob).where(
                    ExportJob.status == STATUT_EN_COURS,
                    ExportJob.lease_until.is_not(None),
                    ExportJob.lease_until < maintenant,
                )
            )
        ).scalars().all()

        for job in expires:
            if job.attempts < settings.export_job_max_attempts:
                job.status = STATUT_EN_FILE
                job.lease_until = None
                job.worker_id = None
                job.progress = 0
                # `attempts + 1` et non `attempts` : c'est le numéro de la
                # tentative qui VA être publiée, et celui qui apparaît dans
                # l'identifiant arq. Journaliser l'autre obligerait, en pleine
                # analyse d'incident, à faire la conversion de tête.
                logger.warning(
                    "EXPORT_JOB_REPRIS job=%s tentative=%s (bail expiré)", job.id, job.attempts + 1
                )
                repris += 1
            else:
                job.status = STATUT_ECHOUE
                job.finished_at = maintenant
                job.lease_until = None
                job.error_code = "BAIL_EXPIRE"
                job.error_message = (
                    "La génération a été interrompue à plusieurs reprises. "
                    "Réduisez la période demandée, ou signalez-le à votre administrateur."
                )
                logger.error("EXPORT_JOB_ABANDONNE job=%s tentatives=%s", job.id, job.attempts)

        limite_file = maintenant - timedelta(seconds=settings.export_job_lease_seconds)
        requete_orphelins = select(ExportJob).where(
            ExportJob.status == STATUT_EN_FILE,
            ExportJob.created_at < limite_file,
        )
        deja_traites = {job.id for job in expires}
        if deja_traites:
            # SANS CETTE EXCLUSION, chaque job repris ci-dessus est compté et
            # republié DEUX FOIS par le même balayage : l'autoflush de
            # SQLAlchemy écrit le passage à `QUEUED` avant d'exécuter ce SELECT,
            # et un job dont le bail vient d'expirer a par construction un
            # `created_at` plus vieux que la durée du bail. Il retombait donc
            # systématiquement dans les « orphelins », gonflant le compte rendu
            # et publiant un second message pour la même tentative.
            requete_orphelins = requete_orphelins.where(ExportJob.id.not_in(deja_traites))
        orphelins = (await db.execute(requete_orphelins)).scalars().all()

        await db.commit()

        a_republier = [(job.id, job.attempts + 1) for job in expires if job.status == STATUT_EN_FILE]
        a_republier += [(job.id, job.attempts + 1) for job in orphelins]

    if republier is not None:
        for job_id, tentative in a_republier:
            await republier(str(job_id), tentative)
    return repris + len(orphelins)


async def _purger_artefacts_perimes() -> int:
    """Supprime les classeurs arrivés à péremption, garde la ligne de job.

    Le fichier part, l'historique reste : l'utilisateur doit pouvoir constater
    qu'un export a existé et qu'il a expiré, plutôt que de le voir disparaître
    sans explication. Ces classeurs portent des données financières nominatives
    et n'ont pas à s'accumuler sur disque au-delà de leur utilité.
    """
    maintenant = utcnow()
    purges = 0
    async with session_technique() as db:
        perimes = (
            await db.execute(
                select(ExportJob).where(
                    ExportJob.status == STATUT_TERMINE,
                    ExportJob.expires_at.is_not(None),
                    ExportJob.expires_at < maintenant,
                )
            )
        ).scalars().all()

        for job in perimes:
            if job.file_path:
                try:
                    chemin = chemin_absolu(job.file_path)
                except CheminArtefactInvalide:
                    # La purge SUPPRIME : c'est l'usage le plus dangereux de
                    # `file_path`. Une ligne dont le chemin ne se confine pas
                    # sous la racine d'uploads est laissee intacte et signalee,
                    # jamais suivie.
                    logger.error(
                        "EXPORT_CHEMIN_INVALIDE job=%s chemin=%r : purge refusee",
                        job.id,
                        job.file_path,
                    )
                    continue
                try:
                    chemin.unlink(missing_ok=True)
                except OSError:
                    # Un fichier qu'on n'arrive pas à supprimer ne doit pas
                    # bloquer la purge des autres : on le signale et on continue.
                    logger.warning("Suppression impossible : %s", chemin, exc_info=True)
                    continue
            job.status = STATUT_EXPIRE
            job.file_path = None
            purges += 1

        await db.commit()
    if purges:
        logger.info("EXPORT_ARTEFACTS_PURGES nombre=%d", purges)
    return purges
