from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.orm.attributes import flag_modified

from app.models.user import User
from . import verdict as verdict_engine
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


@dataclass
class ImportOutcome:
    """Résultat standardisé d'un import (aligné sur le procédé budget)."""
    imp: TableauImport
    imported: int = 0
    updated: int = 0
    skipped: int = 0
    total: int = 0
    errors: list[dict] = field(default_factory=list)


_CATEGORIES_CONNUES = {"Société", "EC Cabinet", "EC Indépendant", "EC Salarié", "Stagiaire"}


def _valider_lignes(rows: list[dict]) -> list[dict]:
    """Contrôles non bloquants ligne par ligne -> [{ligne, champ, message}]."""
    errors: list[dict] = []
    for idx, row in enumerate(rows):
        ligne = idx + 2  # +1 en-tête, +1 base 1
        nom = row.get("nom") or "?"
        if not row.get("numero_ordre"):
            errors.append({"ligne": ligne, "champ": "numero_ordre",
                           "message": f"N° d'ordre manquant ({nom})"})
        if row.get("categorie") in (None, "", "Inconnu"):
            errors.append({"ligne": ligne, "champ": "categorie",
                           "message": f"Catégorie non reconnue ({nom})"})
    return errors


async def import_excel(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    file_name: str,
    content: bytes,
    exercice: str,
) -> ImportOutcome:
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

    # Erreur bloquante : fichier illisible / en-tête introuvable
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

    row_errors = _valider_lignes(rows)
    return ImportOutcome(
        imp=imp,
        imported=len(rows),
        updated=0,
        skipped=0,
        total=len(rows),
        errors=row_errors,
    )


async def run_analyse(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    import_id: int,
) -> TableauAnalyse:
    imp = await get_import(db, organisation_id, import_id)
    if imp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import introuvable")

    import re as _re
    _m = _re.search(r"(20\d{2})", str(imp.exercice or ""))
    exercice_annee = int(_m.group(1)) if _m else None

    # Réglages de délibération (seuil heures, seuil d'âge, action âge...),
    # configurables par organisation/import via metadata_json["reglages"].
    reglages = verdict_engine.TableauReglages.from_dict((imp.metadata_json or {}).get("reglages"))

    dossier_rows = await list_dossiers(db, organisation_id, import_id=import_id)
    dossier_dicts = []
    for d in dossier_rows:
        raw = d.raw_data or {}
        dossier_dicts.append({
            "id": d.id,
            "numero_ordre": d.numero_ordre,
            "nom": d.nom,
            "prenom": d.prenom,
            "categorie": d.categorie,
            "cotisation_payee": d.cotisation_payee,
            "heures_forco": float(d.heures_forco) if d.heures_forco is not None else None,
            "assurance": d.assurance,
            "chiffre_affaires": d.chiffre_affaires,
            "hformation": raw.get("hformation"),
            "anciennete": d.anciennete,
            "age": d.age,
        })

    verdicts = {
        dd["id"]: verdict_engine.evaluer(dd, exercice_annee, reglages) for dd in dossier_dicts
    }
    anomaly_dicts = detect_anomalies(dossier_dicts, exercice_annee)
    stats = compute_analyse_stats(dossier_dicts, anomaly_dicts, verdicts)

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
        v = verdicts.get(d.id, {})
        conclusion = v.get("conclusion") or "analysé"
        # colonnes dédiées
        d.conclusion = conclusion
        d.conclusion_motif = v.get("motif")
        d.statut_dossier = conclusion  # compat UI existante
        # exemptions conservées dans raw_data (JSONB)
        raw = dict(d.raw_data or {})
        raw["exemptions"] = v.get("exemptions")
        d.raw_data = raw
        flag_modified(d, "raw_data")

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


async def set_reglages(
    db: AsyncSession,
    organisation_id: int,
    import_id: int,
    reglages: dict,
) -> dict:
    """Enregistre les réglages de délibération sur un import (metadata_json)."""
    imp = await get_import(db, organisation_id, import_id)
    if imp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import introuvable")
    meta = dict(imp.metadata_json or {})
    current = dict(meta.get("reglages") or {})
    current.update({k: v for k, v in reglages.items() if v is not None})
    # valider via le dataclass (ignore les clés inconnues)
    validated = verdict_engine.TableauReglages.from_dict(current)
    meta["reglages"] = validated.__dict__
    imp.metadata_json = meta
    flag_modified(imp, "metadata_json")
    await db.commit()
    return meta["reglages"]


async def export_tableau(
    db: AsyncSession,
    organisation_id: int,
    import_id: int,
    organisation_nom: str = "CONSEIL PROVINCIAL",
) -> tuple[bytes, str]:
    """Génère le tableau provincial de sortie (.xlsx). Renvoie (octets, nom_fichier)."""
    from .exporter import build_workbook

    imp = await get_import(db, organisation_id, import_id)
    if imp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import introuvable")

    import re as _re
    _m = _re.search(r"(20\d{2})", str(imp.exercice or ""))
    exercice_annee = int(_m.group(1)) if _m else None
    reglages = verdict_engine.TableauReglages.from_dict((imp.metadata_json or {}).get("reglages"))

    dossier_rows = await list_dossiers(db, organisation_id, import_id=import_id)
    dossiers = [
        {
            "numero_ordre": d.numero_ordre,
            "nom": d.nom,
            "prenom": d.prenom,
            "categorie": d.categorie,
            "cotisation_payee": d.cotisation_payee,
            "assurance": d.assurance,
            "chiffre_affaires": d.chiffre_affaires,
            "heures_forco": float(d.heures_forco) if d.heures_forco is not None else None,
            "sexe": d.sexe,
            "date_naissance": d.date_naissance.isoformat() if d.date_naissance else None,
            "age": d.age,
            "nif": d.nif,
            "anciennete": d.anciennete,
            "telephone": d.telephone,
            "email": d.email,
            "cabinet": d.cabinet,
            "raw_data": d.raw_data or {},
        }
        for d in dossier_rows
    ]
    content = build_workbook(dossiers, imp.exercice, reglages, exercice_annee, organisation_nom)
    fname = f"Tableau_{imp.exercice}_{import_id}.xlsx"
    return content, fname


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
