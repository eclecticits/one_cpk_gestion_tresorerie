from __future__ import annotations

import io
import re
from decimal import Decimal
from typing import Any

import pdfplumber


REQ_PATTERN = re.compile(r"(REQ[-A-Z0-9/]+)")
MONTANT_PATTERN = re.compile(r"(\d+(?:[.,]\d{2})?)\s*\$")
RUBRIQUE_PATTERN = re.compile(r"(\d+(?:\.\d+)*)\s*[-:]\s*([A-ZÉÈÊËÀÂÎÏÔÛÇ' ]+)")

STATUT_MAP = {
    "REJETEE": "REJETEE",
    "REJETÉE": "REJETEE",
    "PAYEE": "PAYEE",
    "PAYÉE": "PAYEE",
    "AUTORISEE": "AUTORISEE",
    "AUTORISÉE": "AUTORISEE",
    "APPROUVEE": "APPROUVEE",
    "APPROUVÉE": "APPROUVEE",
    "VALIDEE": "VALIDEE",
    "VALIDÉE": "VALIDEE",
}

REPLACEMENTS = {
    "INVESTISSE MENT": "INVESTISSEMENT",
    "FONCTIO NNEMENT": "FONCTIONNEMENT",
    "COTISAT IONS": "COTISATIONS",
    "DEPENSES D' INVESTISSE MENT": "DEPENSES D' INVESTISSEMENT",
}


def _normalize_text(text: str) -> str:
    normalized = text.replace("\u00a0", " ")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    for src, dest in REPLACEMENTS.items():
        normalized = normalized.replace(src, dest)
    return normalized


def _parse_amount(value: str | None) -> Decimal | None:
    if not value:
        return None
    cleaned = value.replace(" ", "").replace(",", ".")
    try:
        return Decimal(cleaned)
    except Exception:
        return None


def extract_lines(pdf_bytes: bytes) -> list[str]:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        lines: list[str] = []
        for page in pdf.pages:
            text = page.extract_text() or ""
            text = _normalize_text(text)
            for line in text.splitlines():
                stripped = line.strip()
                if stripped:
                    lines.append(stripped)
        return lines


def parse_requisition_pdf(pdf_bytes: bytes) -> dict[str, Any]:
    lines = extract_lines(pdf_bytes)
    items: list[dict[str, Any]] = []

    for line in lines:
        upper = line.upper()
        req_match = REQ_PATTERN.search(upper)
        if not req_match:
            continue

        numero = req_match.group(1).replace(" ", "")
        montant_matches = MONTANT_PATTERN.findall(line)
        montant = _parse_amount(montant_matches[-1]) if montant_matches else None

        statut = None
        for key, value in STATUT_MAP.items():
            if key in upper:
                statut = value
                break

        rubrique = None
        rub_match = RUBRIQUE_PATTERN.search(upper)
        if rub_match:
            code = rub_match.group(1).strip()
            libelle = rub_match.group(2).strip().title()
            rubrique = f"{code} - {libelle}"

        objet = line
        objet = objet.replace(numero, "").strip()
        if montant_matches:
            objet = objet.replace(montant_matches[-1], "").replace("$", "").strip()
        if statut:
            objet = objet.replace(statut, "").strip()

        items.append(
            {
                "numero_requisition": numero,
                "montant": montant,
                "statut": statut,
                "rubrique": rubrique,
                "objet": objet[:180] if objet else None,
                "raw_line": line,
            }
        )

    return {
        "items": items,
        "raw_text_excerpt": "\n".join(lines[:40]),
        "warnings": [] if items else ["Aucune ligne de réquisition détectée dans ce PDF."],
    }
