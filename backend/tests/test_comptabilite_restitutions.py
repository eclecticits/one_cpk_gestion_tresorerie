"""Restitutions comptables (Lot 4) — Grand Livre, Journal, Balance.

Ces états sont le premier moyen de VÉRIFIER que le moteur de génération
produit des écritures justes : jusqu'ici on ne pouvait que lister des
écritures une par une.

Points sensibles couverts :
- seules les écritures validées entrent dans les états (un brouillon ou une
  écriture annulée fausserait tout) ;
- la balance reste équilibrée et les soldes respectent le sens des comptes ;
- la pagination par curseur du Grand Livre ne saute ni ne duplique de ligne,
  et le solde progressif reste juste d'une page à l'autre ;
- le filtrage par date borne les mouvements sans fausser le solde antérieur ;
- aucune fuite inter-organisations (contrainte C2 : filtre explicite).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.organisation import Organisation
from app.models.user import User
from app.modules.comptabilite.models import (
    ComptaCompte,
    ComptaEcriture,
    ComptaExercice,
    ComptaJournal,
    ComptaLigneEcriture,
    ComptaSociete,
)
from app.modules.comptabilite.services.ecriture_service import (
    contrepasser_ecriture,
    valider_ecriture,
)
from app.modules.comptabilite.services.reporting_service import (
    balance_generale,
    grand_livre,
    livre_journal,
)
from app.modules.comptabilite.services.setup_service import setup_comptabilite


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


async def _org(db) -> Organisation:
    org = Organisation(nom="Resti Test", slug=f"resti-{_suffix()}", is_active=True)
    db.add(org)
    await db.flush()
    return org


async def _admin(db, org) -> User:
    user = User(id=uuid.uuid4(), email=f"a{_suffix()}@ex.com", role="admin", organisation_id=org.id)
    db.add(user)
    await db.flush()
    return user


async def _activer(db, org) -> tuple[ComptaSociete, ComptaExercice]:
    await setup_comptabilite(
        db, organisation_id=org.id, organisation_nom=org.nom, type_referentiel="SYSCEBNL",
        exercice_date_debut=date(2026, 1, 1), exercice_date_fin=date(2026, 12, 31),
    )
    await db.flush()
    societe = (
        await db.execute(
            select(ComptaSociete).where(
                ComptaSociete.organisation_id == org.id, ComptaSociete.is_default.is_(True)
            )
        )
    ).scalar_one()
    exercice = (
        await db.execute(
            select(ComptaExercice).where(ComptaExercice.organisation_id == org.id)
        )
    ).scalar_one()
    return societe, exercice


async def _compte(db, org, numero: str) -> ComptaCompte:
    return (
        await db.execute(
            select(ComptaCompte).where(
                ComptaCompte.organisation_id == org.id, ComptaCompte.numero == numero
            )
        )
    ).scalar_one()


async def _journal(db, org, code: str) -> ComptaJournal:
    return (
        await db.execute(
            select(ComptaJournal).where(
                ComptaJournal.organisation_id == org.id, ComptaJournal.code == code
            )
        )
    ).scalar_one()


async def _ecriture(
    db, org, societe, exercice, journal, *, jour: date, montant: Decimal,
    compte_debit: ComptaCompte, compte_credit: ComptaCompte, libelle="Opération",
    valider=True, user=None,
) -> ComptaEcriture:
    ecriture = ComptaEcriture(
        organisation_id=org.id, societe_id=societe.id, exercice_id=exercice.id,
        journal_id=journal.id, date_ecriture=jour, libelle=libelle, statut="BROUILLON",
        devise="USD",
    )
    db.add(ecriture)
    await db.flush()
    db.add_all([
        ComptaLigneEcriture(
            organisation_id=org.id, societe_id=societe.id, ecriture_id=ecriture.id,
            compte_id=compte_debit.id, ordre=1, libelle=libelle,
            debit=montant, credit=Decimal("0"), devise="USD",
            debit_tenue=montant, credit_tenue=Decimal("0"),
        ),
        ComptaLigneEcriture(
            organisation_id=org.id, societe_id=societe.id, ecriture_id=ecriture.id,
            compte_id=compte_credit.id, ordre=2, libelle=libelle,
            debit=Decimal("0"), credit=montant, devise="USD",
            debit_tenue=Decimal("0"), credit_tenue=montant,
        ),
    ])
    await db.flush()
    if valider:
        await valider_ecriture(
            db, ecriture_id=ecriture.id, organisation_id=org.id,
            user_id=user.id if user else None,
        )
    return ecriture


# ── Balance ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_balance_equilibree_et_soldes_par_sens(db_session):
    db = db_session
    org = await _org(db)
    societe, exercice = await _activer(db, org)
    user = await _admin(db, org)
    caisse = await _compte(db, org, "571")
    charge = await _compte(db, org, "605")
    produit = await _compte(db, org, "758")
    journal = await _journal(db, org, "CA")

    # Encaissement 1000 puis dépense 300.
    await _ecriture(db, org, societe, exercice, journal, jour=date(2026, 3, 1),
                    montant=Decimal("1000"), compte_debit=caisse, compte_credit=produit, user=user)
    await _ecriture(db, org, societe, exercice, journal, jour=date(2026, 3, 5),
                    montant=Decimal("300"), compte_debit=charge, compte_credit=caisse, user=user)

    balance = await balance_generale(db, organisation_id=org.id, exercice_id=exercice.id)

    assert balance.equilibree
    assert balance.total_debit == balance.total_credit == Decimal("1300")

    par_compte = {l.compte_numero: l for l in balance.lignes}
    # La caisse est un actif : 1000 encaissés − 300 décaissés = 700 débiteurs.
    assert par_compte["571"].solde_debiteur == Decimal("700")
    assert par_compte["571"].solde_crediteur == Decimal("0")
    assert par_compte["605"].solde_debiteur == Decimal("300")
    assert par_compte["758"].solde_crediteur == Decimal("1000")
    # Les soldes se compensent aussi globalement.
    assert balance.total_solde_debiteur == balance.total_solde_crediteur == Decimal("1000")


@pytest.mark.asyncio
async def test_balance_ignore_brouillons_et_ecritures_annulees(db_session):
    """Le point le plus important de tout le lot : un état qui inclurait un
    brouillon ou une écriture contre-passée serait faux."""
    db = db_session
    org = await _org(db)
    societe, exercice = await _activer(db, org)
    user = await _admin(db, org)
    caisse = await _compte(db, org, "571")
    produit = await _compte(db, org, "758")
    journal = await _journal(db, org, "CA")

    await _ecriture(db, org, societe, exercice, journal, jour=date(2026, 3, 1),
                    montant=Decimal("1000"), compte_debit=caisse, compte_credit=produit, user=user)
    # Un brouillon jamais validé.
    await _ecriture(db, org, societe, exercice, journal, jour=date(2026, 3, 2),
                    montant=Decimal("500"), compte_debit=caisse, compte_credit=produit,
                    valider=False, user=user)
    # Une écriture validée puis contre-passée : l'origine passe ANNULEE et la
    # contre-passation reste au brouillon.
    annulee = await _ecriture(db, org, societe, exercice, journal, jour=date(2026, 3, 3),
                              montant=Decimal("400"), compte_debit=caisse, compte_credit=produit,
                              user=user)
    await contrepasser_ecriture(
        db, ecriture_id=annulee.id, organisation_id=org.id, user_id=user.id, motif="Erreur"
    )

    balance = await balance_generale(db, organisation_id=org.id, exercice_id=exercice.id)
    par_compte = {l.compte_numero: l for l in balance.lignes}
    assert par_compte["571"].solde_debiteur == Decimal("1000")
    assert balance.equilibree

    # En mode simulation, les brouillons apparaissent (1000 + 500 + 400 de
    # contre-passation créditrice).
    simulation = await balance_generale(
        db, organisation_id=org.id, exercice_id=exercice.id, inclure_brouillons=True
    )
    par_compte_sim = {l.compte_numero: l for l in simulation.lignes}
    assert par_compte_sim["571"].solde_debiteur == Decimal("1100")
    assert simulation.equilibree


@pytest.mark.asyncio
async def test_balance_bornee_par_dates(db_session):
    db = db_session
    org = await _org(db)
    societe, exercice = await _activer(db, org)
    user = await _admin(db, org)
    caisse = await _compte(db, org, "571")
    produit = await _compte(db, org, "758")
    journal = await _journal(db, org, "CA")

    for jour, montant in ((date(2026, 1, 10), "100"), (date(2026, 6, 10), "200"), (date(2026, 9, 10), "400")):
        await _ecriture(db, org, societe, exercice, journal, jour=jour, montant=Decimal(montant),
                        compte_debit=caisse, compte_credit=produit, user=user)

    balance = await balance_generale(
        db, organisation_id=org.id, exercice_id=exercice.id,
        date_debut=date(2026, 5, 1), date_fin=date(2026, 8, 31),
    )
    par_compte = {l.compte_numero: l for l in balance.lignes}
    assert par_compte["571"].total_debit == Decimal("200")


@pytest.mark.asyncio
async def test_balance_ne_voit_pas_les_ecritures_d_une_autre_organisation(db_session):
    """Contrainte C2 : le filtre organisation_id doit être explicite sur toute
    requête de restitution."""
    db = db_session
    org_a = await _org(db)
    org_b = await _org(db)
    societe_a, exercice_a = await _activer(db, org_a)
    societe_b, exercice_b = await _activer(db, org_b)
    user_a = await _admin(db, org_a)
    user_b = await _admin(db, org_b)

    await _ecriture(db, org_a, societe_a, exercice_a, await _journal(db, org_a, "CA"),
                    jour=date(2026, 3, 1), montant=Decimal("1000"),
                    compte_debit=await _compte(db, org_a, "571"),
                    compte_credit=await _compte(db, org_a, "758"), user=user_a)
    await _ecriture(db, org_b, societe_b, exercice_b, await _journal(db, org_b, "CA"),
                    jour=date(2026, 3, 1), montant=Decimal("7777"),
                    compte_debit=await _compte(db, org_b, "571"),
                    compte_credit=await _compte(db, org_b, "758"), user=user_b)

    balance_a = await balance_generale(db, organisation_id=org_a.id, exercice_id=exercice_a.id)
    assert balance_a.total_debit == Decimal("1000")


# ── Grand Livre ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_grand_livre_solde_progressif(db_session):
    db = db_session
    org = await _org(db)
    societe, exercice = await _activer(db, org)
    user = await _admin(db, org)
    caisse = await _compte(db, org, "571")
    charge = await _compte(db, org, "605")
    produit = await _compte(db, org, "758")
    journal = await _journal(db, org, "CA")

    await _ecriture(db, org, societe, exercice, journal, jour=date(2026, 2, 1),
                    montant=Decimal("1000"), compte_debit=caisse, compte_credit=produit,
                    libelle="Cotisations", user=user)
    await _ecriture(db, org, societe, exercice, journal, jour=date(2026, 2, 10),
                    montant=Decimal("250"), compte_debit=charge, compte_credit=caisse,
                    libelle="Fournitures", user=user)

    livre = await grand_livre(
        db, organisation_id=org.id, exercice_id=exercice.id, compte_id=caisse.id
    )

    assert livre.compte_numero == "571"
    assert livre.solde_anterieur == Decimal("0")
    assert [m.solde_cumule for m in livre.mouvements] == [Decimal("1000"), Decimal("750")]
    assert livre.total_debit_page == Decimal("1000")
    assert livre.total_credit_page == Decimal("250")
    assert livre.solde_final_page == Decimal("750")
    assert livre.curseur_suivant is None
    # Le journal d'origine doit être lisible : c'est ce qui permet le
    # drill-down vers l'écriture depuis l'état.
    assert all(m.journal_code == "CA" for m in livre.mouvements)


@pytest.mark.asyncio
async def test_grand_livre_pagination_par_curseur_ne_perd_aucune_ligne(db_session):
    """La pagination doit couvrir exactement l'ensemble des mouvements, et le
    solde progressif ne doit pas repartir de zéro à la page suivante."""
    db = db_session
    org = await _org(db)
    societe, exercice = await _activer(db, org)
    user = await _admin(db, org)
    caisse = await _compte(db, org, "571")
    produit = await _compte(db, org, "758")
    journal = await _journal(db, org, "CA")

    for jour in range(1, 8):
        await _ecriture(db, org, societe, exercice, journal, jour=date(2026, 4, jour),
                        montant=Decimal("100"), compte_debit=caisse, compte_credit=produit,
                        user=user)

    vus: list[str] = []
    soldes: list[Decimal] = []
    curseur = None
    pages = 0
    while True:
        page = await grand_livre(
            db, organisation_id=org.id, exercice_id=exercice.id, compte_id=caisse.id,
            curseur=curseur, limite=3,
        )
        vus.extend(str(m.ligne_id) for m in page.mouvements)
        soldes.extend(m.solde_cumule for m in page.mouvements)
        pages += 1
        curseur = page.curseur_suivant
        if curseur is None:
            break
        assert pages < 10, "pagination qui ne se termine pas"

    assert pages == 3  # 3 + 3 + 1
    assert len(vus) == 7
    assert len(set(vus)) == 7, "une ligne a été renvoyée deux fois"
    # Solde progressif continu d'une page à l'autre.
    assert soldes == [Decimal(100 * i) for i in range(1, 8)]


@pytest.mark.asyncio
async def test_grand_livre_solde_anterieur_hors_periode(db_session):
    """Borner la période ne doit pas faire disparaître l'antériorité : le
    solde de départ doit la refléter."""
    db = db_session
    org = await _org(db)
    societe, exercice = await _activer(db, org)
    user = await _admin(db, org)
    caisse = await _compte(db, org, "571")
    produit = await _compte(db, org, "758")
    journal = await _journal(db, org, "CA")

    await _ecriture(db, org, societe, exercice, journal, jour=date(2026, 1, 15),
                    montant=Decimal("500"), compte_debit=caisse, compte_credit=produit, user=user)
    await _ecriture(db, org, societe, exercice, journal, jour=date(2026, 6, 15),
                    montant=Decimal("200"), compte_debit=caisse, compte_credit=produit, user=user)

    livre = await grand_livre(
        db, organisation_id=org.id, exercice_id=exercice.id, compte_id=caisse.id,
        date_debut=date(2026, 6, 1), date_fin=date(2026, 6, 30),
    )
    assert livre.solde_anterieur == Decimal("500")
    assert len(livre.mouvements) == 1
    assert livre.mouvements[0].solde_cumule == Decimal("700")


@pytest.mark.asyncio
async def test_grand_livre_compte_d_une_autre_organisation_refuse(db_session):
    db = db_session
    org_a = await _org(db)
    org_b = await _org(db)
    _, exercice_a = await _activer(db, org_a)
    await _activer(db, org_b)
    compte_b = await _compte(db, org_b, "571")

    with pytest.raises(ValueError):
        await grand_livre(
            db, organisation_id=org_a.id, exercice_id=exercice_a.id, compte_id=compte_b.id
        )


# ── Journal ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_livre_journal_totaux_et_perimetre(db_session):
    db = db_session
    org = await _org(db)
    societe, exercice = await _activer(db, org)
    user = await _admin(db, org)
    caisse = await _compte(db, org, "571")
    produit = await _compte(db, org, "758")
    journal_caisse = await _journal(db, org, "CA")
    journal_od = await _journal(db, org, "OD")

    await _ecriture(db, org, societe, exercice, journal_caisse, jour=date(2026, 5, 1),
                    montant=Decimal("300"), compte_debit=caisse, compte_credit=produit, user=user)
    await _ecriture(db, org, societe, exercice, journal_caisse, jour=date(2026, 5, 2),
                    montant=Decimal("120"), compte_debit=caisse, compte_credit=produit, user=user)
    await _ecriture(db, org, societe, exercice, journal_od, jour=date(2026, 5, 3),
                    montant=Decimal("999"), compte_debit=caisse, compte_credit=produit, user=user)

    livre = await livre_journal(
        db, organisation_id=org.id, exercice_id=exercice.id, journal_id=journal_caisse.id
    )
    assert livre.journal_code == "CA"
    assert len(livre.ecritures) == 2
    assert livre.total_debit == livre.total_credit == Decimal("420")
    # Chaque écriture est équilibrée prise isolément.
    assert all(e.total_debit == e.total_credit for e in livre.ecritures)
    # Ordre chronologique.
    assert [e.date_ecriture for e in livre.ecritures] == [date(2026, 5, 1), date(2026, 5, 2)]


# ── API ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_utilise_le_dernier_exercice_par_defaut(db_session):
    """Les écrans s'ouvrent sans exercice choisi : le plus récent doit être
    retenu, sinon le comptable verrait un état vide sans comprendre pourquoi."""
    db = db_session
    org = await _org(db)
    societe, exercice_2026 = await _activer(db, org)
    user = await _admin(db, org)

    exercice_2025 = ComptaExercice(
        organisation_id=org.id, societe_id=societe.id, code="2025", libelle="Exercice 2025",
        date_debut=date(2025, 1, 1), date_fin=date(2025, 12, 31),
        referentiel_id=exercice_2026.referentiel_id, statut="CLOTURE",
    )
    db.add(exercice_2025)
    await db.flush()

    await _ecriture(db, org, societe, exercice_2026, await _journal(db, org, "CA"),
                    jour=date(2026, 3, 1), montant=Decimal("640"),
                    compte_debit=await _compte(db, org, "571"),
                    compte_credit=await _compte(db, org, "758"), user=user)

    from app.modules.comptabilite.routers.restitutions import get_balance

    out = await get_balance(tenant_id=org.id, db=db)
    assert out.exercice_id == exercice_2026.id
    assert out.devise_tenue == exercice_2026.devise_tenue
    assert out.total_debit == Decimal("640")
    assert out.equilibree is True


@pytest.mark.asyncio
async def test_api_journal_inconnu_renvoie_404(db_session):
    db = db_session
    org = await _org(db)
    await _activer(db, org)
    await db.flush()

    from fastapi import HTTPException

    from app.modules.comptabilite.routers.restitutions import get_journal

    with pytest.raises(HTTPException) as exc:
        await get_journal(journal_id=999999, tenant_id=org.id, db=db)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_api_sans_exercice_renvoie_404(db_session):
    """Organisation sans comptabilité activée : message clair plutôt qu'une
    erreur 500 opaque."""
    db = db_session
    org = await _org(db)
    await db.flush()

    from fastapi import HTTPException

    from app.modules.comptabilite.routers.restitutions import get_balance

    with pytest.raises(HTTPException) as exc:
        await get_balance(tenant_id=org.id, db=db)
    assert exc.value.status_code == 404
