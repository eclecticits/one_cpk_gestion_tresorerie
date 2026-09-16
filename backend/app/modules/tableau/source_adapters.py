"""Adaptateurs Excel du socle multi-source Tableau.

Les adaptateurs ne créent aucune donnée métier finale. Ils conservent la ligne
source telle qu'elle a été reçue et produisent uniquement une forme intermédiaire
destinée aux contrôles et aux futures étapes de normalisation.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any


SOURCE_TYPES = {
    "personnes_physiques",
    "personnes_morales",
    "chiffres_affaires",
    "assurances",
    "tableau",
}


def _norm(value: Any) -> str:
    text = "" if value is None else str(value)
    text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _json_value(value: Any) -> Any:
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _row_json(headers: list[str], values: tuple[Any, ...]) -> dict[str, Any]:
    """Conserve les intitulés et valeurs originales, sans conversion métier."""
    result: dict[str, Any] = {}
    for idx, header in enumerate(headers):
        key = header or f"__col_{idx + 1}"
        result[key] = _json_value(values[idx] if idx < len(values) else None)
    return result


def _header_map(headers: list[str]) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for header in headers:
        normalized = _norm(header)
        if "ordre" in normalized:
            mapped[header] = "numero_ordre"
        elif "cabinet" in normalized and "attach" in normalized:
            mapped[header] = "cabinet_attache"
        elif "nom employeur" in normalized or "employeur" in normalized:
            mapped[header] = "nom_employeur"
        elif normalized in {"nom", "noms", "membre", "nom post noms", "nom post noms et prenoms"} or "denomination" in normalized or "societe" in normalized:
            mapped[header] = "membre"
        elif "sexe" in normalized:
            mapped[header] = "sexe"
        elif "date" in normalized and "naiss" in normalized:
            mapped[header] = "date_naissance"
        elif "telephone" in normalized or "tel" in normalized:
            mapped[header] = "telephone"
        elif "email" in normalized or "mail" in normalized:
            mapped[header] = "email"
        elif normalized == "ville" or "ville" in normalized:
            mapped[header] = "ville"
        elif "adresse" in normalized:
            mapped[header] = "adresse"
        elif "statut" in normalized:
            mapped[header] = "statut"
        elif "impot" in normalized or normalized == "nif":
            mapped[header] = "nif"
        elif normalized == "actif" or normalized.startswith("actif "):
            mapped[header] = "actif"
        elif normalized == "assure" or normalized.startswith("assure "):
            mapped[header] = "assure"
        elif "amlco" in normalized:
            mapped[header] = "amlco"
        elif "120" in normalized and "for" in normalized:
            mapped[header] = "pourcentage_120_for"
        elif "80" in normalized and "for" in normalized:
            mapped[header] = "pourcentage_80_for"
        elif "cotisation" in normalized:
            mapped[header] = "cotisation"
        elif normalized == "solde" or "solde" in normalized:
            mapped[header] = "solde"
        elif "nb employ" in normalized:
            mapped[header] = "nb_employes"
        elif normalized in {"nb ec", "nombre ec"}:
            mapped[header] = "nb_ec"
        elif normalized in {"nb sta", "nombre sta"}:
            mapped[header] = "nb_sta"
        elif "annee souscription" in normalized:
            mapped[header] = "annee_souscription"
        elif "annee" in normalized:
            mapped[header] = "annee"
        elif "devise" in normalized or "currency" in normalized:
            mapped[header] = "devise"
        elif "ca facture" in normalized or "chiffre affaire facture" in normalized:
            mapped[header] = "ca_facture"
        elif "ca collecte" in normalized or "chiffre affaire collecte" in normalized:
            mapped[header] = "ca_collecte"
        elif "date mise" in normalized or "mise a jour" in normalized:
            mapped[header] = "date_mise_a_jour"
        elif "declare" in normalized:
            mapped[header] = "declare"
        elif "souscrit" in normalized:
            mapped[header] = "souscrit"
        elif "fin couverture" in normalized:
            mapped[header] = "fin_couverture"
        elif "assureur" in normalized:
            mapped[header] = "assureur"
        elif "periode" in normalized:
            mapped[header] = "periode"
        elif "statut" in normalized or "categorie" in normalized:
            mapped[header] = "statut"
    return mapped


@dataclass
class ParsedSourceRow:
    # La feuille d'où vient la ligne. Un classeur en porte plusieurs, et leurs
    # numéros de ligne se recouvrent : sans elle, « ligne 5 » désigne autant de
    # lignes qu'il y a d'onglets.
    feuille: str
    line_number: int
    raw_data: dict[str, Any]
    normalized_data: dict[str, Any]
    business_key_candidate: str | None
    errors: list[dict[str, Any]]


@dataclass
class SourceParseResult:
    rows: list[ParsedSourceRow]
    errors: list[dict[str, Any]]


class SourceAdapter:
    source_type: str
    required_any: tuple[set[str], ...]

    def __init__(self, source_type: str) -> None:
        self.source_type = source_type

    def validate_headers(self, mapped: set[str]) -> list[dict[str, Any]]:
        missing = [" / ".join(sorted(group)) for group in self.required_any if not (mapped & group)]
        if missing:
            return [{"ligne": 1, "champ": "headers", "message": f"Colonne requise absente : {'; '.join(missing)}"}]
        return []

    def normalize(self, mapped_row: dict[str, Any], line_number: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        errors: list[dict[str, Any]] = []
        normalized = dict(mapped_row)
        key = normalized.get("numero_ordre") or normalized.get("membre")
        if key is None or not str(key).strip():
            errors.append({"ligne": line_number, "champ": "numero_ordre", "message": "Clé métier absente"})
        return normalized, errors


class PersonnesPhysiquesAdapter(SourceAdapter):
    required_any = ({"numero_ordre"}, {"membre"})


class PersonnesMoralesAdapter(SourceAdapter):
    required_any = ({"numero_ordre"}, {"membre"})


class ChiffresAffairesAdapter(SourceAdapter):
    required_any = ({"numero_ordre", "membre"}, {"annee"})


class AssurancesAdapter(SourceAdapter):
    required_any = ({"numero_ordre", "membre"},)


class TableauSourceAdapter(SourceAdapter):
    required_any = ({"numero_ordre", "membre"},)


ADAPTERS = {
    "personnes_physiques": PersonnesPhysiquesAdapter("personnes_physiques"),
    "personnes_morales": PersonnesMoralesAdapter("personnes_morales"),
    "chiffres_affaires": ChiffresAffairesAdapter("chiffres_affaires"),
    "assurances": AssurancesAdapter("assurances"),
    "tableau": TableauSourceAdapter("tableau"),
}


def file_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def row_sha256(raw_data: dict[str, Any]) -> str:
    payload = json.dumps(raw_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def parse_source_excel(content: bytes, source_type: str) -> SourceParseResult:
    if source_type not in SOURCE_TYPES:
        return SourceParseResult([], [{"ligne": 1, "champ": "source_type", "message": f"Type de source inconnu : {source_type}"}])
    try:
        import openpyxl
        workbook = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    except Exception as exc:  # noqa: BLE001
        return SourceParseResult([], [{"ligne": 1, "champ": "fichier", "message": f"Impossible de lire le fichier Excel : {exc}"}])

    adapter = ADAPTERS[source_type]
    parsed: list[ParsedSourceRow] = []
    errors: list[dict[str, Any]] = []
    for worksheet in workbook.worksheets:
        rows = list(worksheet.iter_rows(values_only=True))
        if not rows:
            continue
        header_index = next((idx for idx, row in enumerate(rows[:15]) if len(_header_map([str(v or "") for v in row])) >= 2), None)
        if header_index is None:
            continue
        headers = [str(value or "") for value in rows[header_index]]
        mapped_headers = _header_map(headers)
        header_errors = adapter.validate_headers(set(mapped_headers.values()))
        errors.extend({**error, "feuille": worksheet.title} for error in header_errors)
        if header_errors:
            continue
        for offset, values in enumerate(rows[header_index + 1:], start=header_index + 2):
            raw = _row_json(headers, values)
            if not any(value not in (None, "") for value in values):
                continue
            mapped: dict[str, Any] = {}
            for idx, header in enumerate(headers):
                field = mapped_headers.get(header)
                if field and field not in mapped:
                    mapped[field] = _json_value(values[idx] if idx < len(values) else None)
            normalized, row_errors = adapter.normalize(mapped, offset)
            parsed.append(ParsedSourceRow(worksheet.title, offset, raw, normalized, str(normalized.get("numero_ordre") or normalized.get("membre") or "").strip() or None, row_errors))
            errors.extend({**error, "feuille": worksheet.title} for error in row_errors)
    if not parsed and not errors:
        errors.append({"ligne": 1, "champ": "headers", "message": "Aucune feuille exploitable détectée"})
    return SourceParseResult(parsed, errors)
