"""Horodatage des opérations financières.

Une opération de caisse tire sa valeur probante de sa chronologie : si
n'importe quel utilisateur peut choisir la date et l'heure d'un encaissement
ou d'une sortie de fonds, la caisse peut être « rattrapée » après coup et
l'ordre des écritures ne prouve plus rien.

L'heure de référence est donc celle du serveur. Seul le super administrateur
peut antidater librement — pour régulariser une saisie oubliée — et cette
exception est concentrée ici plutôt que réécrite à chaque point d'entrée.

Une seconde exception, bornée : le caissier, l'administrateur et le rapporteur
antidatent un encaissement sur BANQUE jusqu'à un mois en arrière. Un versement
bancaire est souvent connu après coup (relevé, avis de crédit) et doit porter
la date où la banque l'a reçu. La caisse, elle, reste au jour : son solde se
compte au guichet.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import HTTPException, status


def _role(user: object) -> str:
    return (getattr(user, "role", "") or "").lower().replace("-", "_")


def est_super_admin(user: object) -> bool:
    return _role(user) == "super_admin"


#: Profils qui saisissent des encaissements et peuvent dater un versement
#: bancaire du jour où la banque l'a reçu.
ROLES_ANTIDATAGE_BANQUE = frozenset({"caissier", "admin", "rapporteur"})


def peut_antidater_banque(user: object) -> bool:
    return _role(user) in ROLES_ANTIDATAGE_BANQUE


def un_mois_avant(jour: date) -> date:
    """Même jour du mois précédent, ramené au dernier jour si ce mois est plus court.

    Le 31 mars donne le 28 (ou 29) février ; le 3 novembre, le 3 octobre.
    """
    annee, mois = (jour.year, jour.month - 1) if jour.month > 1 else (jour.year - 1, 12)
    dernier_jour = (date(annee + (mois == 12), mois % 12 + 1, 1) - date(annee, mois, 1)).days
    return date(annee, mois, min(jour.day, dernier_jour))


def resoudre_date_operation(
    valeur: datetime | None,
    *,
    user: object,
    champ: str,
    canal: str | None = None,
) -> datetime:
    """Date à enregistrer pour une opération financière.

    Super administrateur : la date fournie est retenue telle quelle, y compris
    dans le passé. Caissier, administrateur ou rapporteur, opération sur
    BANQUE : une date passée est retenue si elle n'a pas plus d'un mois. Tout
    autre cas : l'heure du serveur s'impose.

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

    jour = valeur.astimezone(timezone.utc).date()
    aujourd_hui = maintenant.date()

    if (
        peut_antidater_banque(user)
        and (canal or "").upper() == "BANQUE"
        and jour != aujourd_hui
    ):
        limite = un_mois_avant(aujourd_hui)
        if jour > aujourd_hui or jour < limite:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Un encaissement sur banque peut être daté au plus tôt du "
                    f"{limite.strftime('%d/%m/%Y')}, et jamais après aujourd'hui ({champ})."
                ),
            )
        return valeur

    if jour != aujourd_hui:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Seul un super administrateur peut enregistrer une opération à une "
                f"autre date que celle du jour ({champ}). L'opération sera horodatée "
                f"par le serveur."
            ),
        )

    return maintenant
