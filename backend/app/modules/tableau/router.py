from __future__ import annotations

import logging
from collections import Counter
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_tenant_uuid, get_current_user, has_any_permission, has_permission
from app.db.session import get_db
from app.models.organisation import Organisation
from app.models.user import User
from .models import TableauImport, TableauActualisation, TableauActualisationInput, TableauActualisationRow, TableauCaDeclaration, TableauInsuranceDeclaration
from .repository import dernier_exercice, get_analyse_for_import, get_import, get_stats, list_anomalies, list_dossiers, list_imports, list_reports
from .assistant import run_tableau_assistant
from .audit import record_tableau_audit
from .models import TableauAuditLog
from .schemas import (
    TableauAnomalieOut,
    TableauAnalyseOut,
    TableauAssistantIn,
    TableauAssistantOut,
    TableauAuditLogOut,
    TableauBaseAnalyseItem,
    TableauBaseAnalyseResult,
    TableauBaseOut,
    TableauComparisonOut,
    TableauComparisonRequest,
    TableauDecisionCreate,
    TableauDecisionOut,
    TableauDossierCorrection,
    TableauDossierOut,
    TableauImportOut,
    TableauImportResult,
    TableauPVCreate,
    TableauReglagesIn,
    TableauReportCreate,
    TableauReportOut,
    TableauSortieOut,
    TableauStatsOut,
    TableauActualisationListOut, TableauActualisationOut, TableauActualisationRowsOut,
    TableauActualisationRowOut, TableauActualisationStatsOut, TableauActualisationDetailOut,
)
from .service import (
    create_decision,
    create_pv,
    create_report,
    corriger_dossier,
    export_import_annote,
    export_rapport_complet,
    export_tableau,
    get_base_tableau,
    get_stats_tableau,
    import_source_snapshot,
    get_reglages,
    import_excel,
    run_analyse,
    run_analyse_base,
    run_comparison,
    set_reglages,
)
from .actualisation_service import get_current_tableau_actualisation
from .import_lignes import lignes_import
from .sorties import annuler_sortie, declarer_sortie, sortie_payload
from . import releves as releves_service

logger = logging.getLogger(__name__)

# Valeurs des filtres de la Base : les mêmes pour la page et pour l'envoi
# groupé à « tous les membres du filtre ».
FiltrePersonne = Literal["morale", "physique"]
FiltreSexe = Literal["M", "F"]
FiltreAnciennete = Literal["Ancien", "Nouveau"]
FiltreSituation = Literal["en_exercice", "sortis", "tous", "DECEDE", "DEMISSIONNAIRE", "RADIE", "OMIS", "CESSE"]
FiltreConclusion = Literal["INSCRIT", "NON INSCRIT", "À DÉLIBÉRER", "SANS"]
FiltreCotisation = Literal["payee", "partielle", "non_payee", "inconnue"]
FiltreOuiNon = Literal["oui", "non", "inconnu"]
FiltreFormation = Literal["atteint", "insuffisant", "non_requis", "inconnu"]
CanalReleve = Literal["email", "whatsapp"]

router = APIRouter(prefix="/tableau", tags=["Tableau"])

# Le Tableau ne s'ouvre plus sur le droit de consulter le Secrétariat : c'est un
# module à part, avec son propre droit de lecture.
VIEW_PERMS = ["tableau.view"]


@router.get("/stats", response_model=TableauStatsOut, dependencies=[Depends(has_any_permission(VIEW_PERMS))])
async def tableau_stats(
    personne: Literal["toutes", "physique", "morale"] = Query(default="physique"),
    actif: Literal["tous", "oui", "non", "inconnu"] = Query(default="oui"),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> dict:
    return await get_stats_tableau(db, tenant_id, personne=personne, actif=actif)


@router.get("/imports", response_model=list[TableauImportOut], dependencies=[Depends(has_any_permission(VIEW_PERMS))])
async def list_tableau_imports(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list:
    return await list_imports(db, tenant_id)


@router.post(
    "/imports",
    response_model=TableauImportResult,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_permission("tableau.import"))],
)
async def upload_excel(
    exercice: str = Form(...),
    date_situation: date = Form(...),
    source_type: str = Form(default="tableau"),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> TableauImportResult:
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Fichier Excel (.xlsx ou .xls) requis.")
    content = await file.read()
    if source_type == "tableau":
        outcome = await import_excel(db, user, tenant_id, file.filename, content, exercice, date_situation=date_situation)
    else:
        outcome = await import_source_snapshot(
            db, user, tenant_id, file.filename, content, source_type, exercice, date_situation
        )
    n = outcome.imported
    avert = f" ({len(outcome.errors)} avertissement(s))" if outcome.errors else ""
    return TableauImportResult(
        success=True,
        import_id=outcome.imp.id,
        exercice=outcome.imp.exercice,
        date_situation=outcome.imp.date_situation,
        source_type=outcome.imp.source_type,
        file_name=outcome.imp.file_name,
        status="duplicate" if outcome.duplicate_detected else outcome.imp.status,
        duplicate_detected=outcome.duplicate_detected,
        file_sha256=outcome.imp.file_sha256,
        imported=outcome.imported,
        updated=outcome.updated,
        skipped=outcome.skipped,
        total_lignes=outcome.total,
        accepted_rows=outcome.imp.accepted_rows,
        rejected_rows=outcome.imp.rejected_rows,
        error_count=outcome.imp.error_count,
        reprises=outcome.reprises,
        decisions_reportees=outcome.decisions_reportees,
        nouveaux_membres=outcome.nouveaux_membres,
        errors=outcome.errors,
        message=("Réimport identique détecté : aucun nouveau snapshot créé."
                  if outcome.duplicate_detected else f"{n} ligne(s) traitée(s){avert}."),
    )


@router.get(
    "/imports/{import_id}/fichier-annote",
    summary="Fichier importé, lignes à compléter en rouge",
    dependencies=[Depends(has_any_permission(["tableau.import", "tableau.export"]))],
)
async def download_import_annote(
    import_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> StreamingResponse:
    content, fname = await export_import_annote(db, tenant_id, import_id)
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get(
    "/imports/{import_id}/lignes",
    summary="Lignes d'un import, avec les colonnes du fichier Excel dans leur ordre",
    dependencies=[Depends(has_any_permission(VIEW_PERMS))],
)
async def lire_lignes_import(
    import_id: int,
    feuille: str | None = Query(default=None, max_length=120),
    q: str | None = Query(default=None, max_length=120),
    signalees: bool = Query(default=False, description="Seulement les lignes signalées à l'import"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> dict[str, Any]:
    return await lignes_import(
        db, tenant_id, import_id, feuille=feuille, recherche=q, signalees=signalees, limit=limit, offset=offset,
    )


async def _est_conseil_national(db: AsyncSession, user: User) -> bool:
    """Le Conseil National (et le super-admin) peut consolider tous les conseils."""
    if (user.role or "").lower() == "super_admin":
        return True
    if (user.role or "").lower() == "admin" and user.organisation_id:
        res = await db.execute(select(Organisation.slug).where(Organisation.id == user.organisation_id))
        return (res.scalar_one_or_none() or "").lower() == "cn"
    return False


@router.get(
    "/base",
    response_model=TableauBaseOut,
    summary="Base consolidée du Tableau pour un exercice",
    dependencies=[Depends(has_any_permission(VIEW_PERMS))],
)
async def get_base(
    exercice: str | None = Query(default=None, description="Par défaut, l'exercice du dernier import"),
    anomalie_only: bool = Query(default=False),
    national: bool = Query(default=False, description="Consolider tous les conseils — réservé au Conseil National"),
    q: str | None = Query(default=None, max_length=120),
    categorie: str | None = Query(default=None, max_length=50),
    organisation_id: int | None = Query(default=None, ge=1),
    personne: FiltrePersonne | None = Query(default=None),
    province: str | None = Query(default=None, max_length=100),
    sexe: FiltreSexe | None = Query(default=None),
    anciennete: FiltreAnciennete | None = Query(default=None),
    actif: bool | None = Query(default=None),
    situation: FiltreSituation = Query(
        default="en_exercice", description="Par défaut, les membres sortis du Tableau sont écartés",
    ),
    # Filtres sur ce que calculent les règles de délibération.
    conclusion: FiltreConclusion | None = Query(default=None),
    cotisation: FiltreCotisation | None = Query(default=None),
    assurance: FiltreOuiNon | None = Query(default=None),
    chiffre_affaires: FiltreOuiNon | None = Query(default=None),
    formation: FiltreFormation | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> TableauBaseOut:
    """Situation qui fait foi pour chaque membre, tous imports de l'exercice confondus.

    Chaque conseil tient sa propre base ; seul le Conseil National peut demander
    la consolidation de l'ensemble.
    """
    organisation_ids = [tenant_id]
    if national:
        if not await _est_conseil_national(db, user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Consolidation nationale réservée au Conseil National.",
            )
        res = await db.execute(select(TableauImport.organisation_id).distinct())
        organisation_ids = sorted({o for o in res.scalars().all() if o is not None}) or [tenant_id]

    base = await get_base_tableau(
        db,
        organisation_ids,
        exercice=exercice,
        anomalie_only=anomalie_only,
        national=national,
        recherche=q,
        categorie=categorie,
        organisation_id=organisation_id,
        personne=personne,
        province=province,
        sexe=sexe,
        anciennete=anciennete,
        actif=actif,
        conclusion=conclusion,
        cotisation=cotisation,
        assurance=assurance,
        chiffre_affaires=chiffre_affaires,
        formation=formation,
        situation=situation,
        limit=limit,
        offset=offset,
    )
    return TableauBaseOut(**base)


@router.get("/dossiers", response_model=list[TableauDossierOut], dependencies=[Depends(has_any_permission(VIEW_PERMS))])
async def list_tableau_dossiers(
    import_id: int | None = Query(default=None),
    exercice: str | None = Query(default=None),
    anomalie_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list:
    return await list_dossiers(db, tenant_id, import_id=import_id, exercice=exercice, anomalie_only=anomalie_only)


@router.get(
    "/analyses",
    response_model=TableauAnalyseOut | None,
    summary="Analyse enregistrée pour un import et un périmètre",
    dependencies=[Depends(has_any_permission(VIEW_PERMS))],
)
async def get_tableau_analyse(
    import_id: int = Query(...),
    scope: Literal["import", "base"] = Query(default="import"),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> object:
    """Renvoie l'analyse et son état — « completed » ou « stale » — ou null.

    Sans cette lecture, l'obsolescence d'une analyse ne se découvrait qu'au
    moment d'exporter, sous la forme d'un refus.
    """
    return await get_analyse_for_import(db, tenant_id, import_id, scope=scope)


@router.post(
    "/analyse",
    response_model=TableauAnalyseOut,
    dependencies=[Depends(has_permission("tableau.analyze"))],
)
async def analyse_import(
    import_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> object:
    return await run_analyse(db, user, tenant_id, import_id)


@router.post(
    "/analyses/base",
    response_model=TableauBaseAnalyseResult,
    summary="Analyser la base consolidée de l'exercice",
    dependencies=[Depends(has_permission("tableau.analyze"))],
)
async def analyse_base(
    exercice: str | None = Query(default=None, description="Par défaut, l'exercice du dernier import"),
    national: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> TableauBaseAnalyseResult:
    """Délibère sur la situation qui fait foi pour chaque membre, et non sur un fichier isolé."""
    organisation_ids = [tenant_id]
    if national:
        if not await _est_conseil_national(db, user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Analyse nationale réservée au Conseil National.")
        organisation_ids = sorted(set((await db.execute(select(TableauImport.organisation_id).distinct())).scalars().all()))
    exercice = exercice or await dernier_exercice(db, organisation_ids)
    if not exercice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Aucun import Tableau.")

    noms = dict((await db.execute(
        select(Organisation.id, Organisation.nom).where(Organisation.id.in_(organisation_ids))
    )).all())

    # Les analyses sont figées dès qu'elles sont faites : le rollback d'un conseil
    # en échec expire les objets de la session, et lire un objet expiré pour
    # bâtir la réponse relancerait une requête au milieu de la sérialisation.
    analyses: list[TableauAnalyseOut] = []
    resultats: list[TableauBaseAnalyseItem] = []
    for org_id in organisation_ids:
        existe = await db.execute(
            select(TableauImport.id).where(
                TableauImport.organisation_id == org_id,
                TableauImport.exercice == exercice,
            ).limit(1)
        )
        if existe.scalar_one_or_none() is None:
            continue
        if not national:
            # Un seul conseil : l'échec doit remonter tel quel à l'appelant.
            analyse = await run_analyse_base(db, user, org_id, exercice=exercice)
        else:
            # Chaque conseil est validé séparément. Sans cela, un conseil en
            # échec laissait les précédents déjà enregistrés et ne disait pas
            # lesquels : le résultat annonce désormais le sort de chacun.
            try:
                analyse = await run_analyse_base(db, user, org_id, exercice=exercice)
            except HTTPException as exc:
                await db.rollback()
                resultats.append(TableauBaseAnalyseItem(
                    organisation_id=org_id,
                    organisation_nom=noms.get(org_id),
                    status="erreur",
                    detail=str(exc.detail),
                ))
                continue
            except Exception:
                await db.rollback()
                logger.exception("Analyse de base en échec pour l'organisation %s", org_id)
                resultats.append(TableauBaseAnalyseItem(
                    organisation_id=org_id,
                    organisation_nom=noms.get(org_id),
                    status="erreur",
                    detail="Erreur interne pendant l'analyse de ce conseil.",
                ))
                continue
        figee = TableauAnalyseOut.model_validate(analyse)
        analyses.append(figee)
        resultats.append(TableauBaseAnalyseItem(
            organisation_id=org_id,
            organisation_nom=noms.get(org_id),
            status="ok",
            analyse=figee,
        ))
    return TableauBaseAnalyseResult(
        exercice=exercice,
        national=national,
        analyses_count=len(analyses),
        erreurs_count=sum(1 for item in resultats if item.status == "erreur"),
        total_dossiers=sum(a.total_dossiers for a in analyses),
        analyses=analyses,
        resultats=resultats,
    )


@router.get(
    "/reglages/{import_id}",
    summary="Règles de délibération en vigueur pour l'exercice de cet import",
    dependencies=[Depends(has_any_permission(VIEW_PERMS))],
)
async def read_reglages(
    import_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> dict:
    return await get_reglages(db, tenant_id, import_id)


@router.put(
    "/reglages/{import_id}",
    dependencies=[Depends(has_permission("tableau.settings"))],
)
async def update_reglages(
    import_id: int,
    payload: TableauReglagesIn,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> dict:
    """Met à jour les réglages de délibération (seuils, action âge...) d'un import."""
    return await set_reglages(db, tenant_id, import_id, payload.model_dump(exclude_none=True))


@router.get(
    "/export/{import_id}",
    dependencies=[Depends(has_permission("tableau.export"))],
)
async def export_tableau_xlsx(
    import_id: int,
    scope: Literal["import", "base"] = Query(default="import"),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> StreamingResponse:
    """Génère et télécharge le tableau provincial (.xlsx) avec les conclusions."""
    content, fname = await export_tableau(db, tenant_id, import_id, scope=scope)
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get(
    "/rapport-complet/{import_id}",
    dependencies=[Depends(has_permission("tableau.export"))],
)
async def export_rapport_complet_tableau(
    import_id: int,
    format: Literal["pdf", "xlsx"] = Query(default="pdf"),
    scope: Literal["import", "base"] = Query(default="import"),
    categorie: Literal["EC Cabinet", "EC Indépendant", "Société", "EC Salarié"] | None = Query(
        default=None, description="Limite le rapport à une catégorie ; absent : toutes.",
    ),
    formation: Literal["heures", "oui_non"] = Query(
        default="heures", description="Colonne formation : NHV chiffré (heures) ou OUI/NON (oui_non).",
    ),
    personne: Literal["toutes", "physique", "morale"] = Query(default="toutes"),
    actif: Literal["tous", "oui", "non", "inconnu"] = Query(default="tous"),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> StreamingResponse:
    """Télécharge le rapport complet : le tableau de bord, puis la liste des membres."""
    content, fname = await export_rapport_complet(
        db, tenant_id, import_id, format_sortie=format, scope=scope, categorie=categorie, formation=formation, personne=personne, actif=actif,
    )
    media_type = (
        "application/pdf" if format == "pdf"
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/anomalies", response_model=list[TableauAnomalieOut], dependencies=[Depends(has_any_permission(VIEW_PERMS))])
async def list_tableau_anomalies(
    import_id: int | None = Query(default=None),
    gravite: str | None = Query(default=None),
    scope: Literal["import", "base"] = Query(default="import"),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list:
    analyse_id = None
    if import_id is not None:
        analyse = await get_analyse_for_import(db, tenant_id, import_id, scope=scope)
        if analyse is not None:
            analyse_id = analyse.id
        elif scope == "base":
            return []
    return await list_anomalies(
        db,
        tenant_id,
        import_id=import_id if scope == "import" else None,
        gravite=gravite,
        analyse_id=analyse_id,
        legacy_only=import_id is not None and analyse_id is None,
    )


@router.post(
    "/compare",
    response_model=TableauComparisonOut,
    dependencies=[Depends(has_permission("tableau.compare"))],
)
async def compare_tableau(
    payload: TableauComparisonRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> dict:
    return await run_comparison(db, tenant_id, payload.exercice_a, payload.exercice_b)


@router.post(
    "/decisions",
    response_model=TableauDecisionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_permission("tableau.decide"))],
)
async def create_tableau_decision(
    payload: TableauDecisionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> object:
    return await create_decision(db, user, tenant_id, payload)


@router.patch(
    "/dossiers/{dossier_id}",
    response_model=TableauDossierOut,
    dependencies=[Depends(has_permission("tableau.correct"))],
)
async def corriger_tableau_dossier(
    dossier_id: int,
    payload: TableauDossierCorrection,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> object:
    return await corriger_dossier(db, user, tenant_id, dossier_id, payload)


@router.post(
    "/sorties",
    response_model=TableauSortieOut,
    summary="Déclarer (ou modifier) la sortie du Tableau d'un membre",
    dependencies=[Depends(has_permission("tableau.correct"))],
)
async def declarer_sortie_membre(
    numero_ordre: str = Form(..., max_length=50),
    nom: str = Form(..., max_length=300),
    categorie: str | None = Form(default=None, max_length=50),
    situation: Literal["DECEDE", "DEMISSIONNAIRE", "RADIE", "OMIS", "CESSE"] = Form(...),
    date_effet: date = Form(...),
    lieu_deces: str | None = Form(default=None, max_length=200),
    motif_cessation: str | None = Form(default=None, max_length=20),
    societe_absorbante: str | None = Form(default=None, max_length=300),
    reference_decision: str | None = Form(default=None, max_length=200),
    observation: str | None = Form(default=None, max_length=2000),
    piece: UploadFile | None = File(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    tenant_uuid: str = Depends(get_current_tenant_uuid),
) -> object:
    sortie = await declarer_sortie(
        db, user, tenant_id, tenant_uuid,
        numero_ordre=numero_ordre, nom=nom, categorie=categorie, situation=situation, date_effet=date_effet,
        lieu_deces=lieu_deces, motif_cessation=motif_cessation, societe_absorbante=societe_absorbante,
        reference_decision=reference_decision, observation=observation, piece=piece,
    )
    return sortie_payload(sortie)


@router.delete(
    "/sorties/{sortie_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Annuler une sortie déclarée à tort : le membre est réintégré",
    dependencies=[Depends(has_permission("tableau.correct"))],
)
async def annuler_sortie_membre(
    sortie_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> Response:
    await annuler_sortie(db, user, tenant_id, sortie_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class TableauReleveEnvoiIn(BaseModel):
    numero_ordre: str = Field(..., min_length=1, max_length=50)
    exercice: str | None = Field(default=None, max_length=20)
    canaux: list[CanalReleve] = Field(default_factory=lambda: ["email", "whatsapp"])
    renvoyer: bool = Field(default=False, description="Renvoyer même si la même situation est déjà partie.")
    # Passages repris à la main avant l'envoi ; absents, le texte calculé part tel quel.
    annonce: str | None = Field(default=None, max_length=releves_service.MAX_TEXTE_MODIFIE)
    consigne: str | None = Field(default=None, max_length=releves_service.MAX_TEXTE_MODIFIE)


@router.get(
    "/releves/apercu",
    summary="Relevé de situation d'un membre, tel qu'il partirait",
    dependencies=[Depends(has_permission("tableau.notify"))],
)
async def apercu_releve(
    numero_ordre: str = Query(..., min_length=1, max_length=50),
    exercice: str | None = Query(default=None, max_length=20),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> dict[str, Any]:
    return await releves_service.apercu(db, tenant_id, exercice, numero_ordre)


@router.post(
    "/releves",
    summary="Envoyer au membre son relevé de situation (e-mail, WhatsApp)",
    dependencies=[Depends(has_permission("tableau.notify"))],
)
async def envoyer_releve(
    payload: TableauReleveEnvoiIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> dict[str, Any]:
    return await releves_service.envoyer(
        db, user, tenant_id,
        exercice=payload.exercice, numero_ordre=payload.numero_ordre,
        canaux=payload.canaux, renvoyer=payload.renvoyer,
        annonce=payload.annonce, consigne=payload.consigne,
    )


class TableauReleveFiltres(BaseModel):
    """Les filtres de la Base, pour viser « tous les membres du filtre »."""

    q: str | None = Field(default=None, max_length=120)
    categorie: str | None = Field(default=None, max_length=50)
    personne: FiltrePersonne | None = None
    province: str | None = Field(default=None, max_length=100)
    sexe: FiltreSexe | None = None
    anciennete: FiltreAnciennete | None = None
    actif: bool | None = None
    situation: FiltreSituation = "en_exercice"
    conclusion: FiltreConclusion | None = None
    cotisation: FiltreCotisation | None = None
    assurance: FiltreOuiNon | None = None
    chiffre_affaires: FiltreOuiNon | None = None
    formation: FiltreFormation | None = None
    anomalie_only: bool = False

    def en_criteres(self) -> dict[str, Any]:
        donnees = self.model_dump(exclude={"q"})
        donnees["recherche"] = self.q
        return donnees


class TableauReleveSelectionIn(BaseModel):
    """Des n° d'ordre choisis un à un, ou tous les membres d'un filtre de la Base."""

    exercice: str | None = Field(default=None, max_length=20)
    numeros: list[str] | None = Field(default=None, max_length=releves_service.MAX_LOT)
    filtres: TableauReleveFiltres | None = None
    canaux: list[CanalReleve] = Field(default_factory=lambda: ["email", "whatsapp"])
    renvoyer: bool = False

    def selection(self) -> dict[str, Any]:
        if self.numeros is None and self.filtres is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Sélectionnez des membres, ou un filtre.")
        return {
            "numeros": self.numeros,
            "filtres": None if self.numeros is not None else self.filtres.en_criteres(),
        }


@router.post(
    "/releves/selection",
    summary="Envoi groupé : qui recevra sa situation, qui est écarté et pourquoi",
    dependencies=[Depends(has_permission("tableau.notify"))],
)
async def preparer_releves(
    payload: TableauReleveSelectionIn,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> dict[str, Any]:
    return await releves_service.preparer_selection(
        db, tenant_id, exercice=payload.exercice, canaux=payload.canaux, **payload.selection(),
    )


@router.post(
    "/releves/lots",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Lancer l'envoi groupé des relevés de situation (en arrière-plan)",
    dependencies=[Depends(has_permission("tableau.notify"))],
)
async def lancer_lot_releves(
    payload: TableauReleveSelectionIn,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> dict[str, Any]:
    lot = await releves_service.creer_lot(
        db, user, tenant_id, exercice=payload.exercice, canaux=payload.canaux,
        renvoyer=payload.renvoyer, **payload.selection(),
    )
    background_tasks.add_task(releves_service.traiter_lot, lot.id, tenant_id)
    return releves_service.lot_payload(lot)


@router.get(
    "/releves/lots/{lot_id}",
    summary="Avancement d'un envoi groupé",
    dependencies=[Depends(has_permission("tableau.notify"))],
)
async def avancement_lot_releves(
    lot_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> dict[str, Any]:
    lot = await releves_service.lire_lot(db, tenant_id, lot_id)
    return releves_service.lot_payload(lot, await releves_service.echecs_du_lot(db, lot))


@router.post(
    "/releves/lots/{lot_id}/reprendre",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Reprendre un envoi groupé interrompu, là où il s'est arrêté",
    dependencies=[Depends(has_permission("tableau.notify"))],
)
async def reprendre_lot_releves(
    lot_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> dict[str, Any]:
    lot = await releves_service.reprendre_lot(db, tenant_id, lot_id)
    background_tasks.add_task(releves_service.traiter_lot, lot.id, tenant_id)
    return releves_service.lot_payload(lot)


@router.get(
    "/releves/derniers",
    summary="Dernier relevé envoyé à chaque membre de l'exercice",
    dependencies=[Depends(has_any_permission(VIEW_PERMS))],
)
async def derniers_releves(
    exercice: str = Query(..., min_length=1, max_length=20),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> dict[str, Any]:
    return await releves_service.derniers_envois(db, tenant_id, exercice)


@router.get("/reports", response_model=list[TableauReportOut], dependencies=[Depends(has_any_permission(VIEW_PERMS))])
async def list_tableau_reports(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list:
    return await list_reports(db, tenant_id)


@router.post(
    "/reports",
    response_model=TableauReportOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_permission("tableau.generate_report"))],
)
async def generate_tableau_report(
    payload: TableauReportCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> object:
    return await create_report(db, user, tenant_id, payload)


@router.post(
    "/pv",
    response_model=TableauReportOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_permission("tableau.generate_pv"))],
)
async def generate_tableau_pv(
    payload: TableauPVCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> object:
    return await create_pv(db, user, tenant_id, payload)


@router.get(
    "/audit",
    response_model=list[TableauAuditLogOut],
    summary="Journal des actions du module",
    dependencies=[Depends(has_permission("tableau.view_audit_logs"))],
)
async def list_tableau_audit(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    action: str | None = Query(default=None, max_length=80),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list:
    q = select(TableauAuditLog).where(TableauAuditLog.organisation_id == tenant_id)
    if action:
        q = q.where(TableauAuditLog.action == action)
    q = q.order_by(TableauAuditLog.created_at.desc(), TableauAuditLog.id.desc()).limit(limit).offset(offset)
    return list((await db.execute(q)).scalars().all())


@router.post(
    "/assistant/chat",
    response_model=TableauAssistantOut,
    summary="Assistant du Tableau — questions sur la base, les anomalies et les règles",
    dependencies=[Depends(has_permission("tableau.use_assistant"))],
)
async def tableau_assistant_chat(
    payload: TableauAssistantIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> TableauAssistantOut:
    resultat = await run_tableau_assistant(
        message=payload.message,
        db=db,
        user=user,
        organisation_id=tenant_id,
        conversation_history=payload.conversation_history,
    )
    await record_tableau_audit(
        db,
        organisation_id=tenant_id,
        user_id=user.id,
        action="tableau.assistant.chat",
        target_type="ai_chat",
        metadata_json={
            "outils": resultat.get("actions_taken", []),
            "longueur_question": len(payload.message),
        },
    )
    await db.commit()
    return TableauAssistantOut(**resultat)


# Consultation des révisions matérialisées (lecture seule).
def _actualisation_row_payload(row):
    diffs = list(row.differences_json or [])
    anomalies = list(row.anomalies_json or [])
    return {"id": row.id, "actualisation_id": row.actualisation_id, "identity_id": row.identity_id,
            "official_expert_id": row.official_expert_id, "numero_ordre": row.numero_ordre,
            "reference_status": row.reference_status, "proposal_status": row.proposal_status,
            "official_values": row.official_values or {}, "proposed_values": row.proposed_values or {},
            "field_provenance": row.field_provenance or {}, "differences": diffs,
            "difference_codes": [d.get("field") for d in diffs if isinstance(d, dict) and d.get("field")],
            "anomalies": anomalies, "anomaly_codes": [a.get("code") for a in anomalies if isinstance(a, dict) and a.get("code")]}


async def _get_actual(
    db: AsyncSession, tenant_id: int, actualisation_id: int
) -> TableauActualisation:
    """L'actualisation demandée, à condition qu'elle appartienne à l'organisation.

    Appelée en tête de chaque lecture : les lignes et les entrées d'une
    actualisation ne portent pas d'`organisation_id`, elles sont cadrées par leur
    parent. Sans ce contrôle, un identifiant suffirait à lire les données d'une
    autre organisation.
    """
    obj = (await db.execute(
        select(TableauActualisation).where(
            TableauActualisation.id == actualisation_id,
            TableauActualisation.organisation_id == tenant_id,
        )
    )).scalar_one_or_none()
    if obj is None:
        raise HTTPException(404, "Actualisation introuvable")
    return obj


def _actualisation_resume(
    a: TableauActualisation, *, imports_count: int, total_rows: int, is_current: bool
) -> dict:
    """Le résumé commun à la liste et au détail, pour qu'ils ne divergent pas."""
    return {
        "id": a.id,
        "date_situation": a.date_situation,
        "revision_number": a.revision_number,
        "actualized_at": a.actualized_at,
        "status": a.status,
        "reference_snapshot_id": a.reference_snapshot_id,
        "imports_count": imports_count,
        "total_rows": total_rows,
        "is_current": is_current,
    }


@router.get(
    "/actualisations",
    response_model=TableauActualisationListOut,
    dependencies=[Depends(has_any_permission(VIEW_PERMS))],
)
async def tableau_actualisations(
    date_situation: date | None = Query(None),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
):
    where = [TableauActualisation.organisation_id == tenant_id]
    if date_situation:
        where.append(TableauActualisation.date_situation == date_situation)

    actuals = list((await db.execute(
        select(TableauActualisation)
        .where(*where)
        .order_by(
            TableauActualisation.date_situation.desc(),
            TableauActualisation.revision_number.desc(),
        )
    )).scalars().all())

    items = []
    for a in actuals:
        imports_count = (await db.execute(
            select(func.count(TableauActualisationInput.id))
            .where(TableauActualisationInput.actualisation_id == a.id)
        )).scalar_one()
        total_rows = (await db.execute(
            select(func.count(TableauActualisationRow.id))
            .where(TableauActualisationRow.actualisation_id == a.id)
        )).scalar_one()
        courante = await get_current_tableau_actualisation(
            db, organisation_id=tenant_id, date_situation=a.date_situation
        )
        items.append(_actualisation_resume(
            a,
            imports_count=imports_count,
            total_rows=total_rows,
            is_current=bool(courante and courante.id == a.id),
        ))
    return {"items": items, "total": len(items)}


@router.get(
    "/actualisations/{actualisation_id}",
    response_model=TableauActualisationOut,
    dependencies=[Depends(has_any_permission(VIEW_PERMS))],
)
async def tableau_actualisation(
    actualisation_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
):
    a = await _get_actual(db, tenant_id, actualisation_id)
    imports_count = (await db.execute(
        select(func.count(TableauActualisationInput.id))
        .where(TableauActualisationInput.actualisation_id == a.id)
    )).scalar_one()
    total_rows = (await db.execute(
        select(func.count(TableauActualisationRow.id))
        .where(TableauActualisationRow.actualisation_id == a.id)
    )).scalar_one()
    courante = await get_current_tableau_actualisation(
        db, organisation_id=tenant_id, date_situation=a.date_situation
    )
    resume = _actualisation_resume(
        a,
        imports_count=imports_count,
        total_rows=total_rows,
        is_current=bool(courante and courante.id == a.id),
    )
    resume["ruleset_version"] = a.ruleset_version
    resume["knowledge_cutoff_at"] = (a.metadata_json or {}).get("knowledge_cutoff_at")
    resume["metadata_json"] = a.metadata_json
    return resume


@router.get(
    "/actualisations/{actualisation_id}/lignes",
    response_model=TableauActualisationRowsOut,
    dependencies=[Depends(has_any_permission(VIEW_PERMS))],
)
async def tableau_actualisation_lignes(
    actualisation_id: int,
    q: str | None = Query(None, max_length=120),
    proposal_status: str | None = None,
    reference_status: str | None = None,
    anomaly_only: bool = False,
    sort: Literal["numero_ordre", "proposal_status", "reference_status", "id"] = "numero_ordre",
    order: Literal["asc", "desc"] = "asc",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
):
    await _get_actual(db, tenant_id, actualisation_id)

    where = [TableauActualisationRow.actualisation_id == actualisation_id]
    if q:
        nom = TableauActualisationRow.proposed_values.op("->>")("nom_denomination")
        where.append(or_(
            TableauActualisationRow.numero_ordre.ilike(f"%{q}%"),
            nom.ilike(f"%{q}%"),
        ))
    if proposal_status:
        where.append(TableauActualisationRow.proposal_status == proposal_status)
    if reference_status:
        where.append(TableauActualisationRow.reference_status == reference_status)
    if anomaly_only:
        where.append(func.jsonb_array_length(TableauActualisationRow.anomalies_json) > 0)

    colonnes = {
        "numero_ordre": TableauActualisationRow.numero_ordre,
        "proposal_status": TableauActualisationRow.proposal_status,
        "reference_status": TableauActualisationRow.reference_status,
        "id": TableauActualisationRow.id,
    }
    tri = colonnes[sort].desc() if order == "desc" else colonnes[sort]

    total = (await db.execute(
        select(func.count(TableauActualisationRow.id)).where(*where)
    )).scalar_one()
    rows = list((await db.execute(
        select(TableauActualisationRow)
        .where(*where)
        .order_by(tri)
        .offset(offset)
        .limit(limit)
    )).scalars().all())

    return {
        "items": [_actualisation_row_payload(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/actualisations/{actualisation_id}/lignes/{ligne_id}",
    response_model=TableauActualisationDetailOut,
    dependencies=[Depends(has_any_permission(VIEW_PERMS))],
)
async def tableau_actualisation_ligne(
    actualisation_id: int,
    ligne_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
):
    await _get_actual(db, tenant_id, actualisation_id)

    row = (await db.execute(
        select(TableauActualisationRow).where(
            TableauActualisationRow.id == ligne_id,
            TableauActualisationRow.actualisation_id == actualisation_id,
        )
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Ligne introuvable")

    out = _actualisation_row_payload(row)

    imports = (await db.execute(
        select(TableauActualisationInput)
        .where(TableauActualisationInput.actualisation_id == actualisation_id)
    )).scalars().all()
    out["source_imports"] = [
        {
            "id": i.id,
            "import_id": i.import_id,
            "source_type": i.source_type,
            "date_situation": i.date_situation,
            "file_name": i.file_name,
            "file_sha256": i.file_sha256,
        }
        for i in imports
    ]

    # Déclarations rattachées à l'identité de la ligne. Côté déclarations, la
    # colonne s'appelle `member_identity_id` : `identity_id` n'existe pas sur
    # ces modèles et faisait tomber la route en 500. Cadrage par organisation
    # en plus : les identités sont propres à un tenant, mais la requête ne
    # doit pas compter dessus.
    ca = (await db.execute(
        select(TableauCaDeclaration).where(
            TableauCaDeclaration.organisation_id == tenant_id,
            TableauCaDeclaration.member_identity_id == row.identity_id,
        )
    )).scalars().all()
    out["ca_declarations"] = [
        {
            "id": x.id,
            "date_situation": x.date_situation,
            "annee": x.annee,
            "ca_facture": x.ca_facture,
            "ca_collecte": x.ca_collecte,
        }
        for x in ca
    ]

    assurances = (await db.execute(
        select(TableauInsuranceDeclaration)
        .where(
            TableauInsuranceDeclaration.organisation_id == tenant_id,
            TableauInsuranceDeclaration.member_identity_id == row.identity_id,
        )
    )).scalars().all()
    out["insurance_declarations"] = [
        {
            "id": x.id,
            "date_situation": x.date_situation,
            "declare": x.declare_normalise,
            "date_declaration": x.date_declaration,
            "souscrit": x.souscrit_normalise,
            "date_souscription": x.date_souscription,
            "assureur": x.assureur_normalise,
        }
        for x in assurances
    ]
    return out


@router.get(
    "/actualisations/{actualisation_id}/stats",
    response_model=TableauActualisationStatsOut,
    dependencies=[Depends(has_any_permission(VIEW_PERMS))],
)
async def tableau_actualisation_stats(
    actualisation_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
):
    await _get_actual(db, tenant_id, actualisation_id)
    rows = list((await db.execute(
        select(TableauActualisationRow)
        .where(TableauActualisationRow.actualisation_id == actualisation_id)
    )).scalars().all())
    return {
        "total": len(rows),
        "proposal_status": dict(Counter(r.proposal_status for r in rows)),
        "anomaly_rows": sum(bool(r.anomalies_json) for r in rows),
        "reference_status": dict(Counter(r.reference_status for r in rows)),
    }
