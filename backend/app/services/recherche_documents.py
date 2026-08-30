"""Retrouver un document par son numéro, tel qu'un humain le tape.

Un numéro de note de débit s'écrit `ND-2026-000022`. Il est lu sur un papier,
recopié d'un courriel, collé depuis un tableur — et il arrive donc au serveur
avec une espace en trop, sans ses tirets, ou avec des espaces à leur place.

Une comparaison littérale répond alors « aucun résultat » à quelqu'un qui a
sous les yeux le document qu'il cherche. Ce n'est pas une recherche
infructueuse, c'est une recherche cassée : l'utilisateur conclut que la note
n'existe pas.

La règle retenue : **on compare ce qui porte l'information**, c'est-à-dire les
lettres et les chiffres. La ponctuation de présentation — tirets, espaces,
points — est retirée des deux côtés avant comparaison, et la casse est ignorée.
`nd 2026 000022`, `ND2026000022` et `  ND-2026-000022  ` désignent donc la même
note que `ND-2026-000022`.

Ce que la règle ne fait PAS : deviner. Elle ne complète pas un préfixe absent
et ne corrige pas un chiffre. Une sous-chaîne reste une sous-chaîne — taper
`000022` rend toutes les notes qui la contiennent, comme aujourd'hui.
"""

from __future__ import annotations

import re

from sqlalchemy import ColumnElement, func, or_

#: Tout ce qui n'est ni lettre ni chiffre est de la présentation.
_PONCTUATION = re.compile(r"[^0-9A-Za-z]+")
#: Sa traduction en SQL : mêmes classes de caractères, même verdict.
_PONCTUATION_SQL = "[^0-9A-Za-z]+"


def normaliser_numero(saisie: str | None) -> str:
    """Ne garde que ce qui identifie : lettres et chiffres, en majuscules."""
    if not saisie:
        return ""
    return _PONCTUATION.sub("", saisie).upper()


def _colonne_normalisee(colonne: ColumnElement) -> ColumnElement:
    return func.upper(func.regexp_replace(colonne, _PONCTUATION_SQL, "", "g"))


def condition_numero(saisie: str | None, *colonnes: ColumnElement) -> ColumnElement | None:
    """Condition SQL cherchant `saisie` dans l'une des colonnes, normalisées.

    Rend `None` quand la saisie ne porte aucun caractère significatif — une
    suite d'espaces ou de tirets. Filtrer là-dessus viderait l'écran sur une
    frappe accidentelle ; ne rien filtrer rend l'écran intact, ce que
    l'utilisateur attend d'un champ qu'il vient d'effacer.

    L'index sur ces colonnes n'est de toute façon pas utilisable : la recherche
    est une sous-chaîne, donc `%…%`, donc un parcours. La normalisation ne coûte
    rien de plus qu'il n'était déjà payé.
    """
    motif = normaliser_numero(saisie)
    if not motif:
        return None
    recherche = f"%{motif}%"
    return or_(*(_colonne_normalisee(colonne).like(recherche) for colonne in colonnes))
