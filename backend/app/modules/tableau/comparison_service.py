"""Comparaison diagnostique projection préparatoire / Tableau historique."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import TableauDossier, TableauImport
from .service import PreparatoryTableauProjection, PreparatoryTableauRow, build_preparatory_tableau_at_date, _norm_numero_ordre


@dataclass
class FieldDifference:
    field: str
    preparatory_value: Any
    historical_value: Any
    normalized_preparatory_value: Any
    normalized_historical_value: Any
    difference_code: str


@dataclass
class ComparisonRow:
    numero_ordre: str | None
    presence_status: str
    preparatory_identity_id: int | None = None
    historical_dossier_id: int | None = None
    preparatory_name: str | None = None
    historical_name: str | None = None
    preparatory_category: str | None = None
    historical_category: str | None = None
    normalized_preparatory_category: str | None = None
    normalized_historical_category: str | None = None
    differences: list[FieldDifference] = field(default_factory=list)
    comparison_status: str = "IDENTICAL"
    preparatory_projection_status: str | None = None


@dataclass
class PreparatoryHistoricalComparison:
    preparatory_evaluation_date: date
    historical_date_situation: date
    rows: list[ComparisonRow] = field(default_factory=list)
    total_preparatory: int = 0
    total_historical: int = 0
    total_matched: int = 0
    total_preparatory_only: int = 0
    total_historical_only: int = 0
    total_identical: int = 0
    total_different: int = 0
    total_blocked: int = 0
    difference_counts: dict[str, int] = field(default_factory=dict)
    historical_duplicate_keys: int = 0


def _text(value: Any) -> str | None:
    if value is None:
        return None
    value = " ".join(str(value).split()).strip()
    return value.casefold() if value else None


def normalize_comparison_category(value: str | None) -> str | None:
    token = " ".join(str(value or "").split()).casefold()
    token = "".join(c for c in unicodedata.normalize("NFKD", token) if not unicodedata.combining(c))
    token = re.sub(r"[^a-z0-9 ]+", "", token)
    return {"sec": "societe", "societe": "societe", "ec cabinet": "ec cabinet", "ec independant": "ec independant", "ec salarie": "ec salarie"}.get(token, token or None)


def _add_difference(row: ComparisonRow, field: str, preparatory: Any, historical: Any, code: str, normalize=_text) -> None:
    row.differences.append(FieldDifference(field, preparatory, historical, normalize(preparatory), normalize(historical), code))


async def compare_preparatory_to_historical(
    db: AsyncSession, organisation_id: int, evaluation_date: date, historical_import_id: int
) -> PreparatoryHistoricalComparison:
    historical_import = (await db.execute(select(TableauImport).where(
        TableauImport.id == historical_import_id,
        TableauImport.organisation_id == organisation_id,
    ))).scalar_one_or_none()
    if historical_import is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import historique hors organisation ou inexistant")
    projection: PreparatoryTableauProjection = await build_preparatory_tableau_at_date(db, organisation_id, evaluation_date)
    dossiers = (await db.execute(select(TableauDossier).where(
        TableauDossier.organisation_id == organisation_id,
        TableauDossier.import_id == historical_import_id,
    ).order_by(TableauDossier.id.asc()))).scalars().all()
    historical_by_key: dict[str, TableauDossier] = {}
    historical_duplicates: dict[str, int] = {}
    for dossier in dossiers:
        key = _norm_numero_ordre(dossier.numero_ordre)
        if key:
            if key in historical_by_key:
                historical_duplicates[key] = historical_duplicates.get(key, 1) + 1
            else:
                historical_by_key[key] = dossier
    prep_by_key = {row.numero_ordre: row for row in projection.rows}
    result = PreparatoryHistoricalComparison(evaluation_date, historical_import.date_situation)
    result.historical_duplicate_keys = len(historical_duplicates)
    result.total_preparatory = len(projection.rows)
    result.total_historical = len(historical_by_key)
    for key in sorted(set(prep_by_key) | set(historical_by_key)):
        prep = prep_by_key.get(key)
        hist = historical_by_key.get(key)
        if prep is None:
            row = ComparisonRow(key, "HISTORICAL_ONLY", historical_dossier_id=hist.id, historical_name=hist.nom, historical_category=hist.categorie, normalized_historical_category=normalize_comparison_category(hist.categorie))
            if key in historical_duplicates:
                _add_difference(row, "numero_ordre", key, key, "HISTORICAL_DUPLICATE_KEY", lambda v: v)
            result.rows.append(row)
            result.total_historical_only += 1
            continue
        if hist is None:
            row = ComparisonRow(key, "PREPARATORY_ONLY", preparatory_identity_id=prep.identity_id, preparatory_name=prep.nom_denomination, preparatory_category=prep.tableau_category, normalized_preparatory_category=normalize_comparison_category(prep.tableau_category), preparatory_projection_status=prep.projection_status)
            result.rows.append(row); result.total_preparatory_only += 1
            if prep.projection_status == "BLOCKED": result.total_blocked += 1; row.comparison_status = "BLOCKED"
            continue
        row = ComparisonRow(key, "MATCHED", prep.identity_id, hist.id, prep.nom_denomination, hist.nom, prep.tableau_category, hist.categorie, normalize_comparison_category(prep.tableau_category), normalize_comparison_category(hist.categorie), preparatory_projection_status=prep.projection_status)
        result.total_matched += 1
        if key in historical_duplicates:
            _add_difference(row, "numero_ordre", key, key, "HISTORICAL_DUPLICATE_KEY", lambda v: v)
        if _text(prep.nom_denomination) != _text(hist.nom): _add_difference(row, "nom_denomination", prep.nom_denomination, hist.nom, "NAME_MISMATCH")
        if row.normalized_preparatory_category != row.normalized_historical_category: _add_difference(row, "tableau_category", prep.tableau_category, hist.categorie, "CATEGORY_MISMATCH", normalize_comparison_category)
        if prep.assure_source is not None and hist.assurance is not None and prep.assure_source != bool(hist.assurance): _add_difference(row, "assure_source", prep.assure_source, hist.assurance, "INSURANCE_SOURCE_MISMATCH", lambda v: v)
        if prep.projection_status == "BLOCKED": row.comparison_status = "BLOCKED"; result.total_blocked += 1
        elif row.differences: row.comparison_status = "DIFFERENT"; result.total_different += 1
        else: row.comparison_status = "IDENTICAL"; result.total_identical += 1
        result.rows.append(row)
        for difference in row.differences: result.difference_counts[difference.difference_code] = result.difference_counts.get(difference.difference_code, 0) + 1
    if evaluation_date != historical_import.date_situation:
        for row in result.rows:
            row.differences.append(FieldDifference("date_context", evaluation_date, historical_import.date_situation, evaluation_date, historical_import.date_situation, "DATE_CONTEXT_MISMATCH"))
    return result
