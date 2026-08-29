"""Consultation et téléchargement des exports générés en tâche de fond.

Ces trois routes ne produisent aucun classeur : elles rendent l'état d'un job et
livrent son artefact. La génération vit dans `app/workers/exports.py`.

Cf. docs/architecture-exports-asynchrones-20260828.md, phase 1.
"""

from __future__ import annotations

import logging
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, has_permission
from app.api.v1.endpoints.exports import entete_piece_jointe, require_expert_admin
from app.core.config import settings
from app.db.session import get_db
from app.models.export_job import STATUT_TERMINE, ExportJob
from app.models.user import User
from app.models.organisation import Organisation
from app.services.export_jobs import (
    CheminArtefactInvalide,
    chemin_absolu,
    serialiser_job,
)

logger = logging.getLogger("onec_cpk_api.export_jobs")

router = APIRouter()

MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Forme EXACTE d'un chemin d'artefact, telle que `chemin_relatif_artefact()` la
# produit. Le contrôle est une liste blanche, et il ferme deux choses d'un coup :
#
#  - l'injection d'en-tête : `file_path` part tel quel dans `X-Accel-Redirect`,
#    et un retour chariot dans une valeur d'en-tête est une réponse HTTP
#    falsifiée. Aucun caractère de contrôle ne survit à ce motif.
#  - le service croisé entre organisations : le segment de tenant est comparé à
#    l'UUID de l'organisation du job. Le confinement sous la racine d'uploads
#    (cf. `chemin_absolu`) empêche de sortir du volume ; celui-ci empêche de
#    sortir de SON répertoire.
#
# `file_path` est écrit par notre worker et n'est donc pas hostile aujourd'hui.
# Il est stocké : ce contrôle vaut pour le jour où il ne sera plus produit par
# le seul chemin qui le produit actuellement.
MOTIF_ARTEFACT = re.compile(
    # `\Z` et NON `$` : en Python, `$` matche aussi juste avant un retour
    # chariot final, donc « …xlsx\n » passerait — et ce retour chariot est
    # exactement ce qu'on refuse de laisser entrer dans un en-tête HTTP.
    r"^tenants/(?P<tenant>[0-9a-fA-F-]{36})/exports/[0-9a-fA-F-]{36}\.xlsx\Z"
)

# Permission exigée pour VOIR un job, par type d'export.
#
# Sans cette table, un job serait visible de toute l'organisation : un
# utilisateur sans le menu Encaissements pourrait télécharger l'export
# d'encaissements demandé par un collègue, et récupérer par la porte de service
# ce que la porte principale lui refuse. Le cloisonnement multi-tenant ne couvre
# pas ce cas — il sépare les organisations, pas les rôles.
#
# `None` = aucune permission particulière, l'authentification suffit : c'est le
# régime de `GET /exports/budget`, qui n'a pas de dépendance de permission.
# Les clés reprennent EXACTEMENT les dépendances déclarées sur les routes
# correspondantes de `exports.py` ; toute divergence est un trou.
PERMISSION_PAR_TYPE: dict[str, str | None] = {
    "budget": None,
    "encaissements": "menu_encaissements",
    "sorties-fonds": "sorties_fonds",
    "requisitions": "requisitions",
    # `experts-comptables` ne se garde pas par une permission mais par un RÔLE
    # (`require_expert_admin` : super-admin, ou admin de l'organisation
    # nationale). Il ne peut donc pas figurer dans cette table, dont les valeurs
    # sont des codes de permission — d'où le renvoi vers le vérificateur dédié
    # ci-dessous. La clé est absente à dessein ; `_verifier_acces_au_type` la
    # traite avant de consulter cette table.
}

# Types gardés par un contrôle qui n'est pas une permission. La fonction est
# celle-là même que déclare la route synchrone correspondante : deux contrôles
# écrits séparément finiraient par diverger.
VERIFICATEUR_PAR_TYPE = {
    "experts-comptables": require_expert_admin,
}


async def _verifier_acces_au_type(type_export: str, user: User, db: AsyncSession) -> None:
    """Applique la permission (ou le rôle) du type, ou refuse l'inconnu."""
    verificateur = VERIFICATEUR_PAR_TYPE.get(type_export)
    if verificateur is not None:
        await verificateur(user=user, db=db)
        return
    if type_export not in PERMISSION_PAR_TYPE:
        # Refus par défaut : un type ajouté au worker sans être ajouté ici ne
        # doit pas devenir consultable par tout le monde en attendant.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Type d'export non consultable.",
        )
    code = PERMISSION_PAR_TYPE[type_export]
    if code is None:
        return
    # `has_permission` est une fabrique de dépendance, mais la fonction qu'elle
    # rend est une coroutine ordinaire (elle ne touche pas à `Request`) : on
    # peut l'appeler directement plutôt que de dupliquer sa logique de rôles.
    await has_permission(code)(user=user, db=db)


async def _charger_job(db: AsyncSession, job_id: uuid.UUID, user: User) -> ExportJob:
    """Charge un job de l'organisation courante, ou 404.

    Le filtre d'organisation est écrit EN PLUS du listener multi-tenant. Le
    listener suffit tant qu'un contexte est posé ; ce filtre-ci reste vrai même
    s'il ne l'était pas, et il coûte une condition.

    404 et non 403 quand le job appartient à une autre organisation : un 403
    confirmerait l'existence de l'identifiant.
    """
    job = (
        await db.execute(
            select(ExportJob).where(
                ExportJob.id == job_id,
                ExportJob.organisation_id == user.organisation_id,
            )
        )
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export introuvable")
    await _verifier_acces_au_type(job.type, user, db)
    return job


async def _types_visibles(user: User, db: AsyncSession) -> list[str]:
    """Les types d'export que cet utilisateur a le droit de consulter.

    Résolu UNE fois, pour être injecté dans le SQL. Deux raisons, et la première
    n'est pas la performance : filtrer APRÈS coup une page déjà tronquée par
    `LIMIT` fait disparaître les jobs `budget` d'un utilisateur dès que vingt
    exports d'encaissements plus récents ont rempli la page. Il voit une liste
    vide et en conclut que ses exports ont été perdus, alors qu'ils sont là. Le
    `LIMIT` doit porter sur ce qu'il a le droit de voir, pas l'inverse.

    La seconde : `_verifier_acces_au_type` n'est gratuit que sur un ACCORD tiré
    du contexte d'authentification en cache. Sur un REFUS, `has_permission` va
    lire la table des rôles. Appelée par job, elle produisait donc jusqu'à
    `limite` requêtes pour une seule page — un N+1 sur la route que le client
    interroge en boucle pendant qu'il attend son export. Ici, le coût est borné
    par le nombre de types (cinq), quelle que soit la taille de la page.
    """
    autorises: list[str] = []
    for type_export in PERMISSION_PAR_TYPE:
        try:
            await _verifier_acces_au_type(type_export, user, db)
        except HTTPException:
            continue
        autorises.append(type_export)
    return autorises


@router.get("/jobs")
async def lister_jobs(
    limite: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Les exports de l'organisation, les plus récents d'abord.

    Les types que l'utilisateur n'a pas le droit de voir sont retirés de la
    REQUÊTE plutôt que de faire échouer la route : un export d'encaissements
    demandé par un collègue ne doit ni lui être montré, ni empêcher
    l'utilisateur de consulter les siens.

    `total` est le nombre de lignes rendues par cet appel, pas le volume total
    d'exports de l'organisation : le compter exigerait une seconde requête pour
    un chiffre dont aucun écran n'a l'usage aujourd'hui.
    """
    types_visibles = await _types_visibles(user, db)
    if not types_visibles:
        # Aucun type consultable : inutile d'interroger la table pour n'en
        # retenir aucune ligne. Un `IN ()` vide serait par ailleurs du SQL que
        # PostgreSQL n'aime pas.
        return {"items": [], "total": 0}

    resultat = await db.execute(
        select(ExportJob)
        .where(
            ExportJob.organisation_id == user.organisation_id,
            # Un type produit par le worker mais absent de `PERMISSION_PAR_TYPE`
            # ne figure dans aucune liste : c'est le même refus par défaut que
            # sur la consultation d'un job isolé.
            ExportJob.type.in_(types_visibles),
        )
        .order_by(ExportJob.created_at.desc())
        .limit(limite)
    )
    items = [serialiser_job(job) for job in resultat.scalars().all()]
    return {"items": items, "total": len(items)}


@router.get("/jobs/{job_id}")
async def consulter_job(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """État d'un job. C'est cette route que le client interroge en attendant."""
    return serialiser_job(await _charger_job(db, job_id, user))


@router.get("/jobs/{job_id}/download")
async def telecharger_job(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Livre l'artefact sans que le fichier traverse la mémoire de Python.

    Le corps est VIDE : l'en-tête `X-Accel-Redirect` demande à nginx de servir
    lui-même le fichier, exactement comme `secure_uploads.py`. Un export de
    2 Mo ne coûte donc pas un worker HTTP pendant sa transmission — ce qui
    serait absurde après avoir sorti la génération du chemin HTTP.

    La `location internal /_protected_uploads/` a été ajoutée à
    `frontend/nginx.conf` en phase 0. Sans elle, ce corps vide arrive tel quel
    au navigateur. D'où le repli ci-dessous quand `SERVE_UPLOADS_PUBLICLY` est
    vrai : c'est le drapeau qui signale déjà un environnement sans nginx devant
    (dev), et il est faux en production.
    """
    job = await _charger_job(db, job_id, user)

    if job.status != STATUT_TERMINE or not job.file_path:
        # 409 et non 404 : le job existe, c'est son état qui ne permet pas
        # encore le téléchargement. Le client sait alors qu'il doit attendre.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Export non disponible (état : {job.status}).",
        )

    correspondance = MOTIF_ARTEFACT.match(job.file_path)
    if correspondance is None:
        logger.error(
            "Chemin d'artefact de forme inattendue sur le job %s : %r", job.id, job.file_path
        )
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Le fichier de cet export est introuvable. Relancez l'export.",
        )

    organisation_uuid = (
        await db.execute(select(Organisation.uuid).where(Organisation.id == user.organisation_id))
    ).scalar_one_or_none()
    if organisation_uuid is None or str(organisation_uuid) != correspondance.group("tenant"):
        # Le job appartient bien à l'organisation appelante (`_charger_job` l'a
        # filtré), mais son chemin désigne le répertoire d'une AUTRE. Une ligne
        # incohérente, donc : on refuse de servir, on trace, et on ne dit pas
        # pourquoi au client.
        logger.error(
            "Artefact du job %s hors du répertoire de son organisation : %r",
            job.id,
            job.file_path,
        )
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Le fichier de cet export est introuvable. Relancez l'export.",
        )

    try:
        chemin = chemin_absolu(job.file_path)
    except CheminArtefactInvalide:
        logger.error("Chemin d'artefact invalide sur le job %s : %r", job.id, job.file_path)
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Le fichier de cet export est introuvable. Relancez l'export.",
        ) from None
    if not chemin.exists():
        # 410 : le job dit DONE mais l'artefact a été purgé ou perdu. Distinguer
        # ce cas d'un 404 évite à l'utilisateur de croire à une erreur de lien.
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Le fichier de cet export a expiré. Relancez l'export.",
        )

    # MEME sanitisation que le chemin synchrone (`exports.py`), et pour la meme
    # raison : `file_name` vient de la base, donc du worker, donc du meme
    # generateur qui recopie des parametres de requete dans le nom du fichier.
    # Une liste noire de `\r\n"` ne suffisait pas — un caractere hors latin-1
    # fait echouer l'encodage de l'en-tete par Starlette, et le telechargement
    # rend un 500 alors que l'artefact, lui, est bien la.
    entetes = {
        "Content-Disposition": entete_piece_jointe(job.file_name or f"export_{job.id}.xlsx")
    }

    if settings.serve_uploads_publicly:
        return FileResponse(path=str(chemin), media_type=MIME_XLSX, headers=entetes)

    entetes["X-Accel-Redirect"] = f"/_protected_uploads/{job.file_path}"
    return Response(content=b"", media_type=MIME_XLSX, headers=entetes)
