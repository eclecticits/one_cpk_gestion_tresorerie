"""Module d'arrivée après la connexion.

Une personne peut avoir accès à plusieurs modules (Trésorerie et Tableau, par
exemple). L'organisation fixe l'ordre dans lequel on les essaie ; un
utilisateur peut avoir son propre module d'accueil, qui passe avant cet ordre.
Le premier module dont il a l'accès l'emporte : le calcul se fait côté
interface, qui connaît les permissions de la session.
"""

from __future__ import annotations

#: Ordre par défaut, celui qui s'applique tant que l'organisation n'en a pas
#: fixé d'autre. Les clés sont celles de `modules_config`.
MODULES_ORDRE_DEFAUT: tuple[str, ...] = ("tresorerie", "tableau", "comptabilite", "rh", "secretariat")


def normaliser_priorite(valeur: list[str] | None) -> list[str]:
    """Ordre complet, sans doublon ni clé inconnue.

    Un module oublié dans la liste reçue est ajouté à la fin, dans l'ordre par
    défaut : l'ordre enregistré couvre ainsi toujours tous les modules, y
    compris ceux qui apparaîtront plus tard.
    """
    ordre: list[str] = []
    for cle in valeur or []:
        cle = (cle or "").strip().lower()
        if cle in MODULES_ORDRE_DEFAUT and cle not in ordre:
            ordre.append(cle)
    ordre.extend(cle for cle in MODULES_ORDRE_DEFAUT if cle not in ordre)
    return ordre


def normaliser_module_accueil(valeur: str | None) -> str | None:
    """Clé connue, ou None (« selon l'ordre de l'organisation »)."""
    cle = (valeur or "").strip().lower()
    if not cle:
        return None
    if cle not in MODULES_ORDRE_DEFAUT:
        raise ValueError(f"Module inconnu : {valeur}")
    return cle
