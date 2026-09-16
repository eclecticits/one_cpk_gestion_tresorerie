"""Import Excel des tableaux ONEC (membres personnes physiques / sociétés).

Gère les fichiers réels :
- plusieurs feuilles (une par section : SEC, Cabinet, Indépendant, Salariés,
  Stagiaires) OU une feuille à plat exportée du portail ;
- lignes de titre avant l'en-tête (l'en-tête n'est pas forcément en ligne 1) ;
- colonne A vide ou décalage ;
- noms de colonnes variables (correspondance souple par mots-clés).

La catégorie est déduite du nom de la feuille, sinon d'une colonne
« Statut / Catégorie » sur une feuille à plat.

Les colonnes du modèle SQL sont renseignées directement ; les champs
supplémentaires utiles à la délibération (date de naissance, chiffre
d'affaires, ancienneté, NIF, sexe, H.Formation source) sont stockés dans
`raw_data` (JSONB) pour rester rétro-compatible avec le schéma existant.
"""
from __future__ import annotations

import datetime
import io
import re
import unicodedata
from typing import Any

REQUIRED_FIELDS = ["nom"]

# Jeton présent dans la ligne d'en-tête (au moins un requis)
_HEADER_TOKENS = ("nom", "denomination", "ordre")


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _norm(value: Any) -> str:
    s = _strip_accents(str(value or "")).lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _match_field(norm_header: str) -> str | None:
    """Associe un en-tête normalisé à un champ logique (du plus spécifique au plus général)."""
    nh = norm_header
    if not nh:
        return None
    if "nhv" in nh:
        return "heures_forco"
    if "date" in nh and "naiss" in nh:
        return "date_naissance"
    if "naiss" in nh and "lieu" not in nh:
        return "date_naissance"
    if "ordre" in nh:
        return "numero_ordre"
    if "post" in nh and "nom" in nh:
        return "nom"
    if nh in ("nom", "noms") or nh.startswith("nom "):
        return "nom"
    if "denomination" in nh:
        return "nom"
    if "prenom" in nh:
        return "prenom"
    if "raison" in nh:
        return "raison_sociale"
    if "gerant" in nh or "associe" in nh:
        return "gerant"
    if "sexe" in nh:
        return "sexe"
    if "mail" in nh:
        return "email"
    if "tel" in nh:
        return "telephone"
    if "nif" in nh or "impot" in nh:
        return "nif"
    if "cabinet" in nh:
        return "cabinet"
    if "employeur" in nh:
        return "employeur"
    if "adresse" in nh:
        return "adresse"
    if "ville" in nh:
        return "ville"
    if "anciennet" in nh:
        return "anciennete"
    if "cotisation" in nh:
        return "cotisation"
    if "assurance" in nh:
        return "assurance"
    if "affaire" in nh or "chiffre" in nh:
        return "chiffre_affaires"
    if "statut" in nh or "categorie" in nh:
        return "statut"
    if "formation" in nh:
        return "hformation"
    if "conclusion" in nh:
        return "conclusion_src"
    return None


_CATEGORIE_SHEET = (
    ("stagiaire", "Stagiaire"),
    ("societe", "Société"),
    ("sec", "Société"),
    ("cabinet", "EC Cabinet"),
    ("independant", "EC Indépendant"),
    ("indep", "EC Indépendant"),
    ("salarie", "EC Salarié"),
)

_CATEGORIE_ALIASES = {
    "en cabinet": "EC Cabinet",
    "cabinet": "EC Cabinet",
    "independant": "EC Indépendant",
    "salarie": "EC Salarié",
    "societe": "Société",
    "sec": "Société",
    "stagiaire": "Stagiaire",
}


def _categorie_from_sheet(title: str) -> str | None:
    t = _norm(title)
    for token, cat in _CATEGORIE_SHEET:
        if token in t:
            return cat
    return None


def _categorie_from_statut(value: Any) -> str:
    v = _norm(value)
    for token, cat in _CATEGORIE_ALIASES.items():
        if token in v:
            return cat
    return "Inconnu"


def _parse_bool(value: Any) -> bool | None:
    if value is None:
        return None
    s = _norm(value)
    if s in ("oui", "yes", "1", "true", "x", "ok", "o"):
        return True
    if s in ("non", "no", "0", "false", "n"):
        return False
    return None  # NA, vide, non applicable -> inconnu


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        s = re.sub(r"[^0-9.\-]", "", str(value).replace(",", ".").strip())
        return float(s) if s not in ("", "-", ".") else None
    except (ValueError, TypeError):
        return None


def _parse_date(value: Any) -> datetime.date | None:
    if value is None:
        return None
    if isinstance(value, (datetime.datetime, datetime.date)):
        return datetime.date(value.year, value.month, value.day)
    s = str(value).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%m/%d/%Y", "%d/%m/%y"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _find_header_row(rows: list[tuple]) -> int | None:
    """Repère la ligne d'en-tête (dans les 15 premières lignes)."""
    for i, row in enumerate(rows[:15]):
        joined = " ".join(_norm(c) for c in row)
        if not any(tok in joined for tok in _HEADER_TOKENS):
            continue
        recognised = sum(1 for c in row if _match_field(_norm(c)))
        if recognised >= 3:
            return i
    return None


def _compute_age(d: datetime.date | None, exercice_annee: int | None) -> int | None:
    if not d:
        return None
    ref = exercice_annee or datetime.date.today().year
    return ref - d.year


def parse_excel_bytes(content: bytes, exercice: str) -> tuple[list[dict], list[str]]:
    """Parse un classeur Excel et renvoie (lignes, erreurs).

    Chaque ligne est un dict prêt pour le modèle TableauDossier, avec les
    champs de délibération dans `raw_data`.
    """
    try:
        import openpyxl
    except ImportError:
        return [], ["openpyxl non installé — pip install openpyxl"]

    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    except Exception as exc:  # noqa: BLE001
        return [], [f"Impossible de lire le fichier Excel : {exc}"]

    exercice_annee = None
    m = re.search(r"(20\d{2})", str(exercice))
    if m:
        exercice_annee = int(m.group(1))

    errors: list[str] = []
    rows: list[dict] = []
    sheets_ok = 0

    for ws in wb.worksheets:
        all_rows = list(ws.iter_rows(values_only=True))
        if not all_rows:
            continue
        header_idx = _find_header_row(all_rows)
        if header_idx is None:
            continue
        sheets_ok += 1

        headers = list(all_rows[header_idx])
        col_map: dict[str, int] = {}
        for idx, raw in enumerate(headers):
            field = _match_field(_norm(raw))
            if field and field not in col_map:
                col_map[field] = idx

        cat_sheet = _categorie_from_sheet(ws.title)

        for row in all_rows[header_idx + 1:]:
            def get(field: str, _row=row) -> Any:
                idx = col_map.get(field)
                return _row[idx] if idx is not None and idx < len(_row) else None

            nom = _text(get("nom"))
            if not nom:
                continue

            categorie = cat_sheet or _categorie_from_statut(get("statut"))
            date_naissance = _parse_date(get("date_naissance"))
            heures = _parse_float(get("heures_forco"))
            cabinet = _text(get("cabinet")) or _text(get("employeur"))
            anciennete = _text(get("anciennete"))

            # Champs conservés dans raw_data (non promus en colonnes)
            raw_extra = {
                "sheet": ws.title,
                "hformation": _parse_bool(get("hformation")),
                "raison_sociale": _text(get("raison_sociale")),
                "gerant": _text(get("gerant")),
                "conclusion_source": _text(get("conclusion_src")),
            }

            record: dict[str, Any] = {
                "exercice": exercice,
                "numero_ordre": _text(get("numero_ordre")),
                "nom": nom,
                "prenom": _text(get("prenom")),
                "categorie": categorie,
                "statut_membre": _text(get("statut")) or anciennete,
                "cotisation_montant": None,
                "cotisation_payee": _parse_bool(get("cotisation")),
                "heures_forco": heures,
                "assurance": _parse_bool(get("assurance")),
                "chiffre_affaires": _parse_bool(get("chiffre_affaires")),
                "sexe": _text(get("sexe")),
                "date_naissance": date_naissance,
                "age": _compute_age(date_naissance, exercice_annee),
                "nif": _text(get("nif")),
                "anciennete": anciennete,
                "email": _text(get("email")),
                "telephone": _text(get("telephone")),
                "adresse": _text(get("adresse")),
                "cabinet": cabinet,
                "statut_dossier": "imported",
                "raw_data": raw_extra,
            }
            rows.append(record)

    if sheets_ok == 0:
        errors.append("Aucune feuille exploitable : en-tête (Nom / N° d'ordre) introuvable.")
    if not rows and not errors:
        errors.append("Aucune ligne de membre détectée.")

    return rows, errors
