"""Cycle de vie d'un job d'export : soumission, déduplication, artefact.

Ce module ne construit aucun classeur. Il décide *si* un job doit exister, *où*
son fichier ira, et *jusqu'à quand* il vivra. La génération elle-même reste dans
`app/api/v1/endpoints/exports.py`, appelée à l'identique par l'endpoint
synchrone et par le worker — c'est la propriété qui garantit que les deux
chemins produisent le même fichier.

Cf. docs/architecture-exports-asynchrones-20260828.md.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.export_job import (
    STATUT_EN_FILE,
    STATUT_TERMINE,
    STATUTS_ACTIFS,
    ExportJob,
)

logger = logging.getLogger("onec_cpk_api.export_jobs")

# Types que le worker sait produire, dans l'ordre de bascule recommandé : du
# plus coûteux au moins coûteux, pour que le premier gain soit le plus gros.
# Cet ordre est celui du §6 du document d'architecture ; il n'a aucun effet
# technique, c'est une consigne d'exploitation lisible depuis le code.
#
# Être ici ne suffit PAS à basculer : il faut aussi que le type soit nommé dans
# EXPORT_ASYNC_TYPES, et que le volume dépasse EXPORT_ASYNC_ROW_THRESHOLD.
TYPES_SUPPORTES: tuple[str, ...] = (
    "requisitions",
    "encaissements",
    "sorties-fonds",
    "experts-comptables",
    "budget",
)


def racine_uploads() -> Path:
    """Racine du stockage des fichiers, identique à celle de secure_uploads.

    La résolution est DUPLIQUÉE de `app/api/v1/endpoints/secure_uploads.py`
    plutôt qu'importée : un service (donc le worker) ne doit pas dépendre d'un
    module d'endpoints FastAPI. Le risque de divergence est réel, et c'est
    pourquoi `tests/test_export_jobs.py` vérifie que les deux valeurs coïncident.
    En production les deux lisent UPLOAD_DIR, la question ne se pose pas.
    """
    if settings.upload_dir:
        return Path(os.path.abspath(settings.upload_dir))
    return Path(os.path.abspath(Path(__file__).resolve().parents[2] / "uploads"))


def types_asynchrones() -> set[str]:
    """Types routés vers la file, d'après EXPORT_ASYNC_TYPES.

    Vide par défaut : le drapeau est fermé et rien ne change. C'est ce qui rend
    la bascule réversible type par type, sans redéploiement de code.
    """
    brut = (settings.export_async_types or "").strip()
    if not brut:
        return set()
    demandes = {p.strip().lower() for p in brut.split(",") if p.strip()}
    inconnus = demandes - set(TYPES_SUPPORTES)
    if inconnus:
        # Un type mal orthographié ne doit pas basculer silencieusement en
        # synchrone : on le dit, une fois, à chaque appel qui le rencontre.
        logger.warning(
            "EXPORT_ASYNC_TYPES contient des types que le worker ne sait pas produire : %s",
            ", ".join(sorted(inconnus)),
        )
    return demandes & set(TYPES_SUPPORTES)


def empreinte_params(organisation_id: int, type_export: str, params: dict[str, Any]) -> str:
    """Empreinte stable de (organisation, type, filtres), pour la déduplication.

    `sort_keys` rend l'empreinte indépendante de l'ordre des clés, et
    `default=str` couvre les dates et Decimal qui traîneraient dans les filtres.
    L'organisation entre dans l'empreinte bien que les requêtes la filtrent
    déjà : deux organisations ne partageront jamais un artefact, même si le
    filtre venait à être oublié quelque part.
    """
    charge = json.dumps(
        {"org": organisation_id, "type": type_export, "params": params},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(charge.encode("utf-8")).hexdigest()


def chemin_relatif_artefact(organisation_uuid: uuid.UUID | str, job_id: uuid.UUID | str) -> str:
    """`tenants/<uuid organisation>/exports/<id job>.xlsx`, relatif à UPLOAD_DIR.

    L'arborescence par UUID d'organisation est celle que `secure_uploads.py`
    contrôle déjà : `_extract_tenant_uuid` lit le second segment et le compare à
    l'organisation du jeton. Ranger les artefacts ailleurs reviendrait à écrire
    un second contrôle d'appartenance, donc à avoir deux endroits où se tromper.
    """
    return f"tenants/{organisation_uuid}/exports/{job_id}.xlsx"


def chemin_absolu(chemin_relatif: str) -> Path:
    return racine_uploads() / chemin_relatif


def horodatage_peremption(depuis: datetime | None = None) -> datetime:
    """Date de suppression de l'artefact (pas du job)."""
    base = depuis or datetime.now(timezone.utc)
    return base + timedelta(days=settings.export_job_retention_days)


async def _artefact_reutilisable(
    db: AsyncSession,
    *,
    organisation_id: int,
    type_export: str,
    empreinte: str,
) -> ExportJob | None:
    """Un job terminé, identique, récent, dont le fichier est encore là.

    Le motif « l'utilisateur clique cinq fois parce que rien ne se passe » a été
    observé tel quel dans les tirs de charge, et il coûte cinq fois le prix. La
    fenêtre est courte (EXPORT_DEDUP_WINDOW_MINUTES) : au-delà, les données ont
    pu bouger et l'utilisateur attend un classeur à jour, pas une archive.
    """
    fenetre = datetime.now(timezone.utc) - timedelta(minutes=settings.export_dedup_window_minutes)
    resultat = await db.execute(
        select(ExportJob)
        .where(
            # Filtre explicite en plus du listener : ce module est aussi appelé
            # depuis le worker, où une erreur de contexte ne doit pas pouvoir
            # rendre l'artefact d'une autre organisation.
            ExportJob.organisation_id == organisation_id,
            ExportJob.type == type_export,
            ExportJob.params_hash == empreinte,
            ExportJob.status == STATUT_TERMINE,
            ExportJob.created_at >= fenetre,
            ExportJob.file_path.is_not(None),
        )
        .order_by(ExportJob.created_at.desc())
        .limit(1)
    )
    candidat = resultat.scalar_one_or_none()
    if candidat is None:
        return None
    # La base dit que le fichier existe ; le disque a le dernier mot. Un volume
    # remonté vide, une purge manuelle, et on rendrait un 404 à l'utilisateur en
    # lui affirmant que son export est prêt.
    if not chemin_absolu(candidat.file_path).exists():
        logger.warning(
            "Artefact absent du disque pour le job %s (%s) : régénération.",
            candidat.id,
            candidat.file_path,
        )
        return None
    return candidat


async def soumettre(
    db: AsyncSession,
    *,
    organisation_id: int,
    requested_by: uuid.UUID | None,
    type_export: str,
    params: dict[str, Any],
    row_count: int | None = None,
) -> tuple[ExportJob, bool]:
    """Crée un job, ou rend l'artefact identique récent. Ne valide rien d'autre.

    Retourne `(job, reutilise)`. L'appelant reste responsable du `commit()`, et
    doit committer AVANT de publier dans la file : un worker qui recevrait
    l'identifiant d'un job non encore committé ne le trouverait pas en base.

    Ne fait volontairement PAS : le contrôle de permission (il appartient à
    l'endpoint, avec le reste de ses dépendances) ni le quota d'abonnement
    (aucun en phase 1 — un job actif par organisation et une file bornée
    suffisent à l'équité, et on mesurera l'usage réel avant d'inventer une
    limite).
    """
    if type_export not in TYPES_SUPPORTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Type d'export inconnu : {type_export}",
        )

    empreinte = empreinte_params(organisation_id, type_export, params)

    existant = await _artefact_reutilisable(
        db, organisation_id=organisation_id, type_export=type_export, empreinte=empreinte
    )
    if existant is not None:
        logger.info("EXPORT_JOB_REUTILISE job=%s type=%s org=%s", existant.id, type_export, organisation_id)
        return existant, True

    # Équité entre organisations. Un worker unique traite une file unique :
    # sans borne, une organisation qui lance dix exports fait attendre toutes
    # les autres. Le refus est explicite — une attente muette est pire.
    actifs = (
        await db.execute(
            select(func.count(ExportJob.id)).where(
                ExportJob.organisation_id == organisation_id,
                ExportJob.status.in_(tuple(STATUTS_ACTIFS)),
            )
        )
    ).scalar_one()
    if actifs >= settings.export_max_queued_per_org:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"{actifs} exports sont déjà en attente pour votre organisation. "
                "Attendez qu'ils se terminent avant d'en demander un autre."
            ),
        )

    job = ExportJob(
        organisation_id=organisation_id,
        requested_by=requested_by,
        type=type_export,
        params=params,
        params_hash=empreinte,
        status=STATUT_EN_FILE,
        # Deja compte par l'endpoint pour decider de la bascule : le porter des
        # maintenant evite un ecran qui affiche « ... lignes » seulement une fois
        # la generation finie. Le worker le reecrira avec le compte du classeur.
        row_count=row_count,
    )
    db.add(job)
    # flush() et non commit() : l'identifiant doit être disponible tout de
    # suite (il nomme le fichier et part dans la réponse), mais c'est
    # l'endpoint qui décide quand la transaction se referme.
    await db.flush()
    logger.info("EXPORT_JOB_CREE job=%s type=%s org=%s", job.id, type_export, organisation_id)
    return job, False


def serialiser_job(job: ExportJob) -> dict[str, Any]:
    """Représentation JSON d'un job, unique pour toutes les réponses.

    Les chemins sont RELATIFS à la racine de l'API (`/exports/jobs/…`) et non
    absolus : le client construit déjà ses URL en préfixant `API_BASE_URL`
    (frontend/src/utils/download.ts). Renvoyer un chemin absolu obligerait le
    serveur à connaître le nom d'hôte public, qui diffère entre le conteneur, le
    reverse-proxy et le navigateur — trois occasions de se tromper.

    `error_message` est destiné à être affiché : il ne doit jamais porter de
    trace technique. C'est le worker qui en répond, pas cette fonction.
    """
    charge: dict[str, Any] = {
        "id": str(job.id),
        "type": job.type,
        "status": job.status,
        "progress": job.progress,
        "row_count": job.row_count,
        "file_name": job.file_name,
        "file_size": job.file_size,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "expires_at": job.expires_at.isoformat() if job.expires_at else None,
        "status_path": f"/exports/jobs/{job.id}",
    }
    # Le lien de téléchargement n'apparaît que quand il y a quelque chose à
    # télécharger : un client qui le voit peut le suivre, sans avoir à
    # réinterpréter le statut pour savoir s'il a le droit.
    if job.status == STATUT_TERMINE and job.file_path:
        charge["download_path"] = f"/exports/jobs/{job.id}/download"
    return charge
