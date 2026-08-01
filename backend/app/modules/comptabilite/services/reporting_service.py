"""Restitutions comptables (Lot 4) — Grand Livre, Journal, Balance.

Trois décisions structurent ce module.

**1. Quelles écritures entrent dans les états.**
Seules les écritures VALIDEE et CLOTUREE. Un BROUILLON n'a pas de numéro et
peut encore changer ; une écriture ANNULEE a été neutralisée (contre-passation
ou abandon de brouillon). Les mélanger produirait des états faux.
`inclure_brouillons` permet une **simulation** explicite — jamais le défaut,
et l'appelant doit signaler à l'utilisateur que l'état n'est plus officiel.

**2. Filtre `organisation_id` explicite partout (contrainte C2).**
Le scoping multi-tenant du projet n'agit que sur l'ORM. Ces requêtes restent
écrites en SQLAlchemy Core/ORM — elles bénéficient donc du scoping — mais
chaque `where` porte malgré tout `organisation_id` en dur : une bascule
ultérieure vers du SQL brut pour la performance ne doit pas ouvrir de fuite
inter-organisations par omission.

**3. Agrégation directe, pas de soldes pré-calculés.**
Le dossier d'architecture prévoit une table `compta_solde_periode` alimentée à
la validation. Elle n'est volontairement PAS introduite ici : un agrégat
dénormalisé peut diverger du détail, et sur des données financières cette
divergence est un bug silencieux. La Balance est donc calculée par `GROUP BY`
sur les lignes, ce qui est exact par construction. À introduire quand le
volume l'exigera (ordre de grandeur : au-delà du million de lignes par
exercice, ou si la Balance dépasse ~1 s), avec un test de cohérence
agrégat/détail obligatoire.

Les montants sont toujours agrégés dans la **devise de tenue** de l'exercice
(`debit_tenue` / `credit_tenue`) : c'est elle qui fait foi au Grand Livre, une
écriture multi-devises pouvant être déséquilibrée dans les devises d'origine.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.comptabilite.models import (
    ComptaCompte,
    ComptaEcriture,
    ComptaJournal,
    ComptaLigneEcriture,
)

# Une écriture n'entre au Grand Livre qu'une fois validée. ANNULEE n'y figure
# jamais : son effet a déjà été neutralisé.
STATUTS_COMPTABILISES = ("VALIDEE", "CLOTUREE")
STATUTS_AVEC_BROUILLONS = ("VALIDEE", "CLOTUREE", "BROUILLON")


def _statuts(inclure_brouillons: bool) -> tuple[str, ...]:
    return STATUTS_AVEC_BROUILLONS if inclure_brouillons else STATUTS_COMPTABILISES


def _q(montant) -> Decimal:
    return Decimal(montant or 0)


@dataclass
class LigneBalance:
    compte_id: int
    compte_numero: str
    compte_libelle: str
    nature: str
    total_debit: Decimal
    total_credit: Decimal

    @property
    def solde_debiteur(self) -> Decimal:
        ecart = self.total_debit - self.total_credit
        return ecart if ecart > 0 else Decimal("0")

    @property
    def solde_crediteur(self) -> Decimal:
        ecart = self.total_credit - self.total_debit
        return ecart if ecart > 0 else Decimal("0")


@dataclass
class Balance:
    lignes: list[LigneBalance]
    total_debit: Decimal
    total_credit: Decimal
    total_solde_debiteur: Decimal
    total_solde_crediteur: Decimal

    @property
    def equilibree(self) -> bool:
        """Une balance déséquilibrée signale une corruption des données.

        L'équilibre est garanti écriture par écriture à la validation ; s'il
        est rompu ici, c'est qu'une ligne a été altérée hors du service. Le
        signaler vaut mieux que d'afficher un état faux sans avertissement.
        """
        return self.total_debit == self.total_credit


@dataclass
class MouvementGrandLivre:
    ligne_id: UUID
    ecriture_id: UUID
    numero: str | None
    date_ecriture: date
    journal_code: str
    libelle: str | None
    reference_piece: str | None
    debit: Decimal
    credit: Decimal
    statut: str
    solde_cumule: Decimal


@dataclass
class GrandLivre:
    compte_id: int
    compte_numero: str
    compte_libelle: str
    solde_anterieur: Decimal
    mouvements: list[MouvementGrandLivre]
    total_debit_page: Decimal
    total_credit_page: Decimal
    solde_final_page: Decimal
    curseur_suivant: str | None


@dataclass
class EcritureJournal:
    ecriture_id: UUID
    numero: str | None
    date_ecriture: date
    libelle: str
    statut: str
    total_debit: Decimal
    total_credit: Decimal


@dataclass
class LivreJournal:
    journal_id: int
    journal_code: str
    journal_libelle: str
    ecritures: list[EcritureJournal]
    total_debit: Decimal
    total_credit: Decimal


def _filtre_ecritures(
    stmt: Select,
    *,
    organisation_id: int,
    exercice_id: int,
    statuts: tuple[str, ...],
    date_debut: date | None,
    date_fin: date | None,
) -> Select:
    """Restriction commune à toutes les restitutions.

    `organisation_id` est répété ici bien que le scoping ORM l'applique déjà
    (cf. docstring du module, point 2).
    """
    stmt = stmt.where(
        ComptaEcriture.organisation_id == organisation_id,
        ComptaEcriture.exercice_id == exercice_id,
        ComptaEcriture.statut.in_(statuts),
    )
    # Jamais de fonction sur la colonne de date dans un filtre : le piège des
    # 22 s déjà rencontré dans ce projet (CAST(date AS date) désactivait l'index).
    if date_debut is not None:
        stmt = stmt.where(ComptaEcriture.date_ecriture >= date_debut)
    if date_fin is not None:
        stmt = stmt.where(ComptaEcriture.date_ecriture <= date_fin)
    return stmt


async def balance_generale(
    db: AsyncSession,
    *,
    organisation_id: int,
    exercice_id: int,
    date_debut: date | None = None,
    date_fin: date | None = None,
    inclure_brouillons: bool = False,
    comptes_mouvementes_uniquement: bool = True,
) -> Balance:
    """Balance générale : un compte par ligne, totaux débit/crédit et soldes."""
    stmt = (
        select(
            ComptaCompte.id,
            ComptaCompte.numero,
            ComptaCompte.libelle,
            ComptaCompte.nature,
            func.coalesce(func.sum(ComptaLigneEcriture.debit_tenue), 0).label("total_debit"),
            func.coalesce(func.sum(ComptaLigneEcriture.credit_tenue), 0).label("total_credit"),
        )
        .select_from(ComptaLigneEcriture)
        .join(ComptaEcriture, ComptaEcriture.id == ComptaLigneEcriture.ecriture_id)
        .join(ComptaCompte, ComptaCompte.id == ComptaLigneEcriture.compte_id)
        .where(ComptaLigneEcriture.organisation_id == organisation_id)
        .group_by(ComptaCompte.id, ComptaCompte.numero, ComptaCompte.libelle, ComptaCompte.nature)
        .order_by(ComptaCompte.numero)
    )
    stmt = _filtre_ecritures(
        stmt,
        organisation_id=organisation_id,
        exercice_id=exercice_id,
        statuts=_statuts(inclure_brouillons),
        date_debut=date_debut,
        date_fin=date_fin,
    )
    if comptes_mouvementes_uniquement:
        # Un compte sans mouvement n'apparaît pas : sur un plan de plusieurs
        # centaines de comptes, les lignes à zéro noieraient l'information.
        stmt = stmt.having(
            or_(
                func.sum(ComptaLigneEcriture.debit_tenue) != 0,
                func.sum(ComptaLigneEcriture.credit_tenue) != 0,
            )
        )

    res = await db.execute(stmt)
    lignes = [
        LigneBalance(
            compte_id=row.id,
            compte_numero=row.numero,
            compte_libelle=row.libelle,
            nature=row.nature,
            total_debit=_q(row.total_debit),
            total_credit=_q(row.total_credit),
        )
        for row in res.all()
    ]

    return Balance(
        lignes=lignes,
        total_debit=sum((l.total_debit for l in lignes), Decimal("0")),
        total_credit=sum((l.total_credit for l in lignes), Decimal("0")),
        total_solde_debiteur=sum((l.solde_debiteur for l in lignes), Decimal("0")),
        total_solde_crediteur=sum((l.solde_crediteur for l in lignes), Decimal("0")),
    )


def _encoder_curseur(date_ecriture: date, ligne_id: UUID) -> str:
    return f"{date_ecriture.isoformat()}|{ligne_id}"


def _decoder_curseur(curseur: str) -> tuple[date, UUID]:
    date_str, _, id_str = curseur.partition("|")
    return date.fromisoformat(date_str), UUID(id_str)


async def _cumul_mouvements(
    db: AsyncSession,
    *,
    organisation_id: int,
    exercice_id: int,
    compte_id: int,
    statuts: tuple[str, ...],
    date_debut: date | None,
    borne_curseur: tuple[date, UUID] | None = None,
) -> Decimal:
    """Somme algébrique (débit − crédit) des mouvements d'un compte.

    Sert deux besoins : le solde antérieur à la période demandée, et le cumul
    déjà écoulé avant la page courante — sans lequel le solde progressif d'une
    page 2 repartirait faussement de zéro.

    `date_fin` n'intervient jamais ici : borner la fin n'a de sens que pour les
    mouvements affichés, pas pour un cumul qui précède la position courante.
    """
    stmt = (
        select(
            func.coalesce(
                func.sum(ComptaLigneEcriture.debit_tenue - ComptaLigneEcriture.credit_tenue), 0
            )
        )
        .select_from(ComptaLigneEcriture)
        .join(ComptaEcriture, ComptaEcriture.id == ComptaLigneEcriture.ecriture_id)
        .where(
            ComptaLigneEcriture.organisation_id == organisation_id,
            ComptaLigneEcriture.compte_id == compte_id,
            ComptaEcriture.organisation_id == organisation_id,
            ComptaEcriture.exercice_id == exercice_id,
            ComptaEcriture.statut.in_(statuts),
        )
    )
    if borne_curseur is not None:
        # Cumul depuis le début de la période jusqu'à la position du curseur.
        curseur_date, curseur_id = borne_curseur
        if date_debut is not None:
            stmt = stmt.where(ComptaEcriture.date_ecriture >= date_debut)
        stmt = stmt.where(
            or_(
                ComptaEcriture.date_ecriture < curseur_date,
                and_(
                    ComptaEcriture.date_ecriture == curseur_date,
                    ComptaLigneEcriture.id <= curseur_id,
                ),
            )
        )
    elif date_debut is not None:
        # Solde antérieur : tout ce qui précède strictement la période.
        stmt = stmt.where(ComptaEcriture.date_ecriture < date_debut)
    else:
        return Decimal("0")

    res = await db.execute(stmt)
    return _q(res.scalar_one())


async def grand_livre(
    db: AsyncSession,
    *,
    organisation_id: int,
    exercice_id: int,
    compte_id: int,
    date_debut: date | None = None,
    date_fin: date | None = None,
    inclure_brouillons: bool = False,
    curseur: str | None = None,
    limite: int = 100,
) -> GrandLivre:
    """Grand Livre d'un compte : mouvements détaillés et solde progressif.

    Pagination **par curseur** (`date_ecriture`, `ligne_id`) et non par OFFSET :
    sur des centaines de milliers de lignes, l'OFFSET dégrade linéairement et
    peut sauter ou dupliquer des lignes si une écriture est validée entre deux
    pages.
    """
    compte = await db.get(ComptaCompte, compte_id)
    if compte is None or compte.organisation_id != organisation_id:
        raise ValueError("Compte comptable introuvable pour cette organisation.")

    statuts = _statuts(inclure_brouillons)
    borne = _decoder_curseur(curseur) if curseur else None

    solde_anterieur = await _cumul_mouvements(
        db, organisation_id=organisation_id, exercice_id=exercice_id, compte_id=compte_id,
        statuts=statuts, date_debut=date_debut,
    )
    cumul_avant_page = (
        await _cumul_mouvements(
            db, organisation_id=organisation_id, exercice_id=exercice_id, compte_id=compte_id,
            statuts=statuts, date_debut=date_debut, borne_curseur=borne,
        )
        if borne is not None
        else Decimal("0")
    )

    stmt = (
        select(
            ComptaLigneEcriture.id.label("ligne_id"),
            ComptaLigneEcriture.libelle.label("ligne_libelle"),
            ComptaLigneEcriture.debit_tenue,
            ComptaLigneEcriture.credit_tenue,
            ComptaEcriture.id.label("ecriture_id"),
            ComptaEcriture.numero,
            ComptaEcriture.date_ecriture,
            ComptaEcriture.libelle.label("ecriture_libelle"),
            ComptaEcriture.reference_piece,
            ComptaEcriture.statut,
            ComptaJournal.code.label("journal_code"),
        )
        .select_from(ComptaLigneEcriture)
        .join(ComptaEcriture, ComptaEcriture.id == ComptaLigneEcriture.ecriture_id)
        .join(ComptaJournal, ComptaJournal.id == ComptaEcriture.journal_id)
        .where(
            ComptaLigneEcriture.organisation_id == organisation_id,
            ComptaLigneEcriture.compte_id == compte_id,
        )
        .order_by(ComptaEcriture.date_ecriture, ComptaLigneEcriture.id)
        .limit(limite + 1)  # une ligne de plus : présence d'une page suivante
    )
    stmt = _filtre_ecritures(
        stmt,
        organisation_id=organisation_id,
        exercice_id=exercice_id,
        statuts=statuts,
        date_debut=date_debut,
        date_fin=date_fin,
    )
    if borne is not None:
        curseur_date, curseur_id = borne
        stmt = stmt.where(
            or_(
                ComptaEcriture.date_ecriture > curseur_date,
                and_(
                    ComptaEcriture.date_ecriture == curseur_date,
                    ComptaLigneEcriture.id > curseur_id,
                ),
            )
        )

    res = await db.execute(stmt)
    rows = res.all()
    page_suivante = len(rows) > limite
    rows = rows[:limite]

    solde = solde_anterieur + cumul_avant_page
    mouvements: list[MouvementGrandLivre] = []
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    for row in rows:
        debit = _q(row.debit_tenue)
        credit = _q(row.credit_tenue)
        solde += debit - credit
        total_debit += debit
        total_credit += credit
        mouvements.append(
            MouvementGrandLivre(
                ligne_id=row.ligne_id,
                ecriture_id=row.ecriture_id,
                numero=row.numero,
                date_ecriture=row.date_ecriture,
                journal_code=row.journal_code,
                libelle=row.ligne_libelle or row.ecriture_libelle,
                reference_piece=row.reference_piece,
                debit=debit,
                credit=credit,
                statut=row.statut,
                solde_cumule=solde,
            )
        )

    curseur_suivant = (
        _encoder_curseur(rows[-1].date_ecriture, rows[-1].ligne_id) if page_suivante and rows else None
    )

    return GrandLivre(
        compte_id=compte.id,
        compte_numero=compte.numero,
        compte_libelle=compte.libelle,
        solde_anterieur=solde_anterieur,
        mouvements=mouvements,
        total_debit_page=total_debit,
        total_credit_page=total_credit,
        solde_final_page=solde,
        curseur_suivant=curseur_suivant,
    )


async def livre_journal(
    db: AsyncSession,
    *,
    organisation_id: int,
    exercice_id: int,
    journal_id: int,
    date_debut: date | None = None,
    date_fin: date | None = None,
    inclure_brouillons: bool = False,
    limite: int = 200,
) -> LivreJournal:
    """Journal : écritures d'un journal sur une période, avec leurs totaux."""
    journal = await db.get(ComptaJournal, journal_id)
    if journal is None or journal.organisation_id != organisation_id:
        raise ValueError("Journal introuvable pour cette organisation.")

    stmt = (
        select(
            ComptaEcriture.id,
            ComptaEcriture.numero,
            ComptaEcriture.date_ecriture,
            ComptaEcriture.libelle,
            ComptaEcriture.statut,
            func.coalesce(func.sum(ComptaLigneEcriture.debit_tenue), 0).label("total_debit"),
            func.coalesce(func.sum(ComptaLigneEcriture.credit_tenue), 0).label("total_credit"),
        )
        .select_from(ComptaEcriture)
        .join(ComptaLigneEcriture, ComptaLigneEcriture.ecriture_id == ComptaEcriture.id)
        .where(
            ComptaEcriture.journal_id == journal_id,
            ComptaLigneEcriture.organisation_id == organisation_id,
        )
        .group_by(
            ComptaEcriture.id, ComptaEcriture.numero, ComptaEcriture.date_ecriture,
            ComptaEcriture.libelle, ComptaEcriture.statut,
        )
        .order_by(ComptaEcriture.date_ecriture, ComptaEcriture.numero)
        .limit(limite)
    )
    stmt = _filtre_ecritures(
        stmt,
        organisation_id=organisation_id,
        exercice_id=exercice_id,
        statuts=_statuts(inclure_brouillons),
        date_debut=date_debut,
        date_fin=date_fin,
    )

    res = await db.execute(stmt)
    ecritures = [
        EcritureJournal(
            ecriture_id=row.id,
            numero=row.numero,
            date_ecriture=row.date_ecriture,
            libelle=row.libelle,
            statut=row.statut,
            total_debit=_q(row.total_debit),
            total_credit=_q(row.total_credit),
        )
        for row in res.all()
    ]

    return LivreJournal(
        journal_id=journal.id,
        journal_code=journal.code,
        journal_libelle=journal.libelle,
        ecritures=ecritures,
        total_debit=sum((e.total_debit for e in ecritures), Decimal("0")),
        total_credit=sum((e.total_credit for e in ecritures), Decimal("0")),
    )
