"""Ce qu'un payeur doit encore.

Une créance vit note de débit par note de débit : `montant_total` moins
`montant_paye`. Personne n'en fait jamais la somme par personne, si bien qu'un
client avec trois règlements partiels apparaît trois fois et que sa dette réelle
n'est affichée nulle part.

La règle tient en une définition, et elle est ici plutôt que recopiée dans
chaque écran qui l'affiche. Deux écrans qui compteraient différemment
donneraient deux dettes pour le même client, et c'est le genre d'écart qui
décrédibilise un chiffre bien plus sûrement qu'une absence de chiffre.

Les montants sont directement sommables : `montant_total` est toujours exprimé
en USD — pour un encaissement en CDF, il vaut `montant_percu / taux_change` à
l'écriture. C'est `montant_percu` qui porte la devise de perception.
"""

from __future__ import annotations

from sqlalchemy import and_, case, func

from app.models.encaissement import Encaissement

# En-deçà d'un centime, une note de débit est soldée : la différence relève de
# l'arrondi, pas de la créance. Même seuil que la relance de solde.
RESTE_NEGLIGEABLE = 0.009


def montant_du():
    """Le reste à payer d'une note, sans condition."""
    return Encaissement.montant_total - Encaissement.montant_paye


def est_exigible():
    """Les notes qui constituent réellement une dette.

    Une proforma est un devis : rien n'est dû tant qu'elle n'est pas convertie,
    et la faire entrer dans le total gonflerait une créance que personne ne
    réclame.

    C'est le montant qui fait foi, pas `statut_paiement` : ce dernier est dérivé
    à l'écriture, une reprise de données peut l'avoir laissé en arrière, jamais
    les deux colonnes de montant.
    """
    return and_(
        Encaissement.est_proforma.is_(False),
        Encaissement.is_deleted.is_(False),
        montant_du() > RESTE_NEGLIGEABLE,
    )


def agregats_creance() -> tuple:
    """Le montant dû et le nombre de notes qui le composent.

    Les deux vont ensemble : toute divergence entre le montant annoncé et le
    nombre de notes qui le portent rendrait le signalement incompréhensible —
    « doit 0 $ sur 2 notes » n'apprend rien à personne.
    """
    exigible = est_exigible()
    return (
        func.coalesce(func.sum(case((exigible, montant_du()), else_=0)), 0),
        func.count(case((exigible, Encaissement.id))),
    )
