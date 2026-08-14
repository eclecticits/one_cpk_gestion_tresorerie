"""Horodatage des opérations financières.

Une opération de caisse tire sa valeur probante de sa chronologie : si
n'importe quel utilisateur peut choisir la date et l'heure d'un encaissement
ou d'une sortie de fonds, la caisse peut être « rattrapée » après coup et
l'ordre des écritures ne prouve plus rien.

L'heure de référence est donc celle du serveur. Seul le super administrateur
peut antidater — pour régulariser une saisie oubliée — et cette exception est
concentrée ici plutôt que réécrite à chaque point d'entrée.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status


def est_super_admin(user: object) -> bool:
    return (getattr(user, "role", "") or "").lower().replace("-", "_") == "super_admin"


def resoudre_date_operation(
    valeur: datetime | None,
    *,
    user: object,
    champ: str,
) -> datetime:
    """Date à enregistrer pour une opération financière.

    Super administrateur : la date fournie est retenue telle quelle, y compris
    dans le passé. Tout autre profil : l'heure du serveur s'impose.

    Une date d'un autre jour envoyée par un profil non habilité est refusée
    explicitement plutôt qu'écrasée en silence — l'utilisateur croirait sinon
    avoir enregistré une opération à la date qu'il a saisie. Un écart à
    l'intérieur de la même journée est normalisé sans bruit : il vient de
    l'horloge du poste client, pas d'une intention d'antidater.
    """
    maintenant = datetime.now(timezone.utc)

    if valeur is None:
        return maintenant

    if valeur.tzinfo is None:
        valeur = valeur.replace(tzinfo=timezone.utc)

    if est_super_admin(user):
        return valeur

    if valeur.astimezone(timezone.utc).date() != maintenant.date():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Seul un super administrateur peut enregistrer une opération à une "
                f"autre date que celle du jour ({champ}). L'opération sera horodatée "
                f"par le serveur."
            ),
        )

    return maintenant
