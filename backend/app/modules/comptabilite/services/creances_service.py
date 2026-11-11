"""Créances des tiers, constatées à l'émission des notes de débit.

Jusqu'ici la comptabilité ne connaissait une cotisation qu'au moment où elle
était payée (trésorerie contre produit). Le logiciel comptable en place fait
autrement, et c'est ce que ce service reproduit :

- à l'émission de la note, journal des créances (« Adhérents » par défaut,
  le nom se règle) : le compte du tiers au
  débit, les produits au crédit ;
- au règlement : la trésorerie au débit, le compte du membre au crédit
  (cf. `compte_creance_de_la_note`, lu par `encaissement_payments`).

**Un compte par tiers** — membre ou autre client —, ouvert à la demande sous
le compte racine choisi au paramétrage. Reporter un versement d'une note à l'autre du même membre est
donc neutre en comptabilité : les deux notes vivent sur le même compte.

Le mode est un **choix de la société** (`creances_actives`), éteint par
défaut : l'allumer change la date à laquelle un produit entre au résultat.
Une note qui n'a pas d'écriture de créance — émise avant la bascule — reste
réglée comme avant, trésorerie contre produit : jamais de double comptage.

Une note actualisée par réimport ne modifie pas son écriture : l'ancienne est
annulée (brouillon) ou contre-passée (validée), une nouvelle est générée.
"""

from __future__ import annotations

import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.encaissement import Encaissement, EncaissementArticle
from app.models.client import Client
from app.models.expert_comptable import ExpertComptable
from app.modules.comptabilite.models import (
    ComptaCompte,
    ComptaEcriture,
    ComptaJournal,
    ComptaLigneEcriture,
    ComptaSociete,
)
from app.modules.comptabilite.services.ecriture_service import contrepasser_ecriture
from app.modules.comptabilite.services.generation_service import (
    _ajouter_lignes,
    _get_exercice_for_date,
    _taux_vers_tenue,
    resolve_compte_poste_budgetaire,
)
from app.modules.comptabilite.services.integration_mode import get_accounting_integration_mode

MODULE_ORIGINE = "encaissements"
TYPE_ORIGINE_NOTE = "note_debit"
JOURNAL_CREANCES_CODE = "ADR"
JOURNAL_CREANCES_LIBELLE = "Adhérents"
LIBELLE_TIERS_DEFAUT = "membre"
ZERO = Decimal("0")
CENT = Decimal("0.01")
#: Chiffres réservés au numéro d'ordre du compte d'un membre sous la racine.
CHIFFRES_SEQUENCE = 4


def _refus(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _cle_nom(valeur: str | None) -> str:
    """Majuscules sans accents ni ponctuation : « Kabongo, J. » = « KABONGO J »."""
    texte = unicodedata.normalize("NFKD", valeur or "")
    texte = "".join(c for c in texte if not unicodedata.combining(c)).upper()
    return " ".join("".join(c if c.isalnum() else " " for c in texte).split())


async def societe_par_defaut(db: AsyncSession, organisation_id: int) -> ComptaSociete | None:
    return (
        await db.execute(
            select(ComptaSociete).where(
                ComptaSociete.organisation_id == organisation_id, ComptaSociete.is_default.is_(True)
            )
        )
    ).scalar_one_or_none()


async def _societe_en_creances(db: AsyncSession, organisation_id: int) -> ComptaSociete | None:
    """La société, si elle constate ses créances et génère ses écritures ; sinon None."""
    societe = await societe_par_defaut(db, organisation_id)
    if societe is None or not societe.creances_actives:
        return None
    if await get_accounting_integration_mode(db, organisation_id) != "automatic":
        return None
    return societe


async def _journal_creances(db: AsyncSession, organisation_id: int, societe_id: int) -> ComptaJournal:
    journal = (
        await db.execute(
            select(ComptaJournal).where(
                ComptaJournal.organisation_id == organisation_id,
                ComptaJournal.societe_id == societe_id,
                ComptaJournal.code == JOURNAL_CREANCES_CODE,
            )
        )
    ).scalar_one_or_none()
    if journal is None:
        societe = await db.get(ComptaSociete, societe_id)
        journal = ComptaJournal(
            organisation_id=organisation_id,
            societe_id=societe_id,
            code=JOURNAL_CREANCES_CODE,
            libelle=(societe.libelle_journal_creances if societe else None) or JOURNAL_CREANCES_LIBELLE,
            type_journal="VE",
        )
        db.add(journal)
        await db.flush()
    return journal


# ── Paramétrage ──────────────────────────────────────────────────────────────


async def regler_creances(
    db: AsyncSession,
    *,
    organisation_id: int,
    actif: bool,
    compte_racine_id: int | None,
    compte_racine_clients_id: int | None = None,
    libelle_tiers: str | None = None,
    libelle_journal: str | None = None,
) -> ComptaSociete:
    """Allume ou éteint la constatation des créances et fixe le compte racine.

    `libelle_tiers` et `libelle_journal` sont le vocabulaire de l'organisation
    (« membre », « Adhérents »…) ; laissés à None, ils ne changent pas.
    """
    societe = await societe_par_defaut(db, organisation_id)
    if societe is None:
        raise _refus("La comptabilité n'est pas activée pour cette organisation.")
    for racine_id in (compte_racine_id, compte_racine_clients_id):
        if racine_id is None:
            continue
        racine = await db.get(ComptaCompte, racine_id)
        if racine is None or racine.organisation_id != organisation_id:
            raise _refus("Compte racine introuvable pour cette organisation.")
        if not racine.actif:
            raise _refus(f"Le compte {racine.numero} est inactif.")
        if not racine.numero.startswith("4"):
            raise _refus("Le compte racine des créances doit être un compte de tiers (classe 4).")
        if racine.tiers_expert_id is not None or racine.tiers_client_id is not None:
            raise _refus(f"Le compte {racine.numero} est déjà le compte individuel d'un tiers.")
    if actif and compte_racine_id is None:
        raise _refus("Choisissez le compte sous lequel ouvrir les comptes des tiers.")
    societe.creances_actives = actif
    societe.compte_creances_racine_id = compte_racine_id
    societe.compte_creances_clients_racine_id = compte_racine_clients_id
    if libelle_tiers is not None:
        societe.libelle_tiers = " ".join(libelle_tiers.split())[:40] or LIBELLE_TIERS_DEFAUT
    if libelle_journal is not None:
        societe.libelle_journal_creances = " ".join(libelle_journal.split())[:100] or JOURNAL_CREANCES_LIBELLE
    societe.updated_at = datetime.now(timezone.utc)
    await db.flush()
    journal = (
        await _journal_creances(db, organisation_id, societe.id)
        if actif
        else (
            await db.execute(
                select(ComptaJournal).where(
                    ComptaJournal.organisation_id == organisation_id,
                    ComptaJournal.societe_id == societe.id,
                    ComptaJournal.code == JOURNAL_CREANCES_CODE,
                )
            )
        ).scalar_one_or_none()
    )
    if journal is not None and journal.libelle != societe.libelle_journal_creances:
        journal.libelle = societe.libelle_journal_creances
    await db.flush()
    return societe


# ── Compte du membre ─────────────────────────────────────────────────────────


def numero_suivant(racine: str, pris: set[str]) -> str:
    """Le prochain numéro libre sous la racine.

    Les zéros de fin d'une racine sont la place du numéro d'ordre :
    4111010000 → 4111010001, 4111010002… Une racine courte (411) reçoit quatre
    chiffres : 4110001.
    """
    prefixe = racine.rstrip("0") or racine
    longueur = max(len(racine), len(prefixe) + CHIFFRES_SEQUENCE)
    largeur = longueur - len(prefixe)
    for rang in range(1, 10**largeur):
        numero = f"{prefixe}{rang:0{largeur}d}"
        if numero not in pris:
            return numero
    raise _refus(f"Plus aucun numéro libre sous le compte {racine} : choisissez une racine plus courte.")


async def compte_du_tiers(
    db: AsyncSession,
    *,
    organisation_id: int,
    societe: ComptaSociete,
    expert_id: uuid.UUID | None = None,
    client_id: uuid.UUID | None = None,
) -> ComptaCompte:
    """Le compte individuel du tiers ; ouvert à sa première créance.

    Le tiers est un membre (`expert_id`) ou un autre client (`client_id`) :
    tous les clients d'une organisation ne sont pas ses membres. Les clients
    s'ouvrent sous leur propre racine si elle est réglée, sinon sous la même.
    """
    if expert_id is not None:
        lien, racine_id = ComptaCompte.tiers_expert_id == expert_id, societe.compte_creances_racine_id
    elif client_id is not None:
        lien = ComptaCompte.tiers_client_id == client_id
        racine_id = societe.compte_creances_clients_racine_id or societe.compte_creances_racine_id
    else:
        raise _refus("Note sans tiers identifié : impossible de constater sa créance.")

    existant = (
        await db.execute(select(ComptaCompte).where(ComptaCompte.organisation_id == organisation_id, lien))
    ).scalar_one_or_none()
    if existant is not None:
        return existant

    racine = await db.get(ComptaCompte, racine_id) if racine_id else None
    if racine is None or racine.organisation_id != organisation_id:
        raise _refus(
            "Compte racine des créances non paramétré : réglez-le dans Comptabilité → Paramétrage → Créances."
        )
    if expert_id is not None:
        expert = await db.get(ExpertComptable, expert_id)
        nom = (expert.nom_denomination or expert.numero_ordre) if expert is not None else None
    else:
        client = await db.get(Client, client_id)
        nom = client.nom if client is not None and client.organisation_id == organisation_id else None
    if not nom:
        raise _refus("Tiers introuvable : impossible d'ouvrir son compte.")

    prefixe = racine.numero.rstrip("0") or racine.numero
    voisins = list(
        (
            await db.execute(
                select(ComptaCompte).where(
                    ComptaCompte.organisation_id == organisation_id,
                    ComptaCompte.referentiel_id == racine.referentiel_id,
                    ComptaCompte.numero.like(f"{prefixe}%"),
                )
            )
        ).scalars()
    )
    # Un plan repris d'un autre logiciel comptable contient déjà un compte au
    # nom du tiers : on le rattache plutôt que d'en ouvrir un second.
    cle = _cle_nom(nom)
    homonymes = [
        c for c in voisins
        if c.id != racine.id and c.tiers_expert_id is None and c.tiers_client_id is None
        and c.actif and not c.is_collectif and _cle_nom(c.libelle) == cle
    ]
    if len(homonymes) == 1:
        compte = homonymes[0]
        compte.lettrable = True
    else:
        compte = ComptaCompte(
            organisation_id=organisation_id,
            referentiel_id=racine.referentiel_id,
            numero=numero_suivant(racine.numero, {c.numero for c in voisins}),
            libelle=nom[:255],
            classe=racine.classe or racine.numero[0],
            parent_id=racine.id,
            nature=racine.nature,
            sens_normal=racine.sens_normal,
            lettrable=True,
        )
        db.add(compte)
    if expert_id is not None:
        compte.tiers_expert_id = expert_id
    else:
        compte.tiers_client_id = client_id
    await db.flush()
    return compte


# ── Écriture de créance ──────────────────────────────────────────────────────


async def _ecritures_de_la_note(
    db: AsyncSession, organisation_id: int, encaissement_id: uuid.UUID
) -> list[ComptaEcriture]:
    """Toutes les versions de l'écriture de créance d'une note, la plus ancienne d'abord."""
    cle = str(encaissement_id)
    return list(
        (
            await db.execute(
                select(ComptaEcriture)
                .where(
                    ComptaEcriture.organisation_id == organisation_id,
                    ComptaEcriture.module_origine == MODULE_ORIGINE,
                    ComptaEcriture.type_origine == TYPE_ORIGINE_NOTE,
                    or_(
                        ComptaEcriture.objet_origine_id == cle,
                        ComptaEcriture.objet_origine_id.like(f"{cle}:%"),
                    ),
                )
                .order_by(ComptaEcriture.created_at, ComptaEcriture.objet_origine_id)
            )
        ).scalars()
    )


def _courante(versions: list[ComptaEcriture]) -> ComptaEcriture | None:
    actives = [e for e in versions if e.statut != "ANNULEE"]
    return actives[-1] if actives else None


async def _lignes(db: AsyncSession, ecriture_id: uuid.UUID) -> list[ComptaLigneEcriture]:
    return list(
        (
            await db.execute(
                select(ComptaLigneEcriture)
                .where(ComptaLigneEcriture.ecriture_id == ecriture_id)
                .order_by(ComptaLigneEcriture.ordre)
            )
        ).scalars()
    )


async def compte_creance_de_la_note(
    db: AsyncSession, *, organisation_id: int, encaissement_id: uuid.UUID
) -> int | None:
    """Le compte du membre à créditer au règlement, si la créance de la note est constatée."""
    courante = _courante(await _ecritures_de_la_note(db, organisation_id, encaissement_id))
    if courante is None:
        return None
    for ligne in await _lignes(db, courante.id):
        if ligne.debit > 0:
            return ligne.compte_id
    return None


async def _neutraliser(
    db: AsyncSession, *, organisation_id: int, ecriture: ComptaEcriture, motif: str, user_id
) -> None:
    if ecriture.statut == "BROUILLON":
        ecriture.statut = "ANNULEE"
        ecriture.motif_annulation = motif
        ecriture.annule_par = user_id
        ecriture.annule_le = datetime.now(timezone.utc)
        ecriture.updated_at = ecriture.annule_le
        await db.flush()
        return
    await contrepasser_ecriture(
        db, ecriture_id=ecriture.id, organisation_id=organisation_id, user_id=user_id, motif=motif
    )


async def synchroniser_creance_note(
    db: AsyncSession,
    *,
    organisation_id: int,
    encaissement_id: uuid.UUID,
    user_id=None,
) -> ComptaEcriture | None:
    """Met l'écriture de créance d'une note en accord avec la note.

    À appeler après toute création, actualisation ou annulation d'une note.
    Idempotent : une note inchangée garde son écriture. Sans effet si la
    société ne constate pas ses créances — sauf pour une note qui a déjà une
    écriture : celle-là est toujours suivie, même après l'extinction du mode.
    """
    versions = await _ecritures_de_la_note(db, organisation_id, encaissement_id)
    courante = _courante(versions)
    societe = await _societe_en_creances(db, organisation_id)
    if societe is None and courante is None:
        return None
    if societe is None:
        societe = await societe_par_defaut(db, organisation_id)
        if societe is None:
            return None

    note = (
        await db.execute(
            select(Encaissement).where(
                Encaissement.id == encaissement_id, Encaissement.organisation_id == organisation_id
            )
        )
    ).scalar_one_or_none()
    total = Decimal(str(note.montant_total or 0)).quantize(CENT) if note is not None else ZERO
    a_constater = (
        note is not None
        and (note.expert_comptable_id is not None or note.client_id is not None)
        and not note.est_proforma
        and not note.is_deleted
        and (note.statut_operation or "ACTIVE").upper() != "ANNULEE"
        and bool(note.impact_budgetaire)
        and total > 0
    )
    if not a_constater:
        if courante is not None:
            await _neutraliser(
                db, organisation_id=organisation_id, ecriture=courante, user_id=user_id,
                motif=f"Note de débit {note.numero_recu if note else ''} annulée".strip(),
            )
        return None

    articles = list(
        (
            await db.execute(
                select(EncaissementArticle)
                .where(EncaissementArticle.encaissement_id == note.id)
                .order_by(EncaissementArticle.sort_order)
            )
        ).scalars()
    )
    par_poste: dict[int, Decimal] = {}
    libelle_poste: dict[int, str] = {}
    for article in articles:
        poste_id = article.budget_poste_id or note.budget_poste_id
        if poste_id is None:
            raise _refus(f"Note {note.numero_recu} : une ligne n'a pas de poste budgétaire.")
        par_poste[poste_id] = par_poste.get(poste_id, ZERO) + Decimal(str(article.montant or 0))
        libelle_poste.setdefault(poste_id, article.libelle)
    if not articles:
        if note.budget_poste_id is None:
            raise _refus(f"Note {note.numero_recu} : aucun poste budgétaire.")
        par_poste[note.budget_poste_id] = total
        libelle_poste[note.budget_poste_id] = note.libelle
    if sum(par_poste.values(), ZERO).quantize(CENT) != total:
        raise _refus(
            f"Note {note.numero_recu} : la somme de ses lignes diffère de son total ({total})."
        )

    # Un membre d'abord : sa fiche client éventuelle ne lui ouvre pas un second compte.
    membre = await compte_du_tiers(
        db, organisation_id=organisation_id, societe=societe,
        expert_id=note.expert_comptable_id,
        client_id=note.client_id if note.expert_comptable_id is None else None,
    )
    credits: dict[int, tuple[Decimal, str]] = {}
    for poste_id, montant in par_poste.items():
        if montant == 0:
            continue
        compte = await resolve_compte_poste_budgetaire(db, organisation_id, poste_id)
        deja, libelle = credits.get(compte.id, (ZERO, libelle_poste[poste_id]))
        credits[compte.id] = (deja + montant, libelle)

    cible = sorted(
        [(membre.id, total, ZERO)] + [(cid, ZERO, m.quantize(CENT)) for cid, (m, _) in credits.items()]
    )
    if courante is not None:
        actuel = sorted(
            (l.compte_id, Decimal(l.debit).quantize(CENT), Decimal(l.credit).quantize(CENT))
            for l in await _lignes(db, courante.id)
        )
        if actuel == cible:
            return courante
        await _neutraliser(
            db, organisation_id=organisation_id, ecriture=courante, user_id=user_id,
            motif=f"Note de débit {note.numero_recu} actualisée",
        )

    # La première écriture porte la date de la note ; une actualisation est
    # datée du jour où elle est faite, comme la contre-passation qu'elle suit.
    jour: date = (
        (note.date_encaissement or datetime.now(timezone.utc)).date()
        if not versions
        else datetime.now(timezone.utc).date()
    )
    exercice = await _get_exercice_for_date(db, organisation_id, societe.id, jour)
    journal = await _journal_creances(db, organisation_id, societe.id)
    taux = await _taux_vers_tenue(
        db, organisation_id=organisation_id, exercice=exercice, devise="USD", date_operation=jour
    )
    libelle = f"Note de débit {note.numero_recu} — {membre.libelle}"[:255]
    ecriture = ComptaEcriture(
        organisation_id=organisation_id,
        societe_id=societe.id,
        exercice_id=exercice.id,
        journal_id=journal.id,
        numero=None,
        date_ecriture=jour,
        reference_piece=note.numero_recu,
        libelle=libelle,
        statut="BROUILLON",
        devise="USD",
        taux_change=taux,
        module_origine=MODULE_ORIGINE,
        type_origine=TYPE_ORIGINE_NOTE,
        objet_origine_id=str(note.id) if not versions else f"{note.id}:{len(versions) + 1}",
        est_automatique=True,
        created_by=user_id,
    )
    db.add(ecriture)
    await db.flush()
    _ajouter_lignes(
        db, ecriture=ecriture, organisation_id=organisation_id, societe_id=societe.id,
        devise="USD", taux=taux,
        lignes=[
            (membre.id, total, ZERO, libelle),
            *[(cid, ZERO, m.quantize(CENT), lib) for cid, (m, lib) in credits.items()],
        ],
    )
    await db.flush()
    # L'échéance de la note suit la créance : c'est elle qui fait vieillir le
    # reste dû dans la balance âgée.
    if note.date_echeance is not None:
        for ligne in await _lignes(db, ecriture.id):
            if ligne.compte_id == membre.id:
                ligne.date_echeance = note.date_echeance
        await db.flush()
    return ecriture


# ── Reprise des notes déjà émises ────────────────────────────────────────────


@dataclass
class RapportReprise:
    simulation: bool
    constatees: int = 0
    montant: Decimal = ZERO
    deja_reglees_en_partie: int = 0
    echecs: list[tuple[str, str]] = field(default_factory=list)


async def notes_sans_creance(db: AsyncSession, *, organisation_id: int) -> list[Encaissement]:
    """Les notes non soldées d'un tiers identifié qui n'ont pas d'écriture de créance."""
    constatees = (
        select(func.substr(ComptaEcriture.objet_origine_id, 1, 36))
        .where(
            ComptaEcriture.organisation_id == organisation_id,
            ComptaEcriture.module_origine == MODULE_ORIGINE,
            ComptaEcriture.type_origine == TYPE_ORIGINE_NOTE,
        )
    )
    return list(
        (
            await db.execute(
                select(Encaissement)
                .where(
                    Encaissement.organisation_id == organisation_id,
                    or_(Encaissement.expert_comptable_id.is_not(None), Encaissement.client_id.is_not(None)),
                    Encaissement.est_proforma.is_(False),
                    Encaissement.is_deleted.is_(False),
                    Encaissement.impact_budgetaire.is_(True),
                    Encaissement.statut_operation != "ANNULEE",
                    Encaissement.statut_paiement != "paye",
                    Encaissement.montant_total > 0,
                    func.cast(Encaissement.id, ComptaEcriture.objet_origine_id.type).not_in(constatees),
                )
                .order_by(Encaissement.date_encaissement, Encaissement.numero_recu)
            )
        ).scalars()
    )


async def constater_notes_existantes(
    db: AsyncSession, *, organisation_id: int, simulation: bool = True, user_id=None
) -> RapportReprise:
    """Constate la créance des notes émises avant la bascule et encore vierges.

    Une note déjà réglée en partie a vu ce règlement passer en produit : la
    constater en entier compterait ce produit deux fois. Elle est laissée en
    comptabilité de caisse et seulement comptée dans le rapport.
    """
    rapport = RapportReprise(simulation=simulation)
    if await _societe_en_creances(db, organisation_id) is None:
        raise _refus(
            "La constatation des créances n'est pas activée (ou la comptabilité n'est pas en mode automatique)."
        )
    for note in await notes_sans_creance(db, organisation_id=organisation_id):
        if Decimal(str(note.montant_paye or 0)) > 0:
            rapport.deja_reglees_en_partie += 1
            continue
        numero, total = note.numero_recu or str(note.id), Decimal(str(note.montant_total or 0))
        try:
            async with db.begin_nested() as point:
                await synchroniser_creance_note(
                    db, organisation_id=organisation_id, encaissement_id=note.id, user_id=user_id
                )
                if simulation:
                    await point.rollback()
        except HTTPException as exc:
            rapport.echecs.append((numero, str(exc.detail)))
            continue
        rapport.constatees += 1
        rapport.montant += total
    return rapport
