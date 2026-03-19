from __future__ import annotations

import io
import unicodedata
from typing import Any

import pandas as pd


def _normalize_col(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return normalized.strip().lower()


def _parse_amount(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).strip()
    if not raw:
        return None
    raw = raw.replace(" ", "").replace("\u00a0", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


class ExcelParser:
    @staticmethod
    async def parse_bank_statement(file_content: bytes, filename: str | None = None) -> list[dict[str, Any]]:
        df = None
        if filename and filename.lower().endswith(".csv"):
            df = pd.read_csv(io.BytesIO(file_content))
        else:
            try:
                df = pd.read_excel(io.BytesIO(file_content))
            except Exception:
                df = pd.read_csv(io.BytesIO(file_content))

        df.columns = [_normalize_col(str(c)) for c in df.columns]

        label_keys = {"libelle", "libelle", "description", "details", "detail", "motif", "reference"}
        amount_keys = {"montant", "debit", "credit", "valeur", "amount"}
        date_keys = {"date", "date operation", "date_operation", "date valeur", "date_valeur"}

        transactions: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            row_dict = row.to_dict()
            label = None
            for key in label_keys:
                if key in row_dict and row_dict[key] not in (None, ""):
                    label = row_dict[key]
                    break

            amount = None
            for key in amount_keys:
                if key in row_dict and row_dict[key] not in (None, ""):
                    amount = _parse_amount(row_dict[key])
                    if amount is not None:
                        break

            date_value = None
            for key in date_keys:
                if key in row_dict and row_dict[key] not in (None, ""):
                    date_value = row_dict[key]
                    break

            if label and amount is not None:
                transactions.append(
                    {
                        "date": str(date_value) if date_value is not None else None,
                        "label": str(label),
                        "amount": amount,
                    }
                )

        return transactions
