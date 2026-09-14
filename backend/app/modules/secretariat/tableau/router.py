from __future__ import annotations

import logging
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, has_any_permission, has_permission
from app.db.session import get_db
from app.models.organisation import Organisation
from app.models.user import User
from .models import TableauImport
from .repository import dernier_exercice, get_analyse_for_import, get_import, get_stats, list_anomalies, list_dossiers, list_imports, list_reports
from .schemas import (
    TableauAnomalieOut,
    TableauAnalyseOut,
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
    TableauStatsOut,
)
from .service import (
    create_decision,
    create_pv,
    create_report,
    corriger_dossier,
    export_tableau,
    get_base_tableau,
    import_excel,
    run_analyse,
    run_analyse_base,
    run_comparison,
    set_reglages,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tableau", tags=["Agent Tableau"])

VIEW_PERMS = ["secretariat.tableau.view", "secretariat.view"]
@router.get("/stats", response_model=TableauStatsOut, dependencies=[Depends(has_any_permission(VIEW_PERMS))])
async def tableau_stats(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> dict:
    return await get_stats(db, tenant_id)


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
    dependencies=[Depends(has_permission("secretariat.tableau.import"))],
)
async def upload_excel(
    exercice: str = Form(...),
    date_situation: date = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> TableauImportResult:
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Fichier Excel (.xlsx ou .xls) requis.")
    content = await file.read()
    outcome = await import_excel(db, user, tenant_id, file.filename, content, exercice, date_situation=date_situation)
    n = outcome.imported
    avert = f" ({len(outcome.errors)} avertissement(s))" if outcome.errors else ""
    return TableauImportResult(
        success=True,
        import_id=outcome.imp.id,
        exercice=outcome.imp.exercice,
        date_situation=outcome.imp.date_situation,
        file_name=outcome.imp.file_name,
        imported=outcome.imported,
        updated=outcome.updated,
        skipped=outcome.skipped,
        total_lignes=outcome.total,
        reprises=outcome.reprises,
        decisions_reportees=outcome.decisions_reportees,
        nouveaux_membres=outcome.nouveaux_membres,
        errors=outcome.errors,
        message=f"{n} membre(s) importé(s){avert}.",
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
    dependencies=[Depends(has_permission("secretariat.tableau.analyze"))],
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
    dependencies=[Depends(has_permission("secretariat.tableau.analyze"))],
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


@router.put(
    "/reglages/{import_id}",
    dependencies=[Depends(has_permission("secretariat.tableau.analyze"))],
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
    dependencies=[Depends(has_permission("secretariat.tableau.export"))],
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
    dependencies=[Depends(has_permission("secretariat.tableau.compare"))],
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
    dependencies=[Depends(has_permission("secretariat.tableau.decide"))],
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
    dependencies=[Depends(has_permission("secretariat.tableau.correct"))],
)
async def corriger_tableau_dossier(
    dossier_id: int,
    payload: TableauDossierCorrection,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> object:
    return await corriger_dossier(db, user, tenant_id, dossier_id, payload)


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
    dependencies=[Depends(has_permission("secretariat.tableau.generate_report"))],
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
    dependencies=[Depends(has_permission("secretariat.tableau.generate_pv"))],
)
async def generate_tableau_pv(
    payload: TableauPVCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> object:
    return await create_pv(db, user, tenant_id, payload)
