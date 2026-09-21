"""Exécution budgétaire entre deux dates.

Les colonnes du budget sont des cumuls à l'instant présent : elles ne savent pas
de quand elles datent. Tirer un rapport « du 01/01 au 20/03 » oblige donc à
recalculer le réalisé depuis les mouvements, et ces tests fixent ce que ce
recalcul doit rendre — bornes incluses, aucun double comptage entre le registre
des imputations et les opérations qu'il ne couvre pas encore.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.api.v1.endpoints.budget import list_budget_lines_tree
from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.caisse_centrale import CaisseCentrale
from app.models.encaissement import Encaissement
from app.models.mouvement_budget_imputation import MouvementBudgetImputation
from app.models.organisation import Organisation
from app.models.payment_history import PaymentHistory
from app.models.sortie_fonds import SortieFonds
from app.models.user import User

ANNEE = 2026
PREVU = Decimal("12000.00")


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


def _le(jour: int, mois: int) -> datetime:
    return datetime(ANNEE, mois, jour, 10, 0, tzinfo=timezone.utc)


async def _contexte(db):
    org = Organisation(nom="Budget période", slug=f"bp-{_suffix()}", is_active=True)
    db.add(org)
    await db.flush()
    user = User(
        id=uuid.uuid4(),
        email=f"{_suffix()}@example.com",
        nom="Contrôleur",
        prenom="Ada",
        role="admin",
        organisation_id=org.id,
        active=True,
    )
    exercice = BudgetExercice(organisation_id=org.id, annee=ANNEE, statut=StatutBudget.VOTE)
    db.add_all([user, exercice])
    await db.flush()
    recette = BudgetPoste(
        organisation_id=org.id,
        exercice_id=exercice.id,
        code=f"7{_suffix()[:5]}",
        libelle="Cotisations",
        type="RECETTE",
        active=True,
        montant_prevu=PREVU,
        montant_engage=Decimal("0"),
        montant_paye=Decimal("0"),
    )
    depense = BudgetPoste(
        organisation_id=org.id,
        exercice_id=exercice.id,
        code=f"6{_suffix()[:5]}",
        libelle="Fournitures",
        type="DEPENSE",
        active=True,
        montant_prevu=PREVU,
        montant_engage=Decimal("0"),
        montant_paye=Decimal("0"),
    )
    db.add_all([recette, depense])
    db.add(CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("0"), est_ouverte=True))
    await db.flush()
    return org, user, recette, depense


def _note(org, user, poste, montant: Decimal, quand: datetime) -> Encaissement:
    return Encaissement(
        organisation_id=org.id,
        numero_recu=f"ND-{_suffix()}",
        type_client="personne_physique",
        client_nom="Membre",
        libelle="Cotisation",
        montant=montant,
        montant_total=montant,
        montant_paye=montant,
        montant_percu=montant,
        devise_perception="USD",
        taux_change_applique=Decimal("1"),
        canal="CAISSE",
        mode_paiement="cash",
        statut_paiement="complet",
        budget_poste_id=poste.id,
        date_encaissement=quand,
        date_paiement=quand,
        created_by=user.id,
    )


def _versement(org, note, montant: Decimal, quand: datetime) -> PaymentHistory:
    return PaymentHistory(
        organisation_id=org.id,
        encaissement_id=note.id,
        montant=montant,
        devise="USD",
        canal="CAISSE",
        mode_paiement="cash",
        date_paiement=quand,
        statut="ACTIF",
    )


def _sortie(org, user, poste, montant: Decimal, quand: datetime) -> SortieFonds:
    return SortieFonds(
        organisation_id=org.id,
        type_sortie="depense",
        montant_paye=montant,
        mode_paiement="cash",
        devise="USD",
        canal="CAISSE",
        motif="Achat fournitures",
        beneficiaire="Fournisseur",
        statut="VALIDE",
        budget_poste_id=poste.id,
        date_paiement=quand,
        created_by=user.id,
    )


async def _lignes(db, org, user, *, debut: date | None = None, fin: date | None = None) -> dict[str, dict]:
    reponse = await list_budget_lines_tree(
        annee=ANNEE,
        type=None,
        active=None,
        service_id=None,
        date_debut=debut,
        date_fin=fin,
        user=user,
        tenant_id=org.id,
        db=db,
    )
    return {ligne.code: ligne for ligne in reponse.lignes}


@pytest.mark.asyncio
async def test_la_periode_ne_retient_que_les_mouvements_qui_y_tombent(db_session):
    """Le cas d'usage : du 01/01 au 20/03, puis un mois seul."""
    org, user, recette, depense = await _contexte(db_session)
    janvier = _note(org, user, recette, Decimal("400"), _le(15, 1))
    mars = _note(org, user, recette, Decimal("600"), _le(10, 3))
    avril = _note(org, user, recette, Decimal("900"), _le(5, 4))
    db_session.add_all([janvier, mars, avril])
    await db_session.flush()
    db_session.add_all(
        [
            _versement(org, janvier, Decimal("400"), _le(15, 1)),
            _versement(org, mars, Decimal("600"), _le(10, 3)),
            _versement(org, avril, Decimal("900"), _le(5, 4)),
            _sortie(org, user, depense, Decimal("250"), _le(20, 2)),
            _sortie(org, user, depense, Decimal("700"), _le(2, 4)),
        ]
    )
    await db_session.commit()

    lignes = await _lignes(db_session, org, user, debut=date(ANNEE, 1, 1), fin=date(ANNEE, 3, 20))
    assert lignes[recette.code].montant_paye == Decimal("1000.00")
    assert lignes[depense.code].montant_paye == Decimal("250.00")

    # Février seul : le versement de janvier et celui de mars sortent du cadre.
    lignes = await _lignes(db_session, org, user, debut=date(ANNEE, 2, 1), fin=date(ANNEE, 2, 28))
    assert lignes[recette.code].montant_paye == Decimal("0.00")
    assert lignes[depense.code].montant_paye == Decimal("250.00")
    # Le cumul, lui, part de l'ouverture de l'exercice : janvier y est.
    assert lignes[recette.code].montant_paye_cumule == Decimal("400.00")


@pytest.mark.asyncio
async def test_les_bornes_sont_incluses(db_session):
    org, user, recette, _depense = await _contexte(db_session)
    note = _note(org, user, recette, Decimal("300"), _le(20, 3))
    db_session.add(note)
    await db_session.flush()
    db_session.add(_versement(org, note, Decimal("300"), _le(20, 3)))
    await db_session.commit()

    lignes = await _lignes(db_session, org, user, debut=date(ANNEE, 1, 1), fin=date(ANNEE, 3, 20))
    assert lignes[recette.code].montant_paye == Decimal("300.00")

    lignes = await _lignes(db_session, org, user, debut=date(ANNEE, 1, 1), fin=date(ANNEE, 3, 19))
    assert lignes[recette.code].montant_paye == Decimal("0.00")


@pytest.mark.asyncio
async def test_le_registre_prime_et_ne_double_pas_l_operation(db_session):
    """Un versement imputé est compté une fois, par son imputation."""
    org, user, recette, _depense = await _contexte(db_session)
    note = _note(org, user, recette, Decimal("500"), _le(12, 2))
    db_session.add(note)
    await db_session.flush()
    versement = _versement(org, note, Decimal("500"), _le(12, 2))
    db_session.add(versement)
    await db_session.flush()
    db_session.add(
        MouvementBudgetImputation(
            organisation_id=org.id,
            payment_history_id=versement.id,
            budget_poste_id=recette.id,
            sens="RECETTE_REALISEE",
            montant_mouvement=Decimal("500"),
            devise_mouvement="USD",
            montant_budget=Decimal("500"),
            statut="ACTIVE",
        )
    )
    await db_session.commit()

    lignes = await _lignes(db_session, org, user, debut=date(ANNEE, 1, 1), fin=date(ANNEE, 3, 20))
    assert lignes[recette.code].montant_paye == Decimal("500.00")


@pytest.mark.asyncio
async def test_une_imputation_annulee_ne_compte_plus(db_session):
    org, user, recette, _depense = await _contexte(db_session)
    note = _note(org, user, recette, Decimal("500"), _le(12, 2))
    db_session.add(note)
    await db_session.flush()
    versement = _versement(org, note, Decimal("500"), _le(12, 2))
    versement.statut = "ANNULE"
    db_session.add(versement)
    await db_session.flush()
    db_session.add(
        MouvementBudgetImputation(
            organisation_id=org.id,
            payment_history_id=versement.id,
            budget_poste_id=recette.id,
            sens="RECETTE_REALISEE",
            montant_mouvement=Decimal("500"),
            devise_mouvement="USD",
            montant_budget=Decimal("500"),
            statut="ANNULEE",
        )
    )
    await db_session.commit()

    lignes = await _lignes(db_session, org, user, debut=date(ANNEE, 1, 1), fin=date(ANNEE, 3, 20))
    assert lignes[recette.code].montant_paye == Decimal("0.00")


@pytest.mark.asyncio
async def test_la_prevision_se_ramene_aux_jours_ecoules(db_session):
    """Prorata temporis : 12 000 sur l'année, 79 jours au 20 mars."""
    org, user, recette, _depense = await _contexte(db_session)
    await db_session.commit()

    lignes = await _lignes(db_session, org, user, debut=date(ANNEE, 1, 1), fin=date(ANNEE, 3, 20))
    attendu = (PREVU * Decimal(79) / Decimal(365)).quantize(Decimal("0.01"))
    assert lignes[recette.code].montant_prevu_a_date == attendu
    assert lignes[recette.code].montant_prevu == PREVU


@pytest.mark.asyncio
async def test_sans_periode_rien_ne_change(db_session):
    """L'écran sans dates garde exactement ses montants d'avant."""
    org, user, recette, depense = await _contexte(db_session)
    note = _note(org, user, recette, Decimal("500"), _le(12, 2))
    db_session.add(note)
    await db_session.flush()
    db_session.add(_versement(org, note, Decimal("500"), _le(12, 2)))
    depense.montant_paye = Decimal("250.00")
    await db_session.commit()

    lignes = await _lignes(db_session, org, user)
    assert lignes[recette.code].montant_paye == Decimal("500.00")
    assert lignes[depense.code].montant_paye == Decimal("250.00")
    assert lignes[recette.code].montant_paye_cumule == lignes[recette.code].montant_paye
    assert lignes[depense.code].montant_prevu_a_date == PREVU


@pytest.mark.asyncio
async def test_le_classeur_excel_sort_les_memes_chiffres_que_l_ecran(db_session):
    """Un rapport tiré en Excel doit dire ce que l'écran affiche, à la période près."""
    from app.api.v1.endpoints.exports import construire_classeur_budget

    org, user, recette, depense = await _contexte(db_session)
    janvier = _note(org, user, recette, Decimal("400"), _le(15, 1))
    avril = _note(org, user, recette, Decimal("900"), _le(5, 4))
    db_session.add_all([janvier, avril])
    await db_session.flush()
    db_session.add_all(
        [
            _versement(org, janvier, Decimal("400"), _le(15, 1)),
            _versement(org, avril, Decimal("900"), _le(5, 4)),
            _sortie(org, user, depense, Decimal("250"), _le(20, 2)),
            _sortie(org, user, depense, Decimal("700"), _le(2, 4)),
        ]
    )
    await db_session.commit()

    wb, _nom = await construire_classeur_budget(
        db_session,
        org.id,
        annee=ANNEE,
        date_debut=f"{ANNEE}-01-01",
        date_fin=f"{ANNEE}-03-20",
    )
    ws = wb.active
    COL_CODE, COL_REALISE = 1, 10
    realise = {
        ws.cell(row=ligne, column=COL_CODE).value: ws.cell(row=ligne, column=COL_REALISE).value
        for ligne in range(8, ws.max_row + 1)
    }
    assert realise[recette.code] == 400.0
    assert realise[depense.code] == 250.0
    # Et la bande de titre dit sur quoi porte le classeur.
    assert "Période : 01/01/2026 au 20/03/2026" in str(ws["A3"].value)
