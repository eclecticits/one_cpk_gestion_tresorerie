"""Validation en lot des écritures au brouillon.

Sans elle, le moteur de génération produit des brouillons qu'il faut valider
un par un : les états financiers restent vides et la clôture inatteignable.

Points vérifiés :
- les numéros de pièce suivent l'ordre CHRONOLOGIQUE, pas l'ordre de création ;
- une écriture refusée n'annule pas les autres, et son motif est rapporté ;
- la simulation ne fige rien, y compris les numéros consommés ;
- la limite est respectée et le reste signalé ;
- les filtres et l'isolation inter-organisations ;
- l'enchaînement complet : lot → états financiers renseignés → clôture possible.
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
from app.modules.comptabilite.services.cloture_service import (
    ClotureError,
    cloturer_exercice,
    determiner_resultat,
)
from app.modules.comptabilite.services.etats_financiers import calculer_etat
from app.modules.comptabilite.services.setup_service import setup_comptabilite
from app.modules.comptabilite.services.validation_lot import valider_lot


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


async def _org(db) -> Organisation:
    org = Organisation(nom="Lot Test", slug=f"lot-{_suffix()}", is_active=True)
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
        await db.execute(select(ComptaExercice).where(ComptaExercice.organisation_id == org.id))
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


async def _brouillon(
    db, org, societe, exercice, journal, *, jour: date,
    debit_compte: ComptaCompte, credit_compte: ComptaCompte,
    montant_debit: Decimal, montant_credit: Decimal | None = None, libelle="Brouillon",
) -> ComptaEcriture:
    """Crée une écriture au brouillon. `montant_credit` différent du débit
    permet de fabriquer une écriture déséquilibrée, refusée à la validation."""
    ecriture = ComptaEcriture(
        organisation_id=org.id, societe_id=societe.id, exercice_id=exercice.id,
        journal_id=journal.id, date_ecriture=jour, libelle=libelle, statut="BROUILLON",
        devise="USD",
    )
    db.add(ecriture)
    await db.flush()
    credit = montant_credit if montant_credit is not None else montant_debit
    db.add_all([
        ComptaLigneEcriture(
            organisation_id=org.id, societe_id=societe.id, ecriture_id=ecriture.id,
            compte_id=debit_compte.id, ordre=1, libelle=libelle,
            debit=montant_debit, credit=Decimal("0"), devise="USD",
            debit_tenue=montant_debit, credit_tenue=Decimal("0"),
        ),
        ComptaLigneEcriture(
            organisation_id=org.id, societe_id=societe.id, ecriture_id=ecriture.id,
            compte_id=credit_compte.id, ordre=2, libelle=libelle,
            debit=Decimal("0"), credit=credit, devise="USD",
            debit_tenue=Decimal("0"), credit_tenue=credit,
        ),
    ])
    await db.flush()
    return ecriture


# ── Numérotation ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_numerotation_suit_l_ordre_chronologique(db_session):
    """Les écritures sont créées dans le désordre : les numéros doivent
    néanmoins suivre les dates. Un journal dont la numérotation ne suit pas la
    chronologie est relevé par n'importe quel auditeur."""
    db = db_session
    org = await _org(db)
    societe, exercice = await _activer(db, org)
    user = await _admin(db, org)
    caisse = await _compte(db, org, "571")
    produit = await _compte(db, org, "70")
    journal = await _journal(db, org, "CA")

    mai = await _brouillon(db, org, societe, exercice, journal, jour=date(2026, 5, 10),
                           debit_compte=caisse, credit_compte=produit,
                           montant_debit=Decimal("300"), libelle="Mai")
    janvier = await _brouillon(db, org, societe, exercice, journal, jour=date(2026, 1, 20),
                               debit_compte=caisse, credit_compte=produit,
                               montant_debit=Decimal("100"), libelle="Janvier")
    mars = await _brouillon(db, org, societe, exercice, journal, jour=date(2026, 3, 15),
                            debit_compte=caisse, credit_compte=produit,
                            montant_debit=Decimal("200"), libelle="Mars")

    rapport = await valider_lot(
        db, organisation_id=org.id, exercice_id=exercice.id, simulation=False, user_id=user.id
    )
    assert rapport.validees == 3
    assert rapport.echecs == []

    for ecriture in (janvier, mars, mai):
        await db.refresh(ecriture)
    assert janvier.numero == "CA-2026-00001"
    assert mars.numero == "CA-2026-00002"
    assert mai.numero == "CA-2026-00003"


# ── Isolation des échecs ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_une_ecriture_refusee_n_annule_pas_les_autres(db_session):
    db = db_session
    org = await _org(db)
    societe, exercice = await _activer(db, org)
    user = await _admin(db, org)
    caisse = await _compte(db, org, "571")
    produit = await _compte(db, org, "70")
    journal = await _journal(db, org, "CA")

    bonne_1 = await _brouillon(db, org, societe, exercice, journal, jour=date(2026, 2, 1),
                               debit_compte=caisse, credit_compte=produit,
                               montant_debit=Decimal("100"), libelle="Correcte 1")
    # Déséquilibrée : refusée par les contrôles de validation.
    mauvaise = await _brouillon(db, org, societe, exercice, journal, jour=date(2026, 2, 2),
                                debit_compte=caisse, credit_compte=produit,
                                montant_debit=Decimal("100"), montant_credit=Decimal("90"),
                                libelle="Déséquilibrée")
    bonne_2 = await _brouillon(db, org, societe, exercice, journal, jour=date(2026, 2, 3),
                               debit_compte=caisse, credit_compte=produit,
                               montant_debit=Decimal("200"), libelle="Correcte 2")

    rapport = await valider_lot(
        db, organisation_id=org.id, exercice_id=exercice.id, simulation=False, user_id=user.id
    )

    assert rapport.total_examinees == 3
    assert rapport.validees == 2
    assert len(rapport.echecs) == 1
    echec = rapport.echecs[0]
    assert echec.ecriture_id == mauvaise.id
    assert "déséquilibrée" in echec.motif.lower()

    for ecriture in (bonne_1, bonne_2, mauvaise):
        await db.refresh(ecriture)
    assert bonne_1.statut == "VALIDEE"
    assert bonne_2.statut == "VALIDEE"
    assert mauvaise.statut == "BROUILLON"
    # La numérotation ne saute pas de numéro sur l'écriture refusée.
    assert bonne_1.numero == "CA-2026-00001"
    assert bonne_2.numero == "CA-2026-00002"


# ── Simulation ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_simulation_ne_fige_rien_ni_ne_consomme_de_numero(db_session):
    """La simulation doit être exactement le même traitement, annulé. Si elle
    consommait des numéros, le premier vrai lot commencerait à 3."""
    db = db_session
    org = await _org(db)
    societe, exercice = await _activer(db, org)
    user = await _admin(db, org)
    caisse = await _compte(db, org, "571")
    produit = await _compte(db, org, "70")
    journal = await _journal(db, org, "CA")

    a = await _brouillon(db, org, societe, exercice, journal, jour=date(2026, 2, 1),
                         debit_compte=caisse, credit_compte=produit, montant_debit=Decimal("100"))
    await _brouillon(db, org, societe, exercice, journal, jour=date(2026, 2, 2),
                     debit_compte=caisse, credit_compte=produit,
                     montant_debit=Decimal("100"), montant_credit=Decimal("50"))

    simulation = await valider_lot(
        db, organisation_id=org.id, exercice_id=exercice.id, simulation=True, user_id=user.id
    )
    assert simulation.simulation is True
    assert simulation.validees == 1
    assert len(simulation.echecs) == 1

    await db.refresh(a)
    assert a.statut == "BROUILLON"
    assert a.numero is None

    # Le lot réel repart bien du premier numéro.
    reel = await valider_lot(
        db, organisation_id=org.id, exercice_id=exercice.id, simulation=False, user_id=user.id
    )
    assert reel.validees == 1
    await db.refresh(a)
    assert a.numero == "CA-2026-00001"


# ── Filtres, limite, isolation ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_filtre_par_journal_et_operations_automatiques(db_session):
    db = db_session
    org = await _org(db)
    societe, exercice = await _activer(db, org)
    user = await _admin(db, org)
    caisse = await _compte(db, org, "571")
    produit = await _compte(db, org, "70")
    journal_ca = await _journal(db, org, "CA")
    journal_od = await _journal(db, org, "OD")

    en_caisse = await _brouillon(db, org, societe, exercice, journal_ca, jour=date(2026, 2, 1),
                                 debit_compte=caisse, credit_compte=produit,
                                 montant_debit=Decimal("100"))
    en_od = await _brouillon(db, org, societe, exercice, journal_od, jour=date(2026, 2, 2),
                             debit_compte=caisse, credit_compte=produit,
                             montant_debit=Decimal("200"))
    en_caisse.est_automatique = True
    await db.flush()

    rapport = await valider_lot(
        db, organisation_id=org.id, journal_id=journal_ca.id, simulation=False, user_id=user.id
    )
    assert rapport.validees == 1
    await db.refresh(en_od)
    assert en_od.statut == "BROUILLON"

    # Filtre « écritures générées automatiquement » : celle du journal CA est
    # déjà validée, il ne reste rien à traiter.
    rapport_auto = await valider_lot(
        db, organisation_id=org.id, automatiques_uniquement=True, simulation=True, user_id=user.id
    )
    assert rapport_auto.total_examinees == 0


@pytest.mark.asyncio
async def test_limite_respectee_et_reste_signale(db_session):
    db = db_session
    org = await _org(db)
    societe, exercice = await _activer(db, org)
    user = await _admin(db, org)
    caisse = await _compte(db, org, "571")
    produit = await _compte(db, org, "70")
    journal = await _journal(db, org, "CA")

    for jour in range(1, 6):
        await _brouillon(db, org, societe, exercice, journal, jour=date(2026, 4, jour),
                         debit_compte=caisse, credit_compte=produit, montant_debit=Decimal("10"))

    rapport = await valider_lot(
        db, organisation_id=org.id, exercice_id=exercice.id, limite=2,
        simulation=False, user_id=user.id,
    )
    assert rapport.total_examinees == 2
    assert rapport.validees == 2
    assert rapport.reste_a_traiter is True

    # Relance : reprend là où le lot s'est arrêté, les validées n'étant plus
    # des brouillons.
    suite = await valider_lot(
        db, organisation_id=org.id, exercice_id=exercice.id, limite=10,
        simulation=False, user_id=user.id,
    )
    assert suite.validees == 3
    assert suite.reste_a_traiter is False


@pytest.mark.asyncio
async def test_lot_ne_touche_pas_une_autre_organisation(db_session):
    db = db_session
    org_a = await _org(db)
    org_b = await _org(db)
    societe_a, exercice_a = await _activer(db, org_a)
    societe_b, exercice_b = await _activer(db, org_b)
    user_a = await _admin(db, org_a)

    brouillon_b = await _brouillon(
        db, org_b, societe_b, exercice_b, await _journal(db, org_b, "CA"), jour=date(2026, 2, 1),
        debit_compte=await _compte(db, org_b, "571"), credit_compte=await _compte(db, org_b, "70"),
        montant_debit=Decimal("999"),
    )
    await _brouillon(
        db, org_a, societe_a, exercice_a, await _journal(db, org_a, "CA"), jour=date(2026, 2, 1),
        debit_compte=await _compte(db, org_a, "571"), credit_compte=await _compte(db, org_a, "70"),
        montant_debit=Decimal("100"),
    )

    rapport = await valider_lot(db, organisation_id=org_a.id, simulation=False, user_id=user_a.id)
    assert rapport.validees == 1
    await db.refresh(brouillon_b)
    assert brouillon_b.statut == "BROUILLON"


# ── Enchaînement complet ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lot_debloque_les_etats_financiers_et_la_cloture(db_session):
    """Le scénario qui motive tout ce service : des écritures générées
    automatiquement restent au brouillon, les états sont donc vides et la
    clôture refusée. Après validation en lot, tout se débloque."""
    db = db_session
    org = await _org(db)
    societe, exercice = await _activer(db, org)
    user = await _admin(db, org)
    caisse = await _compte(db, org, "571")
    produit = await _compte(db, org, "70")
    charge = await _compte(db, org, "605")
    journal = await _journal(db, org, "CA")

    await _brouillon(db, org, societe, exercice, journal, jour=date(2026, 3, 1),
                     debit_compte=caisse, credit_compte=produit, montant_debit=Decimal("5000"))
    await _brouillon(db, org, societe, exercice, journal, jour=date(2026, 4, 1),
                     debit_compte=charge, credit_compte=caisse, montant_debit=Decimal("1500"))

    # Avant : les états ne voient rien, et la clôture est impossible.
    avant = await calculer_etat(
        db, organisation_id=org.id, exercice_id=exercice.id, type_etat="RESULTAT"
    )
    assert avant.total == Decimal("0")
    with pytest.raises(ClotureError):
        await cloturer_exercice(
            db, organisation_id=org.id, exercice_id=exercice.id, user_id=user.id
        )

    rapport = await valider_lot(
        db, organisation_id=org.id, exercice_id=exercice.id, simulation=False, user_id=user.id
    )
    assert rapport.validees == 2
    assert rapport.echecs == []

    apres = await calculer_etat(
        db, organisation_id=org.id, exercice_id=exercice.id, type_etat="RESULTAT"
    )
    assert apres.total == Decimal("3500")

    await determiner_resultat(db, organisation_id=org.id, exercice_id=exercice.id, user_id=user.id)
    resume = await cloturer_exercice(
        db, organisation_id=org.id, exercice_id=exercice.id, user_id=user.id
    )
    assert resume["deja_cloture"] is False
    await db.refresh(exercice)
    assert exercice.statut == "CLOTURE"
