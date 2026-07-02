from __future__ import annotations

import io
from typing import Any

CATEGORIE_ALIASES = {
    "sec": "SEC",
    "ec cabinet": "EC Cabinet",
    "ec indépendant": "EC Indépendant",
    "ec independant": "EC Indépendant",
    "ec salarié": "EC Salarié",
    "ec salarie": "EC Salarié",
}

REQUIRED_FIELDS = ["nom"]

COLUMN_MAP: dict[str, list[str]] = {
    "numero_ordre": ["n°", "no", "numero", "ordre", "numéro"],
    "nom": ["nom", "name"],
    "prenom": ["prénom", "prenom", "firstname"],
    "categorie": ["catégorie", "categorie", "category"],
    "statut_membre": ["statut", "status", "statut membre"],
    "cotisation_montant": ["cotisation", "montant cotisation", "cotisation montant"],
    "cotisation_payee": ["cotisation payée", "payée", "paye", "payee"],
    "heures_forco": ["heures forco", "forco", "heures", "heure"],
    "assurance": ["assurance", "assuré", "assure"],
    "email": ["email", "e-mail", "courriel", "mail"],
    "telephone": ["téléphone", "telephone", "tel", "tél"],
    "adresse": ["adresse", "address"],
    "cabinet": ["cabinet", "entreprise", "société", "societe"],
}


def _normalize_col(col: str) -> str:
    return str(col).strip().lower()


def _map_columns(headers: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, raw in enumerate(headers):
        norm = _normalize_col(raw)
        for field, aliases in COLUMN_MAP.items():
            if norm in aliases and field not in mapping:
                mapping[field] = idx
    return mapping


def _parse_bool(val: Any) -> bool | None:
    if val is None:
        return None
    s = str(val).strip().lower()
    if s in ("oui", "yes", "1", "true", "✓", "x", "ok"):
        return True
    if s in ("non", "no", "0", "false", "", "-"):
        return False
    return None


def _parse_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        s = str(val).replace(",", ".").replace(" ", "").replace("\xa0", "")
        return float(s) if s else None
    except (ValueError, TypeError):
        return None


def parse_excel_bytes(content: bytes, exercice: str) -> tuple[list[dict], list[str]]:
    """Parse Excel bytes and return (rows, errors). Requires openpyxl."""
    try:
        import openpyxl
    except ImportError:
        return [], ["openpyxl non installé — pip install openpyxl"]

    errors: list[str] = []
    rows: list[dict] = []

    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    except Exception as exc:
        return [], [f"Impossible de lire le fichier Excel : {exc}"]

    ws = wb.active
    if ws is None:
        return [], ["Aucune feuille active dans le fichier"]

    all_rows = list(ws.iter_rows(values_only=True))
    if not all_rows:
        return [], ["Fichier vide"]

    headers = [str(h) if h is not None else "" for h in all_rows[0]]
    col_map = _map_columns(headers)

    if "nom" not in col_map:
        errors.append("Colonne 'nom' introuvable dans les en-têtes")

    for row_idx, row in enumerate(all_rows[1:], start=2):
        def get(field: str) -> Any:
            idx = col_map.get(field)
            return row[idx] if idx is not None and idx < len(row) else None

        nom = str(get("nom") or "").strip()
        if not nom:
            continue

        categorie_raw = str(get("categorie") or "").strip()
        categorie = CATEGORIE_ALIASES.get(categorie_raw.lower(), categorie_raw or "Inconnu")

        record: dict[str, Any] = {
            "exercice": exercice,
            "numero_ordre": str(get("numero_ordre") or "").strip() or None,
            "nom": nom,
            "prenom": str(get("prenom") or "").strip() or None,
            "categorie": categorie,
            "statut_membre": str(get("statut_membre") or "").strip() or None,
            "cotisation_montant": _parse_float(get("cotisation_montant")),
            "cotisation_payee": _parse_bool(get("cotisation_payee")),
            "heures_forco": _parse_float(get("heures_forco")),
            "assurance": _parse_bool(get("assurance")),
            "email": str(get("email") or "").strip() or None,
            "telephone": str(get("telephone") or "").strip() or None,
            "adresse": str(get("adresse") or "").strip() or None,
            "cabinet": str(get("cabinet") or "").strip() or None,
            "statut_dossier": "imported",
            "raw_data": {str(h): row[i] for i, h in enumerate(headers) if i < len(row)},
        }
        rows.append(record)

    return rows, errors
