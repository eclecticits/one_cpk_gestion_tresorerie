from __future__ import annotations

from decimal import Decimal
from typing import Iterable


def calculer_journal_avec_solde(mouvements: Iterable[dict], solde_initial: Decimal) -> list[dict]:
    journal_calcule: list[dict] = []
    solde_courant = Decimal(solde_initial or 0)

    for m in mouvements:
        entree = Decimal(m.get("entree") or 0)
        sortie = Decimal(m.get("sortie") or 0)
        solde_courant = solde_courant + entree - sortie
        line = dict(m)
        line["solde"] = solde_courant
        journal_calcule.append(line)

    return journal_calcule
