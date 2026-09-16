from __future__ import annotations

import logging
from collections import Counter
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, has_any_permission, has_permission
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
    TableauStatsOut,
    TableauActualisationListOut, TableauActualisationOut, TableauActualisationRowsOut,
    TableauActualisationRowOut, TableauActualisationStatsOut, TableauActualisationDetailOut,
)
from .service import (
    create_decision,
    create_pv,
    create_report,
    corriger_dossier,
    export_tableau,
    get_base_tableau,
    import_source_snapshot,
    get_reglages,
    import_excel,
    run_analyse,
    run_analyse_base,
    run_comparison,
    set_reglages,
)
from .actualisation_service import get_current_tableau_actualisation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tableau", tags=["Tableau"])

# Le Tableau ne s'ouvre plus sur le droit de consulter le Secrétariat : c'est un
# module à part, avec son propre droit de lecture.
VIEW_PERMS = ["tableau.view"]


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


async def _get_actual(db, tenant_id, actualisation_id):
    obj = (await db.execute(select(TableauActualisation).where(TableauActualisation.id == actualisation_id, TableauActualisation.organisation_id == tenant_id))).scalar_one_or_none()
    if obj is None:
        raise HTTPException(404, "Actualisation introuvable")
    return obj


@router.get("/actualisations", response_model=TableauActualisationListOut, dependencies=[Depends(has_any_permission(VIEW_PERMS))])
async def tableau_actualisations(date_situation: date | None = Query(None), db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)):
    where = [TableauActualisation.organisation_id == tenant_id]
    if date_situation: where.append(TableauActualisation.date_situation == date_situation)
    actuals = list((await db.execute(select(TableauActualisation).where(*where).order_by(TableauActualisation.date_situation.desc(), TableauActualisation.revision_number.desc()))).scalars().all())
    items = []
    for a in actuals:
        ni = (await db.execute(select(func.count(TableauActualisationInput.id)).where(TableauActualisationInput.actualisation_id == a.id))).scalar_one()
        nr = (await db.execute(select(func.count(TableauActualisationRow.id)).where(TableauActualisationRow.actualisation_id == a.id))).scalar_one()
        cur = await get_current_tableau_actualisation(db, organisation_id=tenant_id, date_situation=a.date_situation)
        items.append({"id": a.id, "date_situation": a.date_situation, "revision_number": a.revision_number, "actualized_at": a.actualized_at, "status": a.status, "reference_snapshot_id": a.reference_snapshot_id, "imports_count": ni, "total_rows": nr, "is_current": bool(cur and cur.id == a.id)})
    return {"items": items, "total": len(items)}


@router.get("/actualisations/{actualisation_id}", response_model=TableauActualisationOut, dependencies=[Depends(has_any_permission(VIEW_PERMS))])
async def tableau_actualisation(actualisation_id: int, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)):
    a = await _get_actual(db, tenant_id, actualisation_id)
    ni = (await db.execute(select(func.count(TableauActualisationInput.id)).where(TableauActualisationInput.actualisation_id == a.id))).scalar_one()
    nr = (await db.execute(select(func.count(TableauActualisationRow.id)).where(TableauActualisationRow.actualisation_id == a.id))).scalar_one()
    cur = await get_current_tableau_actualisation(db, organisation_id=tenant_id, date_situation=a.date_situation)
    return {"id": a.id, "date_situation": a.date_situation, "revision_number": a.revision_number, "actualized_at": a.actualized_at, "status": a.status, "reference_snapshot_id": a.reference_snapshot_id, "imports_count": ni, "total_rows": nr, "is_current": bool(cur and cur.id == a.id), "ruleset_version": a.ruleset_version, "knowledge_cutoff_at": (a.metadata_json or {}).get("knowledge_cutoff_at"), "metadata_json": a.metadata_json}


@router.get("/actualisations/{actualisation_id}/lignes", response_model=TableauActualisationRowsOut, dependencies=[Depends(has_any_permission(VIEW_PERMS))])
async def tableau_actualisation_lignes(actualisation_id: int, q: str | None = Query(None, max_length=120), proposal_status: str | None = None, reference_status: str | None = None, anomaly_only: bool = False, sort: Literal["numero_ordre", "proposal_status", "reference_status", "id"] = "numero_ordre", order: Literal["asc", "desc"] = "asc", limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)):
    await _get_actual(db, tenant_id, actualisation_id)
    where = [TableauActualisationRow.actualisation_id == actualisation_id]
    if q:
        name = TableauActualisationRow.proposed_values.op("->>")("nom_denomination")
        where.append(or_(TableauActualisationRow.numero_ordre.ilike(f"%{q}%"), name.ilike(f"%{q}%")))
    if proposal_status: where.append(TableauActualisationRow.proposal_status == proposal_status)
    if reference_status: where.append(TableauActualisationRow.reference_status == reference_status)
    if anomaly_only: where.append(func.jsonb_array_length(TableauActualisationRow.anomalies_json) > 0)
    cols = {"numero_ordre": TableauActualisationRow.numero_ordre, "proposal_status": TableauActualisationRow.proposal_status, "reference_status": TableauActualisationRow.reference_status, "id": TableauActualisationRow.id}
    col = cols[sort].desc() if order == "desc" else cols[sort]
    total = (await db.execute(select(func.count(TableauActualisationRow.id)).where(*where))).scalar_one()
    rows = list((await db.execute(select(TableauActualisationRow).where(*where).order_by(col).offset(offset).limit(limit))).scalars().all())
    return {"items": [_actualisation_row_payload(r) for r in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/actualisations/{actualisation_id}/lignes/{ligne_id}", response_model=TableauActualisationDetailOut, dependencies=[Depends(has_any_permission(VIEW_PERMS))])
async def tableau_actualisation_ligne(actualisation_id: int, ligne_id: int, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)):
    await _get_actual(db, tenant_id, actualisation_id)
    row = (await db.execute(select(TableauActualisationRow).where(TableauActualisationRow.id == ligne_id, TableauActualisationRow.actualisation_id == actualisation_id))).scalar_one_or_none()
    if row is None: raise HTTPException(404, "Ligne introuvable")
    out = _actualisation_row_payload(row)
    out["source_imports"] = [{"id": i.id, "import_id": i.import_id, "source_type": i.source_type, "date_situation": i.date_situation, "file_name": i.file_name, "file_sha256": i.file_sha256} for i in (await db.execute(select(TableauActualisationInput).where(TableauActualisationInput.actualisation_id == actualisation_id))).scalars().all()]
    out["ca_declarations"] = [{"id": x.id, "date_situation": x.date_situation, "annee": x.annee, "ca_facture": x.ca_facture, "ca_collecte": x.ca_collecte} for x in (await db.execute(select(TableauCaDeclaration).where(TableauCaDeclaration.identity_id == row.identity_id))).scalars().all()]
    out["insurance_declarations"] = [{"id": x.id, "date_situation": x.date_situation, "declare": x.declare_normalise, "souscrit": x.souscrit_normalise, "assureur": x.assureur_normalise} for x in (await db.execute(select(TableauInsuranceDeclaration).where(TableauInsuranceDeclaration.identity_id == row.identity_id))).scalars().all()]
    return out


@router.get("/actualisations/{actualisation_id}/stats", response_model=TableauActualisationStatsOut, dependencies=[Depends(has_any_permission(VIEW_PERMS))])
async def tableau_actualisation_stats(actualisation_id: int, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)):
    await _get_actual(db, tenant_id, actualisation_id)
    rows = list((await db.execute(select(TableauActualisationRow).where(TableauActualisationRow.actualisation_id == actualisation_id))).scalars().all())
    return {"total": len(rows), "proposal_status": dict(Counter(r.proposal_status for r in rows)), "anomaly_rows": sum(bool(r.anomalies_json) for r in rows), "reference_status": dict(Counter(r.reference_status for r in rows))}
