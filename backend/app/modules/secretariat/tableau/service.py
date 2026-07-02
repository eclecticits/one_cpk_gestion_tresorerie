from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from .analyzer import compute_analyse_stats, detect_anomalies
from .comparison import compare_exercices
from .excel_import import parse_excel_bytes
from .models import TableauAnalyse, TableauAnomalie, TableauDecision, TableauDossier, TableauImport, TableauReport
from .report_generator import generate_analyse_report, generate_pv
from .repository import (
    get_analyse_for_import,
    get_import,
    get_stats,
    list_anomalies,
    list_dossiers,
    list_imports,
    list_reports,
)
from .schemas import TableauDecisionCreate, TableauPVCreate, TableauReportCreate


async def import_excel(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    file_name: str,
    content: bytes,
    exercice: str,
) -> TableauImport:
    rows, errors = parse_excel_bytes(content, exercice)

    imp = TableauImport(
        organisation_id=organisation_id,
        user_id=user.id,
        exercice=exercice,
        file_name=file_name,
        status="processing" if not errors else "error",
        total_rows=len(rows),
        imported_rows=0,
        error_message="; ".join(errors) if errors else None,
    )
    db.add(imp)
    await db.flush()

    if errors and not rows:
        await db.commit()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="; ".join(errors))

    for row in rows:
        dossier = TableauDossier(
            organisation_id=organisation_id,
            import_id=imp.id,
            **{k: v for k, v in row.items() if k != "id"},
        )
        db.add(dossier)

    imp.imported_rows = len(rows)
    imp.status = "completed"
    await db.commit()
    return imp


async def run_analyse(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    import_id: int,
) -> TableauAnalyse:
    imp = await get_import(db, organisation_id, import_id)
    if imp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import introuvable")

    dossier_rows = await list_dossiers(db, organisation_id, import_id=import_id)
    dossier_dicts = [
        {
            "id": d.id,
            "nom": d.nom,
            "prenom": d.prenom,
            "categorie": d.categorie,
            "cotisation_payee": d.cotisation_payee,
            "heures_forco": float(d.heures_forco) if d.heures_forco is not None else None,
            "assurance": d.assurance,
        }
        for d in dossier_rows
    ]

    anomaly_dicts = detect_anomalies(dossier_dicts)
    stats = compute_analyse_stats(dossier_dicts, anomaly_dicts)

    existing = await get_analyse_for_import(db, organisation_id, import_id)
    if existing:
        for k, v in stats.items():
            setattr(existing, k, v)
        existing.status = "completed"
        existing.updated_at = datetime.now(timezone.utc)
        analyse = existing
    else:
        analyse = TableauAnalyse(
            organisation_id=organisation_id,
            import_id=import_id,
            exercice=imp.exercice,
            status="completed",
            **stats,
        )
        db.add(analyse)

    await db.flush()

    for d in dossier_rows:
        d.anomalie_detectee = any(a["dossier_id"] == d.id for a in anomaly_dicts)
        dossier_incomplet = (
            d.cotisation_payee is None or d.heures_forco is None or d.assurance is None
        )
        d.statut_dossier = "incomplet" if dossier_incomplet else "analysé"

    res = await db.execute(
        select(TableauAnomalie)
        .join(TableauDossier, TableauAnomalie.dossier_id == TableauDossier.id)
        .where(TableauDossier.import_id == import_id, TableauDossier.organisation_id == organisation_id)
    )
    for old in res.scalars().all():
        await db.delete(old)
    await db.flush()

    for a_dict in anomaly_dicts:
        db.add(TableauAnomalie(
            organisation_id=organisation_id,
            **a_dict,
        ))

    await db.commit()
    return analyse


async def run_comparison(
    db: AsyncSession,
    organisation_id: int,
    exercice_a: str,
    exercice_b: str,
) -> dict:
    dossiers_a_rows = await list_dossiers(db, organisation_id, exercice=exercice_a)
    dossiers_b_rows = await list_dossiers(db, organisation_id, exercice=exercice_b)

    if not dossiers_a_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Aucun dossier pour l'exercice {exercice_a}")
    if not dossiers_b_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Aucun dossier pour l'exercice {exercice_b}")

    def to_dict(d: TableauDossier) -> dict:
        return {"id": d.id, "nom": d.nom, "prenom": d.prenom, "categorie": d.categorie}

    return compare_exercices(
        [to_dict(d) for d in dossiers_a_rows],
        [to_dict(d) for d in dossiers_b_rows],
        exercice_a,
        exercice_b,
    )


async def create_decision(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    payload: TableauDecisionCreate,
) -> TableauDecision:
    decision = TableauDecision(
        organisation_id=organisation_id,
        user_id=user.id,
        dossier_id=payload.dossier_id,
        type_decision=payload.type_decision,
        decision=payload.decision,
        motif=payload.motif,
        observations=payload.observations,
    )
    db.add(decision)
    await db.commit()
    return decision


async def create_report(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    payload: TableauReportCreate,
) -> TableauReport:
    imp = await get_import(db, organisation_id, payload.import_id)
    if imp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import introuvable")

    analyse = await get_analyse_for_import(db, organisation_id, payload.import_id)
    anomaly_rows = await list_anomalies(db, organisation_id, import_id=payload.import_id)
    anomaly_dicts = [
        {"dossier_id": a.dossier_id, "type_anomalie": a.type_anomalie, "gravite": a.gravite, "description": a.description}
        for a in anomaly_rows
    ]

    stats = {
        "total_dossiers": analyse.total_dossiers if analyse else 0,
        "dossiers_complets": analyse.dossiers_complets if analyse else 0,
        "dossiers_incomplets": analyse.dossiers_incomplets if analyse else 0,
        "anomalies_count": analyse.anomalies_count if analyse else 0,
        "doublons_count": analyse.doublons_count if analyse else 0,
        "cotisations_non_payees": analyse.cotisations_non_payees if analyse else 0,
        "heures_forco_insuffisantes": analyse.heures_forco_insuffisantes if analyse else 0,
        "assurances_manquantes": analyse.assurances_manquantes if analyse else 0,
        "stats_json": analyse.stats_json if analyse else {},
    }

    contenu = generate_analyse_report(payload.exercice, stats, anomaly_dicts, payload.instructions)

    report = TableauReport(
        organisation_id=organisation_id,
        user_id=user.id,
        import_id=payload.import_id,
        exercice=payload.exercice,
        type_rapport=payload.type_rapport,
        titre=payload.titre,
        contenu=contenu,
        format_sortie="text",
        status="draft",
    )
    db.add(report)
    await db.commit()
    return report


async def create_pv(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    payload: TableauPVCreate,
) -> TableauReport:
    imp = await get_import(db, organisation_id, payload.import_id)
    if imp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import introuvable")

    analyse = await get_analyse_for_import(db, organisation_id, payload.import_id)
    stats = {
        "total_dossiers": analyse.total_dossiers if analyse else 0,
        "dossiers_complets": analyse.dossiers_complets if analyse else 0,
        "anomalies_count": analyse.anomalies_count if analyse else 0,
    }

    res = await db.execute(
        select(TableauDecision).where(
            TableauDecision.organisation_id == organisation_id,
        ).order_by(TableauDecision.created_at.desc()).limit(50)
    )
    decisions = [
        {"dossier_id": d.dossier_id, "type_decision": d.type_decision, "decision": d.decision, "motif": d.motif}
        for d in res.scalars().all()
    ]

    contenu = generate_pv(payload.exercice, stats, decisions, payload.instructions)

    report = TableauReport(
        organisation_id=organisation_id,
        user_id=user.id,
        import_id=payload.import_id,
        exercice=payload.exercice,
        type_rapport="pv",
        titre=f"Procès-verbal Commission Tableau — {payload.exercice}",
        contenu=contenu,
        format_sortie="text",
        status="draft",
    )
    db.add(report)
    await db.commit()
    return report
