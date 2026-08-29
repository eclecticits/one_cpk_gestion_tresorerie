"""Entrées internes de trésorerie : les lignes qui justifient les totaux.

Un mouvement caisse ↔ banque n'est ni une recette ni une dépense : c'est de
l'argent de l'organisation qui change de poche. Il est pourtant une **entrée**
pour la poche qui reçoit, et les écrans qui présentent cette poche (clôture,
encaissements, journal de trésorerie, exports) doivent pouvoir l'afficher —
sinon la caisse paraît se remplir toute seule.

Ce module centralise ces listes pour que tous ces écrans montrent exactement
les mêmes lignes que celles agrégées dans les totaux (`clotures.py`,
`reports.py`, `treasury.py`).

**Deux sources, une seule liste.** Un tel mouvement vit aujourd'hui soit dans
`sorties_fonds` (chemin historique, sous `type_sortie = 'versement_banque'` ou
`'approvisionnement_caisse'`), soit dans `transferts_internes` (moteur dédié).
Les agrégateurs lisent **déjà les deux et les additionnent** ; ces listes le
font donc aussi. Une opération vit dans exactement une des deux tables, donc
l'union ne double compte pas — c'est l'invariant qui rend la bascule possible
sans jamais copier une ligne d'une table à l'autre.

Sans cette union, un total de clôture contiendrait un montant que sa propre
liste ne justifie pas : le pire symptôme possible sur un document signé.

Deux règles à ne pas défaire :

- **les bornes de date suivent la source.** Une sortie est datée par
  `coalesce(date_paiement, created_at)`, un transfert par `date_transfert` —
  exactement ce que font les agrégats. Uniformiser ici ferait diverger la liste
  du total qu'elle est censée détailler ;
- **aucun filtre sur `TransfertInterne.statut`.** La correction est additive :
  l'original (`CONTREPASSE`) et sa ligne inverse (`EXECUTE`) coexistent, se
  compensent, et les deux doivent rester lisibles. Masquer l'original tout en
  gardant l'inverse afficherait une entrée sans l'opération qu'elle corrige.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.banque import Banque
from app.models.compte_bancaire import CompteBancaire
from app.models.sortie_fonds import SortieFonds
from app.models.transfert_interne import TransfertInterne
from app.models.user import User

# `created_by` n'est pas une clé étrangère déclarée : la jointure est explicite.
Auteur = aliased(User)
#: Exécutant d'un transfert du moteur dédié (`execute_par`), même raison.
Executant = aliased(User)
#: Les deux jambes d'un transfert sont jointes séparément : la ligne doit
#: pouvoir nommer le compte qui reçoit **et** dire d'où l'argent vient. Un
#: virement de banque à banque n'a pas la caisse pour origine, et l'écrire
#: serait un faux sur un document exporté.
CompteSource = aliased(CompteBancaire)
BanqueSource = aliased(Banque)
CompteDestination = aliased(CompteBancaire)
BanqueDestination = aliased(Banque)


def sortie_timestamp():
    """Horodatage retenu pour une sortie : même règle que les agrégats."""
    return func.coalesce(SortieFonds.date_paiement, SortieFonds.created_at)


def _cle_tri(ligne: dict) -> datetime:
    """Ordonne des lignes venues de deux tables sans jamais lever.

    Les deux sources sont horodatées en `timestamptz`, mais une date nulle
    (sortie sans paiement ni création) ou naïve suffirait à faire échouer la
    comparaison et à vider un écran entier.
    """
    valeur = ligne.get("date") or ligne.get("created_at")
    if valeur is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return valeur if valeur.tzinfo is not None else valeur.replace(tzinfo=timezone.utc)


def _fusionner(*groupes: list[dict], limit: int | None = None) -> list[dict]:
    """Fusionne, trie par date décroissante, puis borne.

    Le `limit` s'applique **après** la fusion : borner chaque source séparément
    rendrait les N premières lignes de chacune, c'est-à-dire pas les N plus
    récentes de l'ensemble.
    """
    lignes = [ligne for groupe in groupes for ligne in groupe]
    lignes.sort(key=_cle_tri, reverse=True)
    return lignes[:limit] if limit else lignes


def _nom_personne(prenom, nom, email) -> str:
    return f"{prenom or ''} {nom or ''}".strip() or (email or "")


def _libelle_transfert(transfert: TransfertInterne) -> str:
    if transfert.transfert_origine_id is not None:
        return "Contre-passation d'un transfert interne"
    sens = {
        ("BANQUE", "CAISSE"): "Transfert interne banque → caisse",
        ("CAISSE", "BANQUE"): "Transfert interne caisse → banque",
        ("BANQUE", "BANQUE"): "Transfert interne entre comptes bancaires",
    }
    return sens.get((transfert.source_type, transfert.destination_type), "Transfert interne")


def _requete_transferts(tenant_id: int):
    """Transferts, joints à leurs deux jambes et à leur exécutant.

    Les jointures sont externes : `source_id` et `destination_id` valent NULL
    quand la jambe est la caisse, qui n'a pas de compte bancaire.
    """
    return (
        select(
            TransfertInterne,
            CompteSource, BanqueSource,
            CompteDestination, BanqueDestination,
            Executant,
        )
        .outerjoin(CompteSource, TransfertInterne.source_id == CompteSource.id)
        .outerjoin(BanqueSource, CompteSource.banque_id == BanqueSource.id)
        .outerjoin(CompteDestination, TransfertInterne.destination_id == CompteDestination.id)
        .outerjoin(BanqueDestination, CompteDestination.banque_id == BanqueDestination.id)
        .outerjoin(Executant, TransfertInterne.execute_par == Executant.id)
        .where(TransfertInterne.organisation_id == tenant_id)
        .order_by(TransfertInterne.date_transfert.desc())
    )


def _libelle_compte(banque, compte) -> str:
    return " - ".join(
        part for part in (getattr(banque, "nom", None), getattr(compte, "intitule", None)) if part
    )


def _borner_transferts(query, *, date_debut, date_fin, devise, strict_debut, limit):
    if devise:
        query = query.where(TransfertInterne.devise == devise.upper())
    if date_debut is not None:
        query = (
            query.where(TransfertInterne.date_transfert > date_debut)
            if strict_debut
            else query.where(TransfertInterne.date_transfert >= date_debut)
        )
    if date_fin is not None:
        query = query.where(TransfertInterne.date_transfert <= date_fin)
    if limit:
        query = query.limit(limit)
    return query


def _ligne_transfert(ligne_sql, *, cle_contrepartie: str) -> dict:
    """Ligne d'affichage d'un transfert, aux mêmes clés qu'une ligne de sortie.

    Les consommateurs (écran des encaissements, classeur d'encaissements,
    détail de clôture) ne distinguent pas les deux origines : c'est voulu, une
    entrée est une entrée. Seul `type_operation` les sépare, pour qui veut les
    reconnaître.

    Le compte nommé sur la ligne est celui qui **reçoit** pour une entrée
    bancaire, celui qui **envoie** pour une entrée en caisse — dans les deux
    cas, celui que l'écran a besoin de montrer.
    """
    transfert, compte_source, banque_source, compte_dest, banque_dest, executant = ligne_sql
    if cle_contrepartie == "destination":
        compte, banque = compte_dest, banque_dest
    else:
        compte, banque = compte_source, banque_source
    contrepartie = _libelle_compte(banque, compte)
    provenance = (
        "Caisse centrale"
        if transfert.source_type == "CAISSE"
        else (_libelle_compte(banque_source, compte_source) or "Banque")
    )
    return {
        #: Table d'où vient la ligne. `legacy` = `sorties_fonds`,
        #: `transfert_interne` = moteur dédié. Les deux cohabiteront tant que la
        #: bascule n'est pas terminée, et aucune référence n'est renumérotée :
        #: c'est le seul moyen de savoir, sur une ligne, quel moteur l'a écrite.
        "origine": "transfert_interne",
        #: D'où vient l'argent (pas d'où vient la ligne).
        "provenance": provenance,
        # Préfixé : un identifiant de transfert et un identifiant de sortie sont
        # deux entiers indépendants, et rien n'empêche le même. Sans préfixe,
        # deux lignes distinctes partageraient la même clé à l'affichage.
        "id": f"transfert-{transfert.id}",
        "date": transfert.date_transfert,
        "created_at": transfert.created_at,
        "reference": transfert.reference,
        "libelle": _libelle_transfert(transfert),
        "montant": Decimal(transfert.montant or 0),
        "devise": (transfert.devise or "USD").upper(),
        # Un transfert interne ne connaît pas de mode de paiement : rien ne
        # circule en espèces ou par chèque entre deux poches de la même
        # organisation.
        "mode_paiement": None,
        cle_contrepartie: contrepartie or "Banque",
        "banque": getattr(banque, "nom", None) or "",
        "compte_numero": getattr(compte, "numero_compte", None) or "",
        "auteur": _nom_personne(
            getattr(executant, "prenom", None),
            getattr(executant, "nom", None),
            getattr(executant, "email", None),
        ),
        "type_operation": "TRANSFERT_INTERNE",
        "sens": "ENTREE",
    }


def _requete_sorties(tenant_id: int, type_sortie: str):
    ts = sortie_timestamp()
    return (
        select(
            SortieFonds.id,
            ts.label("date"),
            SortieFonds.reference_numero,
            SortieFonds.reference,
            SortieFonds.motif,
            SortieFonds.montant_paye,
            SortieFonds.devise,
            SortieFonds.mode_paiement,
            SortieFonds.created_at,
            CompteBancaire.intitule,
            CompteBancaire.numero_compte,
            Banque.nom,
            Auteur.prenom,
            Auteur.nom,
            Auteur.email,
        )
        .outerjoin(CompteBancaire, SortieFonds.compte_bancaire_id == CompteBancaire.id)
        .outerjoin(Banque, CompteBancaire.banque_id == Banque.id)
        .outerjoin(Auteur, SortieFonds.created_by == Auteur.id)
        .where(
            SortieFonds.organisation_id == tenant_id,
            SortieFonds.type_sortie == type_sortie,
            (SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE"),
        )
        .order_by(ts.desc())
    )


def _ligne_sortie(row, *, libelle_defaut: str, cle_contrepartie: str, defaut: str, provenance: str, type_operation: str) -> dict:
    (
        sortie_id,
        date_value,
        reference_numero,
        reference,
        motif,
        montant,
        devise_ligne,
        mode_paiement,
        created_at,
        compte_intitule,
        compte_numero,
        banque_nom,
        auteur_prenom,
        auteur_nom,
        auteur_email,
    ) = row
    contrepartie = " - ".join(part for part in (banque_nom, compte_intitule) if part)
    return {
        #: Table d'où vient la ligne — voir `_ligne_transfert`.
        "origine": "legacy",
        #: D'où vient l'argent. Fixe pour le chemin historique — un
        #: approvisionnement vient toujours d'une banque, un versement toujours
        #: de la caisse —, calculé par jambe pour le moteur dédié.
        "provenance": provenance,
        "id": str(sortie_id),
        "date": date_value,
        "created_at": created_at,
        "reference": reference_numero or reference,
        "libelle": motif or libelle_defaut,
        "montant": Decimal(montant or 0),
        "devise": (devise_ligne or "USD").upper(),
        "mode_paiement": mode_paiement,
        cle_contrepartie: contrepartie or defaut,
        "banque": banque_nom or "",
        "compte_numero": compte_numero or "",
        "auteur": _nom_personne(auteur_prenom, auteur_nom, auteur_email),
        "type_operation": type_operation,
        "sens": "ENTREE",
    }


async def list_entrees_internes_caisse(
    db: AsyncSession,
    *,
    tenant_id: int,
    date_debut: datetime | None = None,
    date_fin: datetime | None = None,
    devise: str | None = None,
    strict_debut: bool = False,
    limit: int | None = None,
) -> list[dict]:
    """Argent qui entre en caisse sans être une recette client.

    Les deux sources réunies : approvisionnements banque → caisse de
    `sorties_fonds`, et transferts du moteur dédié dont la destination est la
    caisse. Ensemble, elles somment exactement le terme « entrées de
    transferts » des totaux de clôture.

    `strict_debut` reproduit la borne « > » de la balance de clôture : une
    opération horodatée à la clôture précédente appartient à la période close,
    pas à la suivante.
    """
    query = _requete_sorties(tenant_id, "approvisionnement_caisse")
    ts = sortie_timestamp()
    if devise:
        query = query.where(SortieFonds.devise == devise.upper())
    if date_debut is not None:
        query = query.where(ts > date_debut) if strict_debut else query.where(ts >= date_debut)
    if date_fin is not None:
        query = query.where(ts <= date_fin)
    if limit:
        query = query.limit(limit)
    approvisionnements = [
        _ligne_sortie(
            row,
            libelle_defaut="Approvisionnement de la caisse",
            cle_contrepartie="source",
            defaut="Banque",
            provenance="Banque",
            type_operation="APPROVISIONNEMENT",
        )
        for row in (await db.execute(query)).all()
    ]

    transferts_query = _borner_transferts(
        _requete_transferts(tenant_id).where(TransfertInterne.destination_type == "CAISSE"),
        date_debut=date_debut,
        date_fin=date_fin,
        devise=devise,
        strict_debut=strict_debut,
        limit=limit,
    )
    transferts = [
        _ligne_transfert(ligne, cle_contrepartie="source")
        for ligne in (await db.execute(transferts_query)).all()
    ]
    return _fusionner(approvisionnements, transferts, limit=limit)


async def list_entrees_internes_banque(
    db: AsyncSession,
    *,
    tenant_id: int,
    date_debut: datetime | None = None,
    date_fin: datetime | None = None,
    devise: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Argent qui entre sur un compte bancaire sans être une recette client.

    Les deux sources réunies : versements caisse → banque de `sorties_fonds`,
    et transferts du moteur dédié dont la destination est un compte bancaire —
    y compris de banque à banque, où la ligne nomme le compte qui reçoit.
    """
    query = _requete_sorties(tenant_id, "versement_banque")
    ts = sortie_timestamp()
    if devise:
        query = query.where(SortieFonds.devise == devise.upper())
    if date_debut is not None:
        query = query.where(ts >= date_debut)
    if date_fin is not None:
        query = query.where(ts <= date_fin)
    if limit:
        query = query.limit(limit)
    versements = [
        _ligne_sortie(
            row,
            libelle_defaut="Versement à la banque",
            cle_contrepartie="destination",
            defaut="Banque",
            provenance="Caisse",
            type_operation="VERSEMENT_BANQUE",
        )
        for row in (await db.execute(query)).all()
    ]

    transferts_query = _borner_transferts(
        _requete_transferts(tenant_id).where(TransfertInterne.destination_type == "BANQUE"),
        date_debut=date_debut,
        date_fin=date_fin,
        devise=devise,
        strict_debut=False,
        limit=limit,
    )
    transferts = [
        _ligne_transfert(ligne, cle_contrepartie="destination")
        for ligne in (await db.execute(transferts_query)).all()
    ]
    return _fusionner(versements, transferts, limit=limit)
