"""Normalisation des numéros de téléphone au format international.

Point unique de vérité. Le dépôt portait jusqu'ici trois implémentations
divergentes — `services/whatsapp.py`, `api/v1/endpoints/admin.py`, et
`normalizePhoneList` côté TypeScript — dont aucune n'ajoutait l'indicatif pays :
un numéro saisi `0810123456` partait tel quel et échouait en silence chez le
fournisseur. Les deux implémentations Python sont remplacées par celle-ci.
"""

from __future__ import annotations

import re

# RDC. Surchargable par organisation si le produit s'ouvre à d'autres pays.
DEFAULT_COUNTRY_CODE = "243"

# Longueur d'un numéro national congolais sans le zéro de tête (9 chiffres),
# utilisée pour distinguer « 0810123456 » (national) de « 243810123456 ».
_DRC_NATIONAL_LENGTH = 9


def normalize_phone(raw: str | None, country_code: str = DEFAULT_COUNTRY_CODE) -> str | None:
    """Renvoie le numéro au format E.164 sans le « + », ou None s'il est inexploitable.

    Le fournisseur Evolution attend les chiffres seuls ; Meta et Twilio acceptent
    les deux formes. On stocke donc la forme canonique sans « + », et chaque
    provider la préfixe s'il en a besoin.

    >>> normalize_phone("0810 123 456")
    '243810123456'
    >>> normalize_phone("+243810123456")
    '243810123456'
    >>> normalize_phone("810123456")
    '243810123456'
    >>> normalize_phone("12") is None
    True
    """
    if not raw:
        return None

    value = str(raw).strip()
    if not value:
        return None

    had_plus = value.startswith("+") or value.startswith("00")
    digits = re.sub(r"\D", "", value)
    if not digits:
        return None

    # « 00243… » est la forme internationale composée depuis un poste fixe.
    if digits.startswith("00"):
        digits = digits[2:]
        had_plus = True

    cc = re.sub(r"\D", "", country_code) or DEFAULT_COUNTRY_CODE

    if had_plus:
        # Déjà international : on ne touche pas à l'indicatif, quel qu'il soit.
        normalized = digits
    elif digits.startswith("0"):
        # Forme nationale : le zéro de tête cède la place à l'indicatif.
        normalized = cc + digits.lstrip("0")
    elif digits.startswith(cc):
        normalized = digits
    elif len(digits) <= _DRC_NATIONAL_LENGTH:
        # Numéro national saisi sans son zéro.
        normalized = cc + digits
    else:
        # Assez long pour porter déjà un indicatif étranger : on respecte la saisie.
        normalized = digits

    # Garde-fou : un numéro international plausible fait entre 8 et 15 chiffres
    # (E.164 plafonne à 15). En dessous, c'est une saisie tronquée.
    if not 8 <= len(normalized) <= 15:
        return None

    return normalized


def normalize_phone_list(raw: str | None, country_code: str = DEFAULT_COUNTRY_CODE) -> list[str]:
    """Découpe une liste libre (virgules, points-virgules, retours ligne) et normalise.

    Conserve l'ordre de saisie et supprime les doublons après normalisation :
    « 0810123456 » et « +243810123456 » ne doivent produire qu'un seul envoi.
    """
    if not raw:
        return []

    seen: set[str] = set()
    numbers: list[str] = []
    for part in re.split(r"[,\n;]+", str(raw)):
        normalized = normalize_phone(part, country_code)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        numbers.append(normalized)
    return numbers


def format_phone_display(normalized: str | None) -> str:
    """Forme lisible pour l'interface et les journaux : « +243 810 123 456 »."""
    if not normalized:
        return ""
    digits = re.sub(r"\D", "", normalized)
    if not digits:
        return ""
    if digits.startswith(DEFAULT_COUNTRY_CODE) and len(digits) == len(DEFAULT_COUNTRY_CODE) + _DRC_NATIONAL_LENGTH:
        rest = digits[len(DEFAULT_COUNTRY_CODE):]
        return f"+{DEFAULT_COUNTRY_CODE} {rest[0:3]} {rest[3:6]} {rest[6:]}"
    return f"+{digits}"


def mask_phone(normalized: str | None) -> str:
    """Masque un numéro pour l'affichage à un utilisateur non autorisé : « +243 ••• ••• 456 »."""
    if not normalized:
        return ""
    digits = re.sub(r"\D", "", normalized)
    if len(digits) < 4:
        return "•" * len(digits)
    return f"+{digits[:3]} ••• ••• {digits[-3:]}"
