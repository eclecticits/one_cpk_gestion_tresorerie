from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, has_any_permission, has_permission
from app.db.session import get_db
from app.models.user import User
from .repository import get_import, get_stats, list_anomalies, list_dossiers, list_imports, list_reports
from .schemas import (
    TableauAnomalieOut,
    TableauAnalyseOut,
    TableauComparisonOut,
    TableauComparisonRequest,
    TableauDecisionCreate,
    TableauDecisionOut,
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
    export_tableau,
    import_excel,
    run_analyse,
    run_comparison,
    set_reglages,
)

router = APIRouter(prefix="/tableau", tags=["Agent Tableau"])

VIEW_PERMS = ["secretariat.tableau.view", "secretariat.view"]
IMPORT_PERMS = ["secretariat.tableau.import"]
ANALYZE_PERMS = ["secretariat.tableau.analyze"]
COMPARE_PERMS = ["secretariat.tableau.compare"]
REPORT_PERMS = ["secretariat.tableau.generate_report"]
PV_PERMS = ["secretariat.tableau.generate_pv"]
EXPORT_PERMS = ["secretariat.tableau.export", "secretariat.tableau.view", "secretariat.view"]


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
    dependencies=[Depends(has_any_permission(IMPORT_PERMS + VIEW_PERMS))],
)
async def upload_excel(
    exercice: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> TableauImportResult:
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Fichier Excel (.xlsx ou .xls) requis.")
    content = await file.read()
    outcome = await import_excel(db, user, tenant_id, file.filename, content, exercice)
    n = outcome.imported
    avert = f" ({len(outcome.errors)} avertissement(s))" if outcome.errors else ""
    return TableauImportResult(
        success=True,
        import_id=outcome.imp.id,
        exercice=outcome.imp.exercice,
        file_name=outcome.imp.file_name,
        imported=outcome.imported,
        updated=outcome.updated,
        skipped=outcome.skipped,
        total_lignes=outcome.total,
        errors=outcome.errors,
        message=f"{n} membre(s) importé(s){avert}.",
    )


@router.get("/dossiers", response_model=list[TableauDossierOut], dependencies=[Depends(has_any_permission(VIEW_PERMS))])
async def list_tableau_dossiers(
    import_id: int | None = Query(default=None),
    exercice: str | None = Query(default=None),
    anomalie_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list:
    return await list_dossiers(db, tenant_id, import_id=import_id, exercice=exercice, anomalie_only=anomalie_only)


@router.post(
    "/analyse",
    response_model=TableauAnalyseOut,
    dependencies=[Depends(has_any_permission(ANALYZE_PERMS + VIEW_PERMS))],
)
async def analyse_import(
    import_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> object:
    return await run_analyse(db, user, tenant_id, import_id)


@router.put(
    "/reglages/{import_id}",
    dependencies=[Depends(has_any_permission(ANALYZE_PERMS + VIEW_PERMS))],
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
    dependencies=[Depends(has_any_permission(EXPORT_PERMS))],
)
async def export_tableau_xlsx(
    import_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> StreamingResponse:
    """Génère et télécharge le tableau provincial (.xlsx) avec les conclusions."""
    content, fname = await export_tableau(db, tenant_id, import_id)
    return StreamingResponse(
        iter([content]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/anomalies", response_model=list[TableauAnomalieOut], dependencies=[Depends(has_any_permission(VIEW_PERMS))])
async def list_tableau_anomalies(
    import_id: int | None = Query(default=None),
    gravite: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list:
    return await list_anomalies(db, tenant_id, import_id=import_id, gravite=gravite)


@router.post(
    "/compare",
    response_model=TableauComparisonOut,
    dependencies=[Depends(has_any_permission(COMPARE_PERMS + VIEW_PERMS))],
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
    dependencies=[Depends(has_any_permission(VIEW_PERMS))],
)
async def create_tableau_decision(
    payload: TableauDecisionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> object:
    return await create_decision(db, user, tenant_id, payload)


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
    dependencies=[Depends(has_any_permission(REPORT_PERMS + VIEW_PERMS))],
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
    dependencies=[Depends(has_any_permission(PV_PERMS + VIEW_PERMS))],
)
async def generate_tableau_pv(
    payload: TableauPVCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> object:
    return await create_pv(db, user, tenant_id, payload)
