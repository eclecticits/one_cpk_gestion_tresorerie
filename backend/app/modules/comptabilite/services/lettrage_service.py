"""Lettrage des comptes de tiers.

Lettrer, c'est rapprocher sur un même compte les lignes qui se soldent — la
créance et son règlement, la facture et son paiement — en leur donnant une
même lettre. Ce qui reste sans lettre est ce qui reste dû : c'est la lecture
qu'attend un comptable d'un compte adhérent ou fournisseur.

Règles tenues ici :

- on ne lettre que des écritures **validées** ou clôturées : un brouillon peut
  encore changer de montant ;
- un groupe lettré est **soldé** dans la devise de tenue (débit = crédit) — le
  lettrage partiel n'est pas proposé, il masquerait un reste dû ;
- le lettrage ne modifie ni montant ni compte : c'est un pointage, réversible
  par délettrage, y compris sur un exercice clôturé ;
- le lettrage automatique ne rapproche que ce qui est **sans ambiguïté** : même
  référence de pièce soldée, puis montants identiques pris dans l'ordre des
  dates. Il ne tente aucune combinaison de montants.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.comptabilite.models import (
    ComptaCompte,
    ComptaEcriture,
    ComptaJournal,
    ComptaLigneEcriture,
)

STATUTS_LETTRABLES = ("VALIDEE", "CLOTUREE")
ZERO = Decimal("0")


class LettrageRefuse(Exception):
    """Le lettrage demandé enfreint une règle ; le message est destiné à l'utilisateur."""


@dataclass
class LigneLettrable:
    ligne_id: UUID
    ecriture_id: UUID
    numero: str | None
    date_ecriture: date
    journal_code: str
    libelle: str | None
    reference_piece: str | None
    debit: Decimal
    credit: Decimal
    compte_auxiliaire_id: int | None = None
    lettrage: str | None = None
    date_lettrage: date | None = None


@dataclass
class CompteALettrer:
    compte_id: int
    numero: str
    libelle: str
    lignes_non_lettrees: int
    debit_non_lettre: Decimal
    credit_non_lettre: Decimal

    @property
    def solde_non_lettre(self) -> Decimal:
        return self.debit_non_lettre - self.credit_non_lettre


@dataclass
class GroupePropose:
    compte_id: int
    compte_numero: str
    motif: str  # "REFERENCE" ou "MONTANT"
    lignes: list[LigneLettrable]
    montant: Decimal
    code: str | None = None


@dataclass
class RapportLettrageAuto:
    simulation: bool
    comptes_examines: int = 0
    groupes: list[GroupePropose] = field(default_factory=list)

    @property
    def lignes_lettrees(self) -> int:
        return sum(len(g.lignes) for g in self.groupes)


def code_suivant(dernier: str | None) -> str:
    """AA, AB … AZ, BA … ZZ, AAA … — la suite des lettres d'un compte."""
    if not dernier:
        return "AA"
    lettres = list(dernier)
    position = len(lettres) - 1
    while position >= 0:
        if lettres[position] != "Z":
            lettres[position] = chr(ord(lettres[position]) + 1)
            return "".join(lettres)
        lettres[position] = "A"
        position -= 1
    return "A" + "".join(lettres)


async def _dernier_code(db: AsyncSession, organisation_id: int, compte_id: int) -> str | None:
    """La plus grande lettre déjà posée sur le compte (les plus longues d'abord)."""
    res = await db.execute(
        select(ComptaLigneEcriture.lettrage)
        .where(
            ComptaLigneEcriture.organisation_id == organisation_id,
            ComptaLigneEcriture.compte_id == compte_id,
            ComptaLigneEcriture.lettrage.is_not(None),
        )
        .order_by(func.length(ComptaLigneEcriture.lettrage).desc(), ComptaLigneEcriture.lettrage.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


async def _compte_lettrable(
    db: AsyncSession,
    organisation_id: int,
    compte_id: int,
    *,
    verrouiller: bool = False,
) -> ComptaCompte:
    stmt = select(ComptaCompte).where(
        ComptaCompte.id == compte_id,
        ComptaCompte.organisation_id == organisation_id,
    )
    if verrouiller:
        # La lettre suivante est une séquence propre au compte. Sans verrou sur
        # le compte lui-même, deux rapprochements simultanés de lignes
        # différentes pourraient lire le même dernier code et recevoir tous
        # deux « AA » ; un délettrage retirerait alors les deux groupes.
        stmt = stmt.with_for_update()
    compte = (await db.execute(stmt)).scalar_one_or_none()
    if compte is None or compte.organisation_id != organisation_id:
        raise LettrageRefuse("Compte comptable introuvable pour cette organisation.")
    if not compte.lettrable:
        raise LettrageRefuse(f"Le compte {compte.numero} n'est pas lettrable.")
    return compte


async def comptes_a_lettrer(db: AsyncSession, *, organisation_id: int) -> list[CompteALettrer]:
    """Les comptes lettrables et ce qu'il leur reste de non lettré."""
    non_lettre = ComptaLigneEcriture.lettrage.is_(None)
    stmt = (
        select(
            ComptaCompte.id,
            ComptaCompte.numero,
            ComptaCompte.libelle,
            func.count(ComptaLigneEcriture.id).filter(non_lettre).label("nb"),
            func.coalesce(func.sum(ComptaLigneEcriture.debit_tenue).filter(non_lettre), 0).label("debit"),
            func.coalesce(func.sum(ComptaLigneEcriture.credit_tenue).filter(non_lettre), 0).label("credit"),
        )
        .select_from(ComptaCompte)
        .join(
            ComptaLigneEcriture,
            (ComptaLigneEcriture.compte_id == ComptaCompte.id)
            & (ComptaLigneEcriture.organisation_id == organisation_id),
        )
        .join(
            ComptaEcriture,
            (ComptaEcriture.id == ComptaLigneEcriture.ecriture_id)
            & (ComptaEcriture.organisation_id == organisation_id)
            & (ComptaEcriture.statut.in_(STATUTS_LETTRABLES)),
        )
        .where(ComptaCompte.organisation_id == organisation_id, ComptaCompte.lettrable.is_(True))
        .group_by(ComptaCompte.id, ComptaCompte.numero, ComptaCompte.libelle)
        .order_by(ComptaCompte.numero)
    )
    return [
        CompteALettrer(
            compte_id=row.id,
            numero=row.numero,
            libelle=row.libelle,
            lignes_non_lettrees=row.nb,
            debit_non_lettre=Decimal(row.debit),
            credit_non_lettre=Decimal(row.credit),
        )
        for row in (await db.execute(stmt)).all()
    ]


async def lignes_du_compte(
    db: AsyncSession,
    *,
    organisation_id: int,
    compte_id: int,
    inclure_lettrees: bool = False,
) -> list[LigneLettrable]:
    """Les lignes validées d'un compte, les plus anciennes d'abord."""
    stmt = (
        select(
            ComptaLigneEcriture.id,
            ComptaLigneEcriture.libelle.label("ligne_libelle"),
            ComptaLigneEcriture.debit_tenue,
            ComptaLigneEcriture.credit_tenue,
            ComptaLigneEcriture.compte_auxiliaire_id,
            ComptaLigneEcriture.lettrage,
            ComptaLigneEcriture.date_lettrage,
            ComptaEcriture.id.label("ecriture_id"),
            ComptaEcriture.numero,
            ComptaEcriture.date_ecriture,
            ComptaEcriture.libelle.label("ecriture_libelle"),
            ComptaEcriture.reference_piece,
            ComptaJournal.code.label("journal_code"),
        )
        .select_from(ComptaLigneEcriture)
        .join(ComptaEcriture, ComptaEcriture.id == ComptaLigneEcriture.ecriture_id)
        .join(ComptaJournal, ComptaJournal.id == ComptaEcriture.journal_id)
        .where(
            ComptaLigneEcriture.organisation_id == organisation_id,
            ComptaEcriture.organisation_id == organisation_id,
            ComptaLigneEcriture.compte_id == compte_id,
            ComptaEcriture.statut.in_(STATUTS_LETTRABLES),
        )
        .order_by(ComptaEcriture.date_ecriture, ComptaLigneEcriture.id)
    )
    if not inclure_lettrees:
        stmt = stmt.where(ComptaLigneEcriture.lettrage.is_(None))
    return [
        LigneLettrable(
            ligne_id=row.id,
            ecriture_id=row.ecriture_id,
            numero=row.numero,
            date_ecriture=row.date_ecriture,
            journal_code=row.journal_code,
            libelle=row.ligne_libelle or row.ecriture_libelle,
            reference_piece=row.reference_piece,
            debit=Decimal(row.debit_tenue),
            credit=Decimal(row.credit_tenue),
            compte_auxiliaire_id=row.compte_auxiliaire_id,
            lettrage=row.lettrage,
            date_lettrage=row.date_lettrage,
        )
        for row in (await db.execute(stmt)).all()
    ]


async def lettrer(
    db: AsyncSession,
    *,
    organisation_id: int,
    ligne_ids: list[UUID],
    user_id: UUID | None,
) -> str:
    """Pose une même lettre sur des lignes qui se soldent. Retourne la lettre."""
    ids = list(dict.fromkeys(ligne_ids))
    if len(ids) < 2:
        raise LettrageRefuse("Un lettrage rapproche au moins deux lignes.")

    res = await db.execute(
        select(ComptaLigneEcriture, ComptaEcriture.statut, ComptaEcriture.date_ecriture)
        .join(ComptaEcriture, ComptaEcriture.id == ComptaLigneEcriture.ecriture_id)
        .where(
            ComptaLigneEcriture.organisation_id == organisation_id,
            ComptaLigneEcriture.id.in_(ids),
        )
        .with_for_update(of=ComptaLigneEcriture)
    )
    rows = res.all()
    if len(rows) != len(ids):
        raise LettrageRefuse("Une ou plusieurs lignes sont introuvables pour cette organisation.")

    lignes = [row[0] for row in rows]
    if len({l.compte_id for l in lignes}) != 1:
        raise LettrageRefuse("Les lignes à lettrer doivent appartenir au même compte.")
    if len({l.compte_auxiliaire_id for l in lignes}) != 1:
        raise LettrageRefuse("Les lignes à lettrer doivent porter sur le même tiers.")
    compte = await _compte_lettrable(
        db, organisation_id, lignes[0].compte_id, verrouiller=True
    )

    if any(statut not in STATUTS_LETTRABLES for _, statut, _ in rows):
        raise LettrageRefuse("Seules les écritures validées se lettrent.")
    deja = sorted({l.lettrage for l in lignes if l.lettrage})
    if deja:
        raise LettrageRefuse(
            f"Ligne(s) déjà lettrée(s) ({', '.join(deja)}) : délettrez-les d'abord."
        )

    debit = sum((Decimal(l.debit_tenue) for l in lignes), ZERO)
    credit = sum((Decimal(l.credit_tenue) for l in lignes), ZERO)
    if debit != credit:
        raise LettrageRefuse(
            f"Les lignes ne se soldent pas : débit {debit} ≠ crédit {credit} (écart {debit - credit})."
        )

    code = code_suivant(await _dernier_code(db, organisation_id, compte.id))
    jour = max(date_ecriture for _, _, date_ecriture in rows)
    for ligne in lignes:
        ligne.lettrage = code
        ligne.date_lettrage = jour
        ligne.lettre_par = user_id
    await db.flush()
    return code


async def delettrer(db: AsyncSession, *, organisation_id: int, compte_id: int, code: str) -> int:
    """Retire une lettre sur tout son groupe. Retourne le nombre de lignes libérées."""
    res = await db.execute(
        select(ComptaLigneEcriture)
        .where(
            ComptaLigneEcriture.organisation_id == organisation_id,
            ComptaLigneEcriture.compte_id == compte_id,
            ComptaLigneEcriture.lettrage == code,
        )
        .with_for_update()
    )
    lignes = list(res.scalars())
    if not lignes:
        raise LettrageRefuse(f"Aucune ligne ne porte la lettre {code} sur ce compte.")
    for ligne in lignes:
        ligne.lettrage = None
        ligne.date_lettrage = None
        ligne.lettre_par = None
    await db.flush()
    return len(lignes)


def proposer_groupes(lignes: list[LigneLettrable]) -> list[tuple[str, list[LigneLettrable]]]:
    """Les rapprochements sans ambiguïté parmi des lignes non lettrées d'un même tiers.

    1. Même référence de pièce, et le groupe se solde : la créance et son
       règlement portent le même numéro.
    2. Parmi le reste, un débit et un crédit de même montant, pris dans l'ordre
       des dates : le plus ancien débit avec le plus ancien crédit.
    """
    groupes: list[tuple[str, list[LigneLettrable]]] = []
    prises: set[UUID] = set()

    par_reference: dict[str, list[LigneLettrable]] = defaultdict(list)
    for ligne in lignes:
        reference = (ligne.reference_piece or "").strip().upper()
        if reference:
            par_reference[reference].append(ligne)
    for groupe in par_reference.values():
        debit = sum((l.debit for l in groupe), ZERO)
        credit = sum((l.credit for l in groupe), ZERO)
        if len(groupe) >= 2 and debit == credit and debit > 0:
            groupes.append(("REFERENCE", groupe))
            prises.update(l.ligne_id for l in groupe)

    debits: dict[Decimal, list[LigneLettrable]] = defaultdict(list)
    credits: dict[Decimal, list[LigneLettrable]] = defaultdict(list)
    for ligne in lignes:  # déjà triées par date
        if ligne.ligne_id in prises:
            continue
        if ligne.debit > 0:
            debits[ligne.debit].append(ligne)
        elif ligne.credit > 0:
            credits[ligne.credit].append(ligne)
    for montant, cote_debit in debits.items():
        for ligne_debit, ligne_credit in zip(cote_debit, credits.get(montant, [])):
            groupes.append(("MONTANT", [ligne_debit, ligne_credit]))
    return groupes


async def lettrage_automatique(
    db: AsyncSession,
    *,
    organisation_id: int,
    compte_id: int | None = None,
    simulation: bool = True,
    user_id: UUID | None = None,
) -> RapportLettrageAuto:
    """Lettre ce qui se rapproche sans ambiguïté, sur un compte ou sur tous."""
    if compte_id is not None:
        compte = await _compte_lettrable(db, organisation_id, compte_id)
        cibles = [(compte.id, compte.numero)]
    else:
        cibles = [
            (c.compte_id, c.numero)
            for c in await comptes_a_lettrer(db, organisation_id=organisation_id)
            if c.lignes_non_lettrees >= 2
        ]

    rapport = RapportLettrageAuto(simulation=simulation, comptes_examines=len(cibles))
    for cible_id, numero in cibles:
        lignes = await lignes_du_compte(db, organisation_id=organisation_id, compte_id=cible_id)
        # Un collectif se lettre tiers par tiers : jamais d'un adhérent à l'autre.
        par_tiers: dict[int | None, list[LigneLettrable]] = defaultdict(list)
        for ligne in lignes:
            par_tiers[ligne.compte_auxiliaire_id].append(ligne)
        for lignes_tiers in par_tiers.values():
            for motif, groupe in proposer_groupes(lignes_tiers):
                propose = GroupePropose(
                    compte_id=cible_id,
                    compte_numero=numero,
                    motif=motif,
                    lignes=groupe,
                    montant=sum((l.debit for l in groupe), ZERO),
                )
                if not simulation:
                    propose.code = await lettrer(
                        db,
                        organisation_id=organisation_id,
                        ligne_ids=[l.ligne_id for l in groupe],
                        user_id=user_id,
                    )
                rapport.groupes.append(propose)
    return rapport


async def definir_lettrable(
    db: AsyncSession, *, organisation_id: int, compte_id: int, lettrable: bool
) -> ComptaCompte:
    """Rend un compte lettrable ou non. Un compte portant des lettres le reste."""
    compte = await db.get(ComptaCompte, compte_id)
    if compte is None or compte.organisation_id != organisation_id:
        raise LettrageRefuse("Compte comptable introuvable pour cette organisation.")
    if not lettrable and await _dernier_code(db, organisation_id, compte_id):
        raise LettrageRefuse(
            f"Le compte {compte.numero} porte des lignes lettrées : délettrez-les avant de le rendre non lettrable."
        )
    compte.lettrable = lettrable
    await db.flush()
    return compte
