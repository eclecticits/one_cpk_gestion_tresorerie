"""Exécution budgétaire sur une période.

`budget_postes.montant_engage` et `montant_paye` sont des cumuls à l'instant
présent : on ne peut pas les « filtrer » par dates. Ce que le budget a réalisé
entre deux dates se recalcule donc depuis les mouvements qui l'ont nourri.

Deux sources, dans cet ordre :

1. `mouvement_budget_imputations`, le registre des impacts budgétaires figés. Il
   porte le poste, le sens, le montant retenu par le budget et la répartition
   des recettes entre plusieurs postes. C'est la source exacte — mais elle ne
   commence qu'à sa mise en service (août 2026 en production), alors que les
   opérations, elles, remontent à l'ouverture de l'exercice.
2. Les opérations elles-mêmes, pour celles qu'aucune imputation active ne
   décrit. Sans ce repli, un rapport de janvier à mars sortirait à zéro alors
   que l'argent est bien passé.

La date retenue est celle de l'opération — le versement, le paiement, le retour
— et non celle de la saisie : un versement de janvier saisi en février compte
en janvier.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.encaissement import Encaissement
from app.models.mouvement_budget_imputation import MouvementBudgetImputation
from app.models.payment_history import PaymentHistory
from app.models.retour_caisse import RetourCaisse
from app.models.sortie_fonds import SortieFonds


IMPUTATION_ACTIVE = "ACTIVE"
PAYMENT_ACTIF = "ACTIF"


def bornes_periode(
    date_debut: date | None, date_fin: date | None
) -> tuple[datetime | None, datetime | None]:
    """Bornes incluses : le dernier jour demandé compte en entier."""
    debut = datetime.combine(date_debut, time.min, tzinfo=timezone.utc) if date_debut else None
    fin = datetime.combine(date_fin, time.max, tzinfo=timezone.utc) if date_fin else None
    if debut and fin and debut > fin:
        raise HTTPException(status_code=400, detail="date_debut doit précéder date_fin")
    return debut, fin


def valider_periode_exercice(annee: int, date_debut: date | None, date_fin: date | None) -> None:
    """Une période d'exécution appartient à son exercice.

    Le budget est voté pour une année : comparer un réalisé de février 2025 à la
    prévision de 2026 ne veut rien dire, et le prorata temporis n'aurait pas de
    dénominateur. Une borne hors de l'exercice est donc refusée plutôt que
    rognée en silence — l'agent doit savoir que ce qu'il a saisi n'est pas ce
    qu'il obtient.
    """
    for borne, libelle in ((date_debut, "date_debut"), (date_fin, "date_fin")):
        if borne is not None and borne.year != annee:
            raise HTTPException(
                status_code=400,
                detail=f"{libelle} doit tomber dans l'exercice {annee} : du 01/01/{annee} au 31/12/{annee}.",
            )


def part_ecoulee(annee: int, date_fin: date | None) -> Decimal:
    """Part de l'exercice écoulée à la date de fin, entre 0 et 1.

    L'exercice est l'année civile : un poste n'a pas de calendrier propre. Ce
    ratio sert au repère prorata temporis — la prévision ramenée aux jours
    passés —, seule façon de dire si un réalisé de 20 % au 20 mars est en avance
    ou en retard.
    """
    fin = date_fin or datetime.now(timezone.utc).date()
    if fin.year < annee:
        return Decimal("0")
    if fin.year > annee:
        return Decimal("1")
    jours_annee = date(annee, 12, 31).timetuple().tm_yday
    return Decimal(fin.timetuple().tm_yday) / Decimal(jours_annee)


def _borner(query: Select, colonne, date_debut: datetime | None, date_fin: datetime | None) -> Select:
    """Bornes incluses : une période se lit comme on la dit, du premier au dernier jour."""
    if date_debut is not None:
        query = query.where(colonne >= date_debut)
    if date_fin is not None:
        query = query.where(colonne <= date_fin)
    return query


def _encaissement_retenu():
    return (
        Encaissement.est_proforma.is_(False),
        Encaissement.is_deleted.is_(False),
        or_(
            Encaissement.statut_operation.is_(None),
            Encaissement.statut_operation == "ACTIVE",
        ),
    )


def _sortie_retenue():
    return (
        or_(SortieFonds.statut.is_(None), func.upper(SortieFonds.statut) == "VALIDE"),
    )


def _cumuler(cible: dict[int, Decimal], rows, *, signe: int = 1) -> None:
    for poste_id, montant in rows:
        if poste_id is None:
            continue
        cible[int(poste_id)] = cible.get(int(poste_id), Decimal("0")) + signe * Decimal(montant or 0)


async def _recettes_du_registre(
    db: AsyncSession,
    *,
    organisation_id: int,
    date_debut: datetime | None,
    date_fin: datetime | None,
    service_id: int | None,
) -> dict[int, Decimal]:
    m = MouvementBudgetImputation
    # La date vit sur l'opération, jamais sur l'imputation : `created_at` du
    # registre est l'heure de la saisie.
    date_operation = func.coalesce(
        PaymentHistory.date_paiement,
        Encaissement.date_paiement,
        Encaissement.date_encaissement,
        m.created_at,
    )
    query = (
        select(m.budget_poste_id, func.coalesce(func.sum(m.montant_budget), 0))
        .select_from(m)
        .outerjoin(PaymentHistory, PaymentHistory.id == m.payment_history_id)
        .outerjoin(
            Encaissement,
            Encaissement.id == func.coalesce(m.encaissement_id, PaymentHistory.encaissement_id),
        )
        .where(
            m.organisation_id == organisation_id,
            m.statut == IMPUTATION_ACTIVE,
            m.sens == "RECETTE_REALISEE",
        )
        .group_by(m.budget_poste_id)
    )
    if service_id is not None:
        query = query.where(Encaissement.service_id == service_id)
    query = _borner(query, date_operation, date_debut, date_fin)
    return {int(r[0]): Decimal(r[1] or 0) for r in (await db.execute(query)).all() if r[0]}


async def _recettes_sans_registre(
    db: AsyncSession,
    *,
    organisation_id: int,
    date_debut: datetime | None,
    date_fin: datetime | None,
    service_id: int | None,
) -> dict[int, Decimal]:
    """Versements — et notes anciennes sans versement — qu'aucune imputation ne décrit."""
    m = MouvementBudgetImputation
    totaux: dict[int, Decimal] = {}

    versement_impute = (
        select(m.id)
        .where(
            m.payment_history_id == PaymentHistory.id,
            m.statut == IMPUTATION_ACTIVE,
        )
        .exists()
    )
    date_versement = func.coalesce(PaymentHistory.date_paiement, PaymentHistory.created_at)
    versements = (
        select(
            Encaissement.budget_poste_id,
            func.coalesce(func.sum(PaymentHistory.montant), 0),
        )
        .join(Encaissement, Encaissement.id == PaymentHistory.encaissement_id)
        .where(
            PaymentHistory.organisation_id == organisation_id,
            PaymentHistory.statut == PAYMENT_ACTIF,
            Encaissement.budget_poste_id.is_not(None),
            ~versement_impute,
            *_encaissement_retenu(),
        )
        .group_by(Encaissement.budget_poste_id)
    )
    if service_id is not None:
        versements = versements.where(Encaissement.service_id == service_id)
    versements = _borner(versements, date_versement, date_debut, date_fin)
    _cumuler(totaux, (await db.execute(versements)).all())

    # Notes payées d'avant l'historique des versements : leur montant ne vit que
    # sur l'encaissement. Le repli ne vaut que pour les notes SANS aucune ligne
    # d'historique — statut compris : dès qu'un versement existe, fût-il annulé,
    # c'est lui qui fait foi, et reprendre l'en-tête ressusciterait le montant
    # qu'une annulation vient d'effacer.
    sans_versement = (
        ~select(PaymentHistory.id)
        .where(PaymentHistory.encaissement_id == Encaissement.id)
        .exists()
    )
    note_imputee = (
        select(m.id)
        .where(m.encaissement_id == Encaissement.id, m.statut == IMPUTATION_ACTIVE)
        .exists()
    )
    date_note = func.coalesce(Encaissement.date_paiement, Encaissement.date_encaissement)
    notes = (
        select(
            Encaissement.budget_poste_id,
            func.coalesce(func.sum(func.coalesce(Encaissement.montant_paye, 0)), 0),
        )
        .where(
            Encaissement.organisation_id == organisation_id,
            Encaissement.budget_poste_id.is_not(None),
            func.coalesce(Encaissement.montant_paye, 0) > 0,
            sans_versement,
            ~note_imputee,
            *_encaissement_retenu(),
        )
        .group_by(Encaissement.budget_poste_id)
    )
    if service_id is not None:
        notes = notes.where(Encaissement.service_id == service_id)
    notes = _borner(notes, date_note, date_debut, date_fin)
    _cumuler(totaux, (await db.execute(notes)).all())
    return totaux


async def _depenses_du_registre(
    db: AsyncSession,
    *,
    organisation_id: int,
    date_debut: datetime | None,
    date_fin: datetime | None,
    service_id: int | None,
) -> dict[int, Decimal]:
    m = MouvementBudgetImputation
    totaux: dict[int, Decimal] = {}

    date_sortie = func.coalesce(SortieFonds.date_paiement, SortieFonds.created_at, m.created_at)
    payees = (
        select(m.budget_poste_id, func.coalesce(func.sum(m.montant_budget), 0))
        .select_from(m)
        .outerjoin(SortieFonds, SortieFonds.id == m.sortie_fonds_id)
        .where(
            m.organisation_id == organisation_id,
            m.statut == IMPUTATION_ACTIVE,
            m.sens == "DEPENSE_PAYEE",
        )
        .group_by(m.budget_poste_id)
    )
    if service_id is not None:
        payees = payees.where(SortieFonds.service_id == service_id)
    payees = _borner(payees, date_sortie, date_debut, date_fin)
    _cumuler(totaux, (await db.execute(payees)).all())

    # Un retour rend du crédit au poste : il se retranche de la dépense.
    date_retour = func.coalesce(RetourCaisse.date_retour, m.created_at)
    retours = (
        select(m.budget_poste_id, func.coalesce(func.sum(m.montant_budget), 0))
        .select_from(m)
        .outerjoin(RetourCaisse, RetourCaisse.id == m.retour_caisse_id)
        .where(
            m.organisation_id == organisation_id,
            m.statut == IMPUTATION_ACTIVE,
            m.sens == "RETOUR_DEPENSE",
        )
        .group_by(m.budget_poste_id)
    )
    if service_id is not None:
        retours = retours.where(RetourCaisse.service_id == service_id)
    retours = _borner(retours, date_retour, date_debut, date_fin)
    _cumuler(totaux, (await db.execute(retours)).all(), signe=-1)
    return totaux


async def _depenses_sans_registre(
    db: AsyncSession,
    *,
    organisation_id: int,
    date_debut: datetime | None,
    date_fin: datetime | None,
    service_id: int | None,
) -> dict[int, Decimal]:
    m = MouvementBudgetImputation
    totaux: dict[int, Decimal] = {}

    sortie_imputee = (
        select(m.id)
        .where(m.sortie_fonds_id == SortieFonds.id, m.statut == IMPUTATION_ACTIVE)
        .exists()
    )
    date_sortie = func.coalesce(SortieFonds.date_paiement, SortieFonds.created_at)
    sorties = (
        select(
            SortieFonds.budget_poste_id,
            func.coalesce(func.sum(func.coalesce(SortieFonds.montant_paye, 0)), 0),
        )
        .where(
            SortieFonds.organisation_id == organisation_id,
            SortieFonds.budget_poste_id.is_not(None),
            ~sortie_imputee,
            *_sortie_retenue(),
        )
        .group_by(SortieFonds.budget_poste_id)
    )
    if service_id is not None:
        sorties = sorties.where(SortieFonds.service_id == service_id)
    sorties = _borner(sorties, date_sortie, date_debut, date_fin)
    _cumuler(totaux, (await db.execute(sorties)).all())

    retour_impute = (
        select(m.id)
        .where(m.retour_caisse_id == RetourCaisse.id, m.statut == IMPUTATION_ACTIVE)
        .exists()
    )
    retours = (
        select(
            RetourCaisse.budget_poste_id,
            func.coalesce(func.sum(func.coalesce(RetourCaisse.montant, 0)), 0),
        )
        .where(
            RetourCaisse.organisation_id == organisation_id,
            RetourCaisse.budget_poste_id.is_not(None),
            RetourCaisse.ajuste_budget.is_(True),
            func.upper(RetourCaisse.statut) == "VALIDE",
            ~retour_impute,
        )
        .group_by(RetourCaisse.budget_poste_id)
    )
    if service_id is not None:
        retours = retours.where(RetourCaisse.service_id == service_id)
    retours = _borner(retours, RetourCaisse.date_retour, date_debut, date_fin)
    _cumuler(totaux, (await db.execute(retours)).all(), signe=-1)
    return totaux


async def realise_par_poste(
    db: AsyncSession,
    *,
    organisation_id: int,
    date_debut: datetime | None,
    date_fin: datetime | None,
    service_id: int | None = None,
) -> dict[int, Decimal]:
    """Réalisé de chaque poste entre deux dates, recettes et dépenses confondues.

    Un poste de recette reçoit ce qui a été encaissé, un poste de dépense ce qui
    a été payé, net des retours. Les montants sont ceux que le budget retient —
    `montant_budget` du registre, à défaut le montant de l'opération, comme le
    font déjà les colonnes de l'écran.
    """
    totaux: dict[int, Decimal] = {}
    for source in (
        _recettes_du_registre,
        _recettes_sans_registre,
        _depenses_du_registre,
        _depenses_sans_registre,
    ):
        partiel = await source(
            db,
            organisation_id=organisation_id,
            date_debut=date_debut,
            date_fin=date_fin,
            service_id=service_id,
        )
        for poste_id, montant in partiel.items():
            totaux[poste_id] = totaux.get(poste_id, Decimal("0")) + montant
    # Un retour peut dépasser la dépense de la période : le poste n'a pas pour
    # autant réalisé un montant négatif sur l'exercice.
    return {poste_id: max(Decimal("0"), montant) for poste_id, montant in totaux.items()}
