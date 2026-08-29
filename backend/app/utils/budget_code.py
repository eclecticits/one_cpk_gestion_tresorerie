from __future__ import annotations

import re


_ROMAN_VALUES = {
    "I": 1,
    "V": 5,
    "X": 10,
    "L": 50,
    "C": 100,
    "D": 500,
    "M": 1000,
}


def normaliser_code_budget(value: str | None) -> str:
    if not value:
        return ""
    code = re.sub(r"\s+", "", value.strip())
    return re.sub(r"\.+", ".", code).strip(".")


def _roman_to_int(value: str) -> int | None:
    if not value:
        return None
    total = 0
    previous = 0
    for char in reversed(value.upper()):
        current = _ROMAN_VALUES.get(char)
        if current is None:
            return None
        if current < previous:
            total -= current
        else:
            total += current
            previous = current
    return total


def cle_tri_code_budget(value: str | None) -> tuple:
    """Ordre métier d'un code budgétaire segmenté.

    `II.2.13.4` ne doit pas être trié comme du texte brut : le segment numérique
    `13` vient après `2`, donc `II.2.2` doit passer avant `II.2.13.4`.
    """
    code = normaliser_code_budget(value)
    if not code:
        return ()

    key: list[tuple[int, int | str]] = []
    for segment in code.split("."):
        if segment.isdigit():
            key.append((0, int(segment)))
            continue
        roman = _roman_to_int(segment)
        if roman is not None:
            key.append((1, roman))
            continue
        key.append((2, segment.lower()))
    return tuple(key)
