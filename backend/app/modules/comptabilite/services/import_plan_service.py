"""Import du plan comptable depuis un fichier Excel.

Le plan de démarrage intégré n'est qu'un socle : chaque organisation doit le
compléter avec ses propres comptes. Cet import le fait en masse, avec trois
garde-fous :

- **rien n'est supprimé** : un compte absent du fichier reste en place (aucune
  suppression physique dans le module) ;
- **tout ou rien** : une seule ligne en erreur et aucun compte n'est écrit,
  pour ne jamais laisser un plan à moitié importé ;
- **l'historique est protégé** : la nature et le sens d'un compte déjà
  mouvementé ne changent pas (les soldes passés changeraient de côté dans les
  états), et un compte utilisé par un mapping ne peut être ni désactivé ni
  rendu collectif (le moteur de génération le refuserait ensuite).

Seuls le numéro et le libellé sont obligatoires. La nature, le sens et le
compte parent sont déduits du numéro quand le fichier ne les donne pas, selon
la numérotation OHADA — et signalés comme tels, pour relecture.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.comptabilite.models import (
    ComptaCompte,
    ComptaLigneEcriture,
    ComptaMappingCompteBancaire,
    ComptaMappingPosteBudgetaire,
    ComptaMappingRubrique,
    ComptaReferentiel,
    ComptaSociete,
    utcnow,
)
from app.modules.comptabilite.schemas.plan_import import ImportPlanOut, LignePlanIn, LignePlanOut

NATURES = ("ACTIF", "PASSIF", "CHARGE", "PRODUIT", "ENGAGEMENT")

_ALIAS_NATURE = {
    "actif": "ACTIF",
    "passif": "PASSIF",
    "charge": "CHARGE",
    "charges": "CHARGE",
    "produit": "PRODUIT",
    "produits": "PRODUIT",
    "engagement": "ENGAGEMENT",
    "engagements": "ENGAGEMENT",
}
_ALIAS_SENS = {
    "debit": "DEBIT",
    "d": "DEBIT",
    "debiteur": "DEBIT",
    "credit": "CREDIT",
    "c": "CREDIT",
    "crediteur": "CREDIT",
}
_OUI = {"oui", "o", "yes", "y", "vrai", "true", "1", "x"}
_NON = {"non", "n", "no", "faux", "false", "0"}

_NUMERO_VALIDE = re.compile(r"^[1-9][0-9A-Z]*$")
_LONGUEUR_NUMERO = 30
_LONGUEUR_LIBELLE = 255


class ReferentielIntrouvable(Exception):
    """La comptabilité n'est pas activée : il n'y a pas de plan où importer."""


def _texte(value: str | None) -> str:
    """Minuscules, sans accents ni espaces superflus, pour comparer des saisies libres."""
    brut = (value or "").replace(" ", " ").strip().lower()
    return "".join(c for c in unicodedata.normalize("NFD", brut) if unicodedata.category(c) != "Mn")


def normaliser_numero(value: str | None) -> str:
    """« 601 100 », « 601.100 » et « 601-100 » désignent le même compte 601100."""
    return re.sub(r"[\s.\-]", "", (value or "").replace(" ", "")).upper()


def deduire_nature_sens(numero: str) -> tuple[str, str]:
    """Nature et sens normal d'un compte d'après sa numérotation OHADA.

    Les comptes correcteurs (amortissements 28, dépréciations 29/39/49/59)
    restent à l'actif mais fonctionnent au crédit ; en classe 8, les numéros
    impairs sont des charges HAO et les pairs des produits HAO.
    """
    classe, prefixe = numero[0], numero[:2]
    if classe == "1":
        return "PASSIF", "CREDIT"
    if classe in "23":
        return ("ACTIF", "CREDIT") if prefixe in {"28", "29", "39"} else ("ACTIF", "DEBIT")
    if classe == "4":
        if prefixe in {"40", "42", "43", "44"}:
            return "PASSIF", "CREDIT"
        return ("ACTIF", "CREDIT") if prefixe == "49" else ("ACTIF", "DEBIT")
    if classe == "5":
        if prefixe == "56":
            return "PASSIF", "CREDIT"
        return ("ACTIF", "CREDIT") if prefixe == "59" else ("ACTIF", "DEBIT")
    if classe == "6":
        return "CHARGE", "DEBIT"
    if classe == "7":
        return "PRODUIT", "CREDIT"
    if classe == "8":
        if len(numero) > 1 and numero[1].isdigit() and int(numero[1]) % 2 == 0:
            return "PRODUIT", "CREDIT"
        return "CHARGE", "DEBIT"
    return "ENGAGEMENT", "DEBIT"


def _sens_par_defaut(numero: str, nature: str) -> str:
    nature_deduite, sens_deduit = deduire_nature_sens(numero)
    if nature_deduite == nature:
        return sens_deduit
    return "CREDIT" if nature in {"PASSIF", "PRODUIT"} else "DEBIT"


def _booleen(value: str | None) -> tuple[bool | None, bool]:
    """(valeur, reconnue). Une cellule vide vaut « non renseigné », pas « non »."""
    texte = _texte(value)
    if not texte:
        return None, True
    if texte in _OUI:
        return True, True
    if texte in _NON:
        return False, True
    return None, False


@dataclass
class _Ligne:
    source: LignePlanIn
    numero: str = ""
    libelle: str = ""
    nature: str | None = None
    sens: str | None = None
    parent_explicite: str | None = None
    collectif: bool | None = None
    auxiliaire: bool | None = None
    actif: bool | None = None
    erreurs: list[str] = field(default_factory=list)


def _lire_ligne(source: LignePlanIn) -> _Ligne:
    lue = _Ligne(source=source)
    lue.numero = normaliser_numero(source.numero)
    lue.libelle = " ".join((source.libelle or "").split())

    if not lue.numero:
        lue.erreurs.append("Numéro de compte manquant.")
    elif len(lue.numero) > _LONGUEUR_NUMERO:
        lue.erreurs.append(f"Numéro trop long ({len(lue.numero)} caractères, {_LONGUEUR_NUMERO} au plus).")
    elif not _NUMERO_VALIDE.match(lue.numero):
        lue.erreurs.append("Numéro invalide : il doit commencer par un chiffre de 1 à 9 (la classe).")

    if not lue.libelle:
        lue.erreurs.append("Libellé manquant.")
    elif len(lue.libelle) > _LONGUEUR_LIBELLE:
        lue.erreurs.append(f"Libellé trop long ({_LONGUEUR_LIBELLE} caractères au plus).")

    if _texte(source.nature):
        lue.nature = _ALIAS_NATURE.get(_texte(source.nature))
        if lue.nature is None:
            lue.erreurs.append(
                f"Nature « {source.nature} » inconnue (attendu : Actif, Passif, Charge, Produit ou Engagement)."
            )
    if _texte(source.sens):
        lue.sens = _ALIAS_SENS.get(_texte(source.sens))
        if lue.sens is None:
            lue.erreurs.append(f"Sens « {source.sens} » inconnu (attendu : Débit ou Crédit).")

    parent = normaliser_numero(source.parent)
    lue.parent_explicite = parent or None

    for nom, attribut in (("Collectif", "collectif"), ("Auxiliaire", "auxiliaire"), ("Actif", "actif")):
        valeur, reconnue = _booleen(getattr(source, attribut))
        if not reconnue:
            lue.erreurs.append(f"{nom} : « {getattr(source, attribut)} » n'est ni Oui ni Non.")
        setattr(lue, attribut, valeur)
    if lue.collectif and lue.auxiliaire:
        lue.erreurs.append("Un compte ne peut pas être à la fois collectif et auxiliaire.")
    return lue


def _parent_deduit(numero: str, connus: set[str]) -> str | None:
    """Le plus long préfixe strict du numéro qui existe déjà : 601100 → 601 → 60."""
    for longueur in range(len(numero) - 1, 0, -1):
        if numero[:longueur] in connus:
            return numero[:longueur]
    return None


async def _comptes_proteges(
    db: AsyncSession, organisation_id: int, ids: list[int]
) -> tuple[set[int], set[int]]:
    """(comptes mouvementés, comptes utilisés par un mapping)."""
    if not ids:
        return set(), set()
    mouvementes = set(
        (
            await db.execute(
                select(ComptaLigneEcriture.compte_id)
                .where(
                    ComptaLigneEcriture.organisation_id == organisation_id,
                    ComptaLigneEcriture.compte_id.in_(ids),
                )
                .distinct()
            )
        ).scalars()
    )
    mappes: set[int] = set()
    for modele in (ComptaMappingPosteBudgetaire, ComptaMappingCompteBancaire, ComptaMappingRubrique):
        mappes.update(
            (await db.execute(select(modele.compte_id).where(modele.compte_id.in_(ids)))).scalars()
        )
    mappes.update(
        (
            await db.execute(
                select(ComptaSociete.compte_caisse_defaut_id).where(
                    ComptaSociete.organisation_id == organisation_id,
                    ComptaSociete.compte_caisse_defaut_id.in_(ids),
                )
            )
        ).scalars()
    )
    return mouvementes, mappes


async def importer_plan_comptable(
    db: AsyncSession,
    *,
    organisation_id: int,
    lignes: list[LignePlanIn],
    mode: str,
    simulation: bool,
) -> ImportPlanOut:
    referentiel = (
        await db.execute(
            select(ComptaReferentiel).where(
                ComptaReferentiel.organisation_id == organisation_id,
                ComptaReferentiel.is_default.is_(True),
            )
        )
    ).scalar_one_or_none()
    if referentiel is None:
        raise ReferentielIntrouvable()

    existants_liste = list(
        (
            await db.execute(
                select(ComptaCompte).where(
                    ComptaCompte.organisation_id == organisation_id,
                    ComptaCompte.referentiel_id == referentiel.id,
                )
            )
        ).scalars()
    )
    existants = {c.numero: c for c in existants_liste}
    numero_par_id = {c.id: c.numero for c in existants_liste}
    mouvementes, mappes = await _comptes_proteges(db, organisation_id, list(numero_par_id))

    # ── 1. Lecture et contrôles propres à chaque ligne ──────────────────
    lues: list[_Ligne] = []
    vues: dict[str, int] = {}
    for source in lignes:
        if not (source.numero or "").strip() and not (source.libelle or "").strip():
            continue
        lue = _lire_ligne(source)
        if lue.numero and not lue.erreurs:
            if lue.numero in vues:
                lue.erreurs.append(f"Numéro déjà présent à la ligne {vues[lue.numero]} du fichier.")
            else:
                vues[lue.numero] = source.ligne
        lues.append(lue)

    connus = set(existants) | set(vues)

    # ── 2. Hiérarchie : parent explicite contrôlé, sinon déduit ─────────
    parents: dict[str, str | None] = {
        numero: numero_par_id.get(c.parent_id) if c.parent_id else None for numero, c in existants.items()
    }
    parent_deduit: dict[str, bool] = {}
    for lue in lues:
        if lue.erreurs:
            continue
        existant = existants.get(lue.numero)
        if lue.parent_explicite:
            if lue.parent_explicite == lue.numero:
                lue.erreurs.append("Un compte ne peut pas être son propre parent.")
            elif lue.parent_explicite not in connus:
                lue.erreurs.append(
                    f"Compte parent {lue.parent_explicite} introuvable, ni dans le plan ni dans le fichier."
                )
            else:
                parents[lue.numero] = lue.parent_explicite
        elif existant is None or existant.parent_id is None:
            # Sur un compte existant déjà rattaché, on ne remplace pas un
            # rattachement choisi par une simple déduction.
            deduit = _parent_deduit(lue.numero, connus)
            parents[lue.numero] = deduit
            parent_deduit[lue.numero] = deduit is not None

    for lue in lues:
        if lue.erreurs or not lue.parent_explicite:
            continue
        courant, etapes = parents.get(lue.numero), 0
        while courant and etapes <= len(parents):
            if courant == lue.numero:
                lue.erreurs.append("Rattachement circulaire : ce compte se retrouve parmi ses propres parents.")
                break
            courant, etapes = parents.get(courant), etapes + 1

    # ── 3. Ce que l'import ferait de chaque ligne ───────────────────────
    sorties: list[LignePlanOut] = []
    a_creer: list[_Ligne] = []
    a_modifier: list[tuple[_Ligne, ComptaCompte, dict]] = []

    for lue in lues:
        base = {"ligne": lue.source.ligne, "numero": lue.numero or (lue.source.numero or ""), "libelle": lue.libelle}
        if lue.erreurs:
            sorties.append(LignePlanOut(**base, action="ERREUR", message=" ".join(lue.erreurs)))
            continue

        existant = existants.get(lue.numero)
        parent_numero = parents.get(lue.numero)
        deduits: list[str] = []

        if existant is None:
            nature_deduite, _ = deduire_nature_sens(lue.numero)
            nature = lue.nature or nature_deduite
            sens = lue.sens or _sens_par_defaut(lue.numero, nature)
            if lue.nature is None:
                deduits.append("nature")
            if lue.sens is None:
                deduits.append("sens")
            if parent_deduit.get(lue.numero):
                deduits.append("parent")
            sorties.append(
                LignePlanOut(
                    **base,
                    action="CREER",
                    nature=nature,
                    sens_normal=sens,
                    parent_numero=parent_numero,
                    is_collectif=bool(lue.collectif),
                    is_auxiliaire=bool(lue.auxiliaire),
                    actif=True if lue.actif is None else lue.actif,
                    deduits=deduits,
                )
            )
            lue.nature, lue.sens = nature, sens
            a_creer.append(lue)
            continue

        if mode == "add_only":
            sorties.append(
                LignePlanOut(
                    **base,
                    action="IGNORE",
                    nature=existant.nature,
                    sens_normal=existant.sens_normal,
                    parent_numero=parents.get(lue.numero),
                    message="Compte déjà présent : laissé tel quel.",
                )
            )
            continue

        # Sur un compte existant, seules les colonnes renseignées comptent :
        # une nature déduite n'écrase jamais une nature choisie.
        cibles = {
            "libelle": lue.libelle,
            "nature": lue.nature or existant.nature,
            "sens_normal": lue.sens or existant.sens_normal,
            "parent_numero": parent_numero,
            "is_collectif": existant.is_collectif if lue.collectif is None else lue.collectif,
            "is_auxiliaire": existant.is_auxiliaire if lue.auxiliaire is None else lue.auxiliaire,
            "actif": existant.actif if lue.actif is None else lue.actif,
        }
        actuels = {
            "libelle": existant.libelle,
            "nature": existant.nature,
            "sens_normal": existant.sens_normal,
            "parent_numero": numero_par_id.get(existant.parent_id) if existant.parent_id else None,
            "is_collectif": existant.is_collectif,
            "is_auxiliaire": existant.is_auxiliaire,
            "actif": existant.actif,
        }
        changements = [cle for cle in cibles if cibles[cle] != actuels[cle]]
        if parent_deduit.get(lue.numero) and "parent_numero" in changements:
            deduits.append("parent")

        refus: list[str] = []
        if existant.id in mouvementes and {"nature", "sens_normal"} & set(changements):
            refus.append("Compte déjà mouvementé : sa nature et son sens ne peuvent plus changer.")
        if existant.id in mappes and "actif" in changements and not cibles["actif"]:
            refus.append("Compte utilisé par un mapping : il ne peut pas être désactivé.")
        if existant.id in mappes and "is_collectif" in changements and cibles["is_collectif"]:
            refus.append("Compte utilisé par un mapping : il ne peut pas devenir collectif.")
        if cibles["is_collectif"] and cibles["is_auxiliaire"]:
            refus.append("Un compte ne peut pas être à la fois collectif et auxiliaire.")

        details = {
            "ligne": lue.source.ligne,
            "numero": lue.numero,
            "libelle": lue.libelle,
            "nature": cibles["nature"],
            "sens_normal": cibles["sens_normal"],
            "parent_numero": cibles["parent_numero"],
            "is_collectif": cibles["is_collectif"],
            "is_auxiliaire": cibles["is_auxiliaire"],
            "actif": cibles["actif"],
            "deduits": deduits,
            "changements": changements,
        }
        if refus:
            sorties.append(LignePlanOut(**details | {"action": "ERREUR", "message": " ".join(refus)}))
        elif changements:
            sorties.append(LignePlanOut(**details | {"action": "METTRE_A_JOUR"}))
            a_modifier.append((lue, existant, cibles))
        else:
            sorties.append(LignePlanOut(**details | {"action": "INCHANGE"}))

    compte = {action: sum(1 for s in sorties if s.action == action) for action in
              ("CREER", "METTRE_A_JOUR", "INCHANGE", "IGNORE", "ERREUR")}
    nb_erreurs = compte["ERREUR"]

    # ── 4. Écriture, seulement si tout le fichier passe ─────────────────
    enregistre = False
    if not simulation and nb_erreurs == 0 and (a_creer or a_modifier):
        nouveaux: dict[str, ComptaCompte] = {}
        for lue in a_creer:
            nouveau = ComptaCompte(
                organisation_id=organisation_id,
                referentiel_id=referentiel.id,
                numero=lue.numero,
                libelle=lue.libelle,
                classe=lue.numero[0],
                nature=lue.nature,
                sens_normal=lue.sens,
                is_collectif=bool(lue.collectif),
                is_auxiliaire=bool(lue.auxiliaire),
                actif=True if lue.actif is None else lue.actif,
            )
            db.add(nouveau)
            nouveaux[lue.numero] = nouveau
        await db.flush()

        par_numero = existants | nouveaux
        for lue in a_creer:
            parent = parents.get(lue.numero)
            nouveaux[lue.numero].parent_id = par_numero[parent].id if parent else None
        for lue, existant, cibles in a_modifier:
            existant.libelle = cibles["libelle"]
            existant.nature = cibles["nature"]
            existant.sens_normal = cibles["sens_normal"]
            existant.is_collectif = cibles["is_collectif"]
            existant.is_auxiliaire = cibles["is_auxiliaire"]
            existant.actif = cibles["actif"]
            parent = cibles["parent_numero"]
            existant.parent_id = par_numero[parent].id if parent else None
            existant.updated_at = utcnow()
        await db.flush()
        enregistre = True

    if nb_erreurs:
        message = (
            f"{nb_erreurs} ligne(s) en erreur : aucun compte n'a été enregistré. "
            "Corrigez le fichier puis relancez l'import."
            if not simulation
            else f"{nb_erreurs} ligne(s) en erreur à corriger avant l'import."
        )
    elif not (a_creer or a_modifier):
        message = "Le plan est déjà à jour : aucun compte à créer ni à modifier."
    else:
        verbe = "seront" if simulation else "ont été"
        message = (
            f"{compte['CREER']} compte(s) {verbe} créé(s) et "
            f"{compte['METTRE_A_JOUR']} mis à jour."
        )

    return ImportPlanOut(
        simulation=simulation,
        enregistre=enregistre,
        total_lignes=len(sorties),
        crees=compte["CREER"],
        mis_a_jour=compte["METTRE_A_JOUR"],
        inchanges=compte["INCHANGE"],
        ignores=compte["IGNORE"],
        erreurs=nb_erreurs,
        lignes=sorties,
        message=message,
    )
