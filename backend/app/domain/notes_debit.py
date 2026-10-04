"""Vocabulaire métier des lignes de créance d'une note de débit.

Une note reste un :class:`Encaissement` et ses lignes restent des
``EncaissementArticle``.  Ce module centralise seulement la sémantique qui
manquait aux articles ; l'import, l'API et les documents utilisent ainsi les
mêmes codes et les mêmes libellés.
"""

from __future__ import annotations

import re
import unicodedata


COTISATION_ANNUELLE = "COTISATION_ANNUELLE"
ARRIERE_COTISATION = "ARRIERE_COTISATION"
PENALITE_APO = "PENALITE_APO"
ARRIERE_PENALITE_APO = "ARRIERE_PENALITE_APO"
AUTRE_PENALITE = "AUTRE_PENALITE"
ARRIERE_AUTRE_PENALITE = "ARRIERE_AUTRE_PENALITE"
AUTRE_CREANCE = "AUTRE_CREANCE"
LEGACY = "LEGACY"

CATEGORIES_IMPORTABLES = {
    COTISATION_ANNUELLE,
    ARRIERE_COTISATION,
    PENALITE_APO,
    ARRIERE_PENALITE_APO,
    AUTRE_PENALITE,
    ARRIERE_AUTRE_PENALITE,
    AUTRE_CREANCE,
}
CATEGORIES = CATEGORIES_IMPORTABLES | {LEGACY}
CATEGORIES_ARRIERE = {
    ARRIERE_COTISATION,
    ARRIERE_PENALITE_APO,
    ARRIERE_AUTRE_PENALITE,
}

LIBELLES = {
    COTISATION_ANNUELLE: "Cotisation annuelle",
    ARRIERE_COTISATION: "Arriéré de cotisation",
    PENALITE_APO: "Pénalité APO",
    ARRIERE_PENALITE_APO: "Arriéré de pénalité APO",
    AUTRE_PENALITE: "Autre pénalité",
    ARRIERE_AUTRE_PENALITE: "Arriéré d'autre pénalité",
    AUTRE_CREANCE: "Autre créance",
    LEGACY: "Créance historique non ventilée",
}


def _cle(valeur: str) -> str:
    texte = "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", valeur or "")
        if not unicodedata.combining(caractere)
    ).upper()
    return re.sub(r"[^A-Z0-9]+", "_", texte).strip("_")


_ALIASES = {
    "COTISATION": COTISATION_ANNUELLE,
    "COTISATION_ANNUELLE": COTISATION_ANNUELLE,
    "ARRIERE_COTISATION": ARRIERE_COTISATION,
    "ARRIERES_COTISATIONS": ARRIERE_COTISATION,
    "PENALITE_APO": PENALITE_APO,
    "ARRIERE_PENALITE_APO": ARRIERE_PENALITE_APO,
    "ARRIERES_PENALITE_APO": ARRIERE_PENALITE_APO,
    "AUTRE_PENALITE": AUTRE_PENALITE,
    "ARRIERE_AUTRE_PENALITE": ARRIERE_AUTRE_PENALITE,
    "ARRIERES_AUTRES_PENALITES": ARRIERE_AUTRE_PENALITE,
    "AUTRE_CREANCE": AUTRE_CREANCE,
    "AUTRES_CREANCES": AUTRE_CREANCE,
}


def normaliser_categorie(valeur: str | None) -> str | None:
    """Rend le code canonique d'une catégorie importable, sinon ``None``."""

    if valeur is None:
        return None
    cle = _cle(str(valeur))
    return cle if cle in CATEGORIES else _ALIASES.get(cle)


def libelle_categorie(categorie: str | None, repli: str | None = None) -> str:
    return LIBELLES.get(categorie or "", repli or categorie or "Créance")
