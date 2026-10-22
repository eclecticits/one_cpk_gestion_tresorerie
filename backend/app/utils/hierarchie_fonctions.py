"""Ordre protocolaire des fonctions d'une unité : le Président, puis le bureau
(Vice-président, Rapporteur, Rapporteur adjoint, Trésorier, Trésorier adjoint),
puis les autres membres, les assistants en dernier.

On classe sur le libellé imprimé, pas sur le rang réglé dans l'unité : ce rang
est éditable et, au Conseil, « Membre du conseil » portait le même que le
Président, si bien que l'ordre alphabétique faisait passer les membres devant.
La règle est dupliquée côté interface dans `utils/serviceMemberFunctions.ts`.

Un participant dont l'ordre a été fixé à la saisie (`ordre`) suit cet ordre :
le classement par fonction ne reconnaît pas tous les libellés et ne sert plus
qu'aux remboursements antérieurs, ou aux lignes sans ordre."""

from __future__ import annotations

import unicodedata
from typing import Iterable, Protocol, TypeVar


class _Participant(Protocol):
    nom: str
    titre_fonction: str
    type_participant: str
    ordre: int | None


P = TypeVar("P", bound=_Participant)

RANG_AUTRE_MEMBRE = 7
RANG_ASSISTANT = 9


def _cle(libelle: str | None) -> str:
    ascii_label = unicodedata.normalize("NFKD", libelle or "").encode("ascii", "ignore").decode("ascii")
    return "".join(ch for ch in ascii_label.lower() if ch.isalnum())


def rang_fonction(libelle: str | None) -> int:
    cle = _cle(libelle)
    if "assistant" in cle:
        return RANG_ASSISTANT
    adjoint = "adjoint" in cle
    if "vicepresident" in cle:
        return 2
    if "president" in cle:
        return 1
    if "rapporteu" in cle:
        return 4 if adjoint else 3
    if "tresori" in cle:
        return 6 if adjoint else 5
    return RANG_AUTRE_MEMBRE


def trier_participants(participants: Iterable[P]) -> list[P]:
    return sorted(
        participants,
        key=lambda p: (
            p.type_participant == "assistant",
            getattr(p, "ordre", None) is None,
            getattr(p, "ordre", None) or 0,
            rang_fonction(p.titre_fonction),
            _cle(p.nom),
        ),
    )
