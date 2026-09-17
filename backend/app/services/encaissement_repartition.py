"""Répartition d'un versement entre les postes des articles d'un encaissement.

Un encaissement se règle parfois en plusieurs versements, et ses articles ne
tombent pas forcément sur le même poste. Chaque versement doit donc se répartir
entre les postes dans la proportion des articles — un acompte de la moitié
apporte la moitié à chacun, et non la totalité au premier.

La règle d'arrondi est celle des sorties multi-postes (`sorties_fonds.py`) :
chaque part est arrondie au centime, puis l'écart de centime revient à la plus
grosse part. La somme des parts vaut exactement le versement, toujours — sans
quoi le budget encaisserait un centime de plus ou de moins que la trésorerie.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

CENTIME = Decimal("0.01")


def repartir(
    lignes: Iterable[tuple[int | None, Decimal]],
    montant: Decimal,
    *,
    poste_par_defaut: int | None = None,
) -> list[tuple[int, Decimal]]:
    """Parts `(poste, montant)` d'un versement, au prorata des lignes.

    `lignes` : les articles, `(poste, montant de l'article)`. Une ligne sans
    poste suit `poste_par_defaut` — le poste de l'encaissement, qui reste la
    règle quand la saisie n'a rien précisé. Une ligne sans poste ni repli
    n'impute rien et n'entre pas dans la proportion.
    """
    montant = Decimal(montant or 0)
    if montant <= 0:
        return []

    cumul: dict[int, Decimal] = {}
    for poste, part in lignes:
        cible = poste if poste is not None else poste_par_defaut
        if cible is None:
            continue
        valeur = Decimal(part or 0)
        if valeur <= 0:
            continue
        cumul[cible] = cumul.get(cible, Decimal("0")) + valeur

    if not cumul:
        # Aucun article imputable : tout revient au poste de l'encaissement,
        # c'est-à-dire au comportement d'avant les postes par article.
        return [(poste_par_defaut, montant)] if poste_par_defaut is not None else []

    if len(cumul) == 1:
        # Un seul poste : pas de prorata, donc pas d'arrondi — le versement lui
        # revient en entier, au centime près de ce que la trésorerie a reçu.
        return [(next(iter(cumul)), montant)]

    total = sum(cumul.values(), Decimal("0"))
    parts = [
        (poste, (montant * valeur / total).quantize(CENTIME))
        for poste, valeur in sorted(cumul.items())
    ]
    ecart = montant - sum(part for _, part in parts)
    if ecart != 0:
        plus_grosse = max(range(len(parts)), key=lambda i: parts[i][1])
        parts[plus_grosse] = (parts[plus_grosse][0], parts[plus_grosse][1] + ecart)
    return [(poste, part) for poste, part in parts if part > 0]
