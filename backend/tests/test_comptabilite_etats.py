"""États financiers et clôture d'exercice (Lot 5).

Le cœur des vérifications :
- le bilan est ÉQUILIBRÉ une fois le résultat déterminé — c'est le contrôle
  qui prouve que la structure paramétrée couvre bien tous les comptes ;
- les clients créditeurs basculent automatiquement au passif (filtre de sens
  appliqué compte par compte) ;
- les amortissements se déduisent des immobilisations brutes ;
- le résultat calculé par l'état correspond à celui de la clôture ;
- la clôture et le report des à-nouveaux sont idempotents et ordonnés ;
- un compte mouvementé hors de tout poste est SIGNALÉ, pas ignoré.
"""

from __future__ import annotations

import importlib.util
import pathlib
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, text

ALEMBIC_VERSIONS_DIR = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _load_migration(filename: str):
    """Charge une migration Alembic comme module autonome (cf. test_comptabilite)."""
    path = ALEMBIC_VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

from app.models.organisation import Organisation
from app.models.user import User
from app.modules.comptabilite.models import (
    ComptaCompte,
    ComptaEcriture,
    ComptaExercice,
    ComptaJournal,
    ComptaLigneEcriture,
    ComptaPosteEtat,
    ComptaSociete,
)
from app.modules.comptabilite.services.cloture_service import (
    ClotureError,
    cloturer_exercice,
    determiner_resultat,
    reporter_a_nouveaux,
)
from app.modules.comptabilite.services.ecriture_service import valider_ecriture
from app.modules.comptabilite.services.etats_financiers import calculer_etat, controler_bilan
from app.modules.comptabilite.services.setup_service import setup_comptabilite


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


async def _org(db) -> Organisation:
    org = Organisation(nom="États Test", slug=f"etats-{_suffix()}", is_active=True)
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


async def _ecriture(
    db, org, societe, exercice, journal, *, jour: date,
    lignes: list[tuple[ComptaCompte, Decimal, Decimal]], libelle="Opération", user=None, valider=True,
) -> ComptaEcriture:
    ecriture = ComptaEcriture(
        organisation_id=org.id, societe_id=societe.id, exercice_id=exercice.id,
        journal_id=journal.id, date_ecriture=jour, libelle=libelle, statut="BROUILLON",
        devise="USD",
    )
    db.add(ecriture)
    await db.flush()
    for ordre, (compte, debit, credit) in enumerate(lignes, start=1):
        db.add(
            ComptaLigneEcriture(
                organisation_id=org.id, societe_id=societe.id, ecriture_id=ecriture.id,
                compte_id=compte.id, ordre=ordre, libelle=libelle,
                debit=debit, credit=credit, devise="USD",
                debit_tenue=debit, credit_tenue=credit,
            )
        )
    await db.flush()
    if valider:
        await valider_ecriture(
            db, ecriture_id=ecriture.id, organisation_id=org.id,
            user_id=user.id if user else None,
        )
    return ecriture


def _ligne(etat, code: str):
    return next(l for l in etat.lignes if l.code == code)


# ── Provisionnement ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_activation_provisionne_les_structures_d_etats(db_session):
    db = db_session
    org = await _org(db)
    _, exercice = await _activer(db, org)

    res = await db.execute(
        select(ComptaPosteEtat.type_etat).where(ComptaPosteEtat.organisation_id == org.id)
    )
    types = {row for row, in res.all()}
    assert types == {"BILAN_ACTIF", "BILAN_PASSIF", "RESULTAT", "SIG", "FLUX"}


@pytest.mark.asyncio
async def test_activation_rejouee_n_ecrase_pas_le_parametrage(db_session):
    """Le provisionnement est idempotent : un rejeu ne doit pas dupliquer les
    postes ni écraser un paramétrage affiné par l'organisation."""
    db = db_session
    org = await _org(db)
    await _activer(db, org)
    avant = (
        await db.execute(
            select(ComptaPosteEtat).where(ComptaPosteEtat.organisation_id == org.id)
        )
    ).scalars().all()

    poste = avant[0]
    poste.libelle = "Libellé personnalisé"
    await db.flush()

    await _activer(db, org)
    apres = (
        await db.execute(
            select(ComptaPosteEtat).where(ComptaPosteEtat.organisation_id == org.id)
        )
    ).scalars().all()
    assert len(apres) == len(avant)
    await db.refresh(poste)
    assert poste.libelle == "Libellé personnalisé"


# ── Bilan ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bilan_equilibre_apres_determination_du_resultat(db_session):
    """Le contrôle décisif : actif = passif. S'il échoue, c'est que la
    structure paramétrée laisse des comptes de côté."""
    db = db_session
    org = await _org(db)
    societe, exercice = await _activer(db, org)
    user = await _admin(db, org)

    caisse = await _compte(db, org, "571")
    cotisations = await _compte(db, org, "70")
    charges = await _compte(db, org, "605")
    journal = await _journal(db, org, "CA")

    # Encaissement de cotisations, puis une dépense.
    await _ecriture(db, org, societe, exercice, journal, jour=date(2026, 3, 1),
                    lignes=[(caisse, Decimal("5000"), Decimal("0")),
                            (cotisations, Decimal("0"), Decimal("5000"))], user=user)
    await _ecriture(db, org, societe, exercice, journal, jour=date(2026, 4, 1),
                    lignes=[(charges, Decimal("1200"), Decimal("0")),
                            (caisse, Decimal("0"), Decimal("1200"))], user=user)

    # Avant détermination du résultat, le bilan est volontairement déséquilibré :
    # le résultat de l'exercice n'y figure pas encore.
    controle_avant = await controler_bilan(db, organisation_id=org.id, exercice_id=exercice.id)
    assert not controle_avant.equilibre

    await determiner_resultat(db, organisation_id=org.id, exercice_id=exercice.id, user_id=user.id)

    controle = await controler_bilan(db, organisation_id=org.id, exercice_id=exercice.id)
    assert controle.equilibre, (
        f"actif {controle.total_actif} ≠ passif {controle.total_passif}, "
        f"comptes non couverts : {controle.comptes_non_couverts}"
    )
    assert controle.total_actif == Decimal("3800")  # 5000 − 1200 en caisse


@pytest.mark.asyncio
async def test_bilan_deduit_les_amortissements_des_immobilisations(db_session):
    db = db_session
    org = await _org(db)
    societe, exercice = await _activer(db, org)
    user = await _admin(db, org)

    materiel = await _compte(db, org, "2183")
    amortissement = await _compte(db, org, "2818")
    caisse = await _compte(db, org, "571")
    dotation = await _compte(db, org, "6811")
    journal = await _journal(db, org, "OD")

    await _ecriture(db, org, societe, exercice, journal, jour=date(2026, 1, 15),
                    lignes=[(materiel, Decimal("3000"), Decimal("0")),
                            (caisse, Decimal("0"), Decimal("3000"))], user=user)
    await _ecriture(db, org, societe, exercice, journal, jour=date(2026, 12, 31),
                    lignes=[(dotation, Decimal("600"), Decimal("0")),
                            (amortissement, Decimal("0"), Decimal("600"))], user=user)

    actif = await calculer_etat(
        db, organisation_id=org.id, exercice_id=exercice.id, type_etat="BILAN_ACTIF"
    )
    corporelles = _ligne(actif, "AC")
    assert corporelles.brut == Decimal("3000")
    assert corporelles.amortissement == Decimal("600")
    assert corporelles.net == Decimal("2400")


@pytest.mark.asyncio
async def test_adherent_crediteur_bascule_au_passif(db_session):
    """Filtre de sens appliqué COMPTE PAR COMPTE : un adhérent qui a trop payé
    est une dette, pas une créance en moins."""
    db = db_session
    org = await _org(db)
    societe, exercice = await _activer(db, org)
    user = await _admin(db, org)

    # Deux comptes auxiliaires d'adhérents, de sens opposés.
    referentiel_id = exercice.referentiel_id
    debiteur = ComptaCompte(
        organisation_id=org.id, referentiel_id=referentiel_id, numero="4110001",
        libelle="Adhérent A", nature="ACTIF", sens_normal="DEBIT",
    )
    crediteur = ComptaCompte(
        organisation_id=org.id, referentiel_id=referentiel_id, numero="4110002",
        libelle="Adhérent B", nature="ACTIF", sens_normal="DEBIT",
    )
    db.add_all([debiteur, crediteur])
    await db.flush()

    cotisations = await _compte(db, org, "70")
    caisse = await _compte(db, org, "571")
    journal = await _journal(db, org, "OD")

    # A doit 800 ; B a versé 300 d'avance.
    await _ecriture(db, org, societe, exercice, journal, jour=date(2026, 2, 1),
                    lignes=[(debiteur, Decimal("800"), Decimal("0")),
                            (cotisations, Decimal("0"), Decimal("800"))], user=user)
    await _ecriture(db, org, societe, exercice, journal, jour=date(2026, 2, 2),
                    lignes=[(caisse, Decimal("300"), Decimal("0")),
                            (crediteur, Decimal("0"), Decimal("300"))], user=user)

    actif = await calculer_etat(
        db, organisation_id=org.id, exercice_id=exercice.id, type_etat="BILAN_ACTIF"
    )
    passif = await calculer_etat(
        db, organisation_id=org.id, exercice_id=exercice.id, type_etat="BILAN_PASSIF"
    )
    # La créance nette n'est PAS 500 : les deux positions sont présentées
    # séparément, de part et d'autre du bilan.
    assert _ligne(actif, "BX").net == Decimal("800")
    assert _ligne(passif, "DD").net == Decimal("300")


@pytest.mark.asyncio
async def test_compte_hors_de_tout_poste_est_signale(db_session):
    """La faiblesse d'un rattachement par préfixe est qu'un compte peut
    n'entrer nulle part : il doit être signalé, jamais disparaître."""
    db = db_session
    org = await _org(db)
    societe, exercice = await _activer(db, org)
    user = await _admin(db, org)

    orphelin = ComptaCompte(
        organisation_id=org.id, referentiel_id=exercice.referentiel_id, numero="9999",
        libelle="Compte hors nomenclature", nature="ACTIF", sens_normal="DEBIT",
    )
    db.add(orphelin)
    await db.flush()
    caisse = await _compte(db, org, "571")
    journal = await _journal(db, org, "OD")

    await _ecriture(db, org, societe, exercice, journal, jour=date(2026, 5, 1),
                    lignes=[(orphelin, Decimal("450"), Decimal("0")),
                            (caisse, Decimal("0"), Decimal("450"))], user=user)

    actif = await calculer_etat(
        db, organisation_id=org.id, exercice_id=exercice.id, type_etat="BILAN_ACTIF"
    )
    assert any("9999" in c for c in actif.comptes_non_couverts)


# ── Compte de résultat et SIG ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resultat_et_sig_concordent(db_session):
    db = db_session
    org = await _org(db)
    societe, exercice = await _activer(db, org)
    user = await _admin(db, org)

    caisse = await _compte(db, org, "571")
    cotisations = await _compte(db, org, "70")
    achats = await _compte(db, org, "605")
    personnel = await _compte(db, org, "661")
    journal = await _journal(db, org, "CA")

    await _ecriture(db, org, societe, exercice, journal, jour=date(2026, 3, 1),
                    lignes=[(caisse, Decimal("9000"), Decimal("0")),
                            (cotisations, Decimal("0"), Decimal("9000"))], user=user)
    await _ecriture(db, org, societe, exercice, journal, jour=date(2026, 4, 1),
                    lignes=[(achats, Decimal("2000"), Decimal("0")),
                            (caisse, Decimal("0"), Decimal("2000"))], user=user)
    await _ecriture(db, org, societe, exercice, journal, jour=date(2026, 5, 1),
                    lignes=[(personnel, Decimal("3000"), Decimal("0")),
                            (caisse, Decimal("0"), Decimal("3000"))], user=user)

    resultat = await calculer_etat(
        db, organisation_id=org.id, exercice_id=exercice.id, type_etat="RESULTAT"
    )
    assert _ligne(resultat, "TOTAL_PRODUITS").net == Decimal("9000")
    assert _ligne(resultat, "TOTAL_CHARGES").net == Decimal("5000")
    assert resultat.total == Decimal("4000")

    sig = await calculer_etat(
        db, organisation_id=org.id, exercice_id=exercice.id, type_etat="SIG"
    )
    # Marge = cotisations − achats ; le résultat net des SIG doit retomber sur
    # celui du compte de résultat.
    assert _ligne(sig, "SIG_MARGE").net == Decimal("7000")
    assert _ligne(sig, "SIG_NET").net == Decimal("4000")


# ── Clôture ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_determination_du_resultat_solde_les_comptes_de_gestion(db_session):
    db = db_session
    org = await _org(db)
    societe, exercice = await _activer(db, org)
    user = await _admin(db, org)

    caisse = await _compte(db, org, "571")
    cotisations = await _compte(db, org, "70")
    achats = await _compte(db, org, "605")
    journal = await _journal(db, org, "CA")

    await _ecriture(db, org, societe, exercice, journal, jour=date(2026, 3, 1),
                    lignes=[(caisse, Decimal("6000"), Decimal("0")),
                            (cotisations, Decimal("0"), Decimal("6000"))], user=user)
    await _ecriture(db, org, societe, exercice, journal, jour=date(2026, 4, 1),
                    lignes=[(achats, Decimal("2500"), Decimal("0")),
                            (caisse, Decimal("0"), Decimal("2500"))], user=user)

    resume = await determiner_resultat(
        db, organisation_id=org.id, exercice_id=exercice.id, user_id=user.id
    )
    assert resume["resultat"] == Decimal("3500")
    assert resume["deja_fait"] is False

    # Charges et produits sont soldés.
    resultat = await calculer_etat(
        db, organisation_id=org.id, exercice_id=exercice.id, type_etat="RESULTAT"
    )
    assert _ligne(resultat, "TOTAL_PRODUITS").net == Decimal("0")
    assert _ligne(resultat, "TOTAL_CHARGES").net == Decimal("0")

    # Le résultat figure désormais au passif du bilan.
    passif = await calculer_etat(
        db, organisation_id=org.id, exercice_id=exercice.id, type_etat="BILAN_PASSIF"
    )
    assert _ligne(passif, "CD").net == Decimal("3500")

    # Rejeu : idempotent.
    rejeu = await determiner_resultat(
        db, organisation_id=org.id, exercice_id=exercice.id, user_id=user.id
    )
    assert rejeu["deja_fait"] is True


@pytest.mark.asyncio
async def test_cloture_refusee_avant_determination_du_resultat(db_session):
    db = db_session
    org = await _org(db)
    societe, exercice = await _activer(db, org)
    user = await _admin(db, org)
    caisse = await _compte(db, org, "571")
    cotisations = await _compte(db, org, "70")
    journal = await _journal(db, org, "CA")
    await _ecriture(db, org, societe, exercice, journal, jour=date(2026, 3, 1),
                    lignes=[(caisse, Decimal("100"), Decimal("0")),
                            (cotisations, Decimal("0"), Decimal("100"))], user=user)

    with pytest.raises(ClotureError) as exc:
        await cloturer_exercice(db, organisation_id=org.id, exercice_id=exercice.id, user_id=user.id)
    assert "résultat" in str(exc.value)


@pytest.mark.asyncio
async def test_cloture_refusee_s_il_reste_des_brouillons(db_session):
    """Un brouillon perdu à la clôture disparaîtrait des états sans trace."""
    db = db_session
    org = await _org(db)
    societe, exercice = await _activer(db, org)
    user = await _admin(db, org)
    caisse = await _compte(db, org, "571")
    cotisations = await _compte(db, org, "70")
    journal = await _journal(db, org, "CA")

    await _ecriture(db, org, societe, exercice, journal, jour=date(2026, 3, 1),
                    lignes=[(caisse, Decimal("500"), Decimal("0")),
                            (cotisations, Decimal("0"), Decimal("500"))], user=user)
    await determiner_resultat(db, organisation_id=org.id, exercice_id=exercice.id, user_id=user.id)
    # Un brouillon oublié, postérieur à la détermination du résultat.
    await _ecriture(db, org, societe, exercice, journal, jour=date(2026, 6, 1),
                    lignes=[(caisse, Decimal("50"), Decimal("0")),
                            (cotisations, Decimal("0"), Decimal("50"))], user=user, valider=False)

    with pytest.raises(ClotureError) as exc:
        await cloturer_exercice(db, organisation_id=org.id, exercice_id=exercice.id, user_id=user.id)
    assert "brouillon" in str(exc.value)


@pytest.mark.asyncio
async def test_cloture_puis_report_des_a_nouveaux(db_session):
    db = db_session
    org = await _org(db)
    societe, exercice = await _activer(db, org)
    user = await _admin(db, org)

    caisse = await _compte(db, org, "571")
    cotisations = await _compte(db, org, "70")
    journal = await _journal(db, org, "CA")
    await _ecriture(db, org, societe, exercice, journal, jour=date(2026, 3, 1),
                    lignes=[(caisse, Decimal("4200"), Decimal("0")),
                            (cotisations, Decimal("0"), Decimal("4200"))], user=user)

    await determiner_resultat(db, organisation_id=org.id, exercice_id=exercice.id, user_id=user.id)
    resume = await cloturer_exercice(
        db, organisation_id=org.id, exercice_id=exercice.id, user_id=user.id
    )
    assert resume["deja_cloture"] is False
    await db.refresh(exercice)
    assert exercice.statut == "CLOTURE"

    exercice_2027 = ComptaExercice(
        organisation_id=org.id, societe_id=societe.id, code="2027", libelle="Exercice 2027",
        date_debut=date(2027, 1, 1), date_fin=date(2027, 12, 31),
        referentiel_id=exercice.referentiel_id, statut="OUVERT",
    )
    db.add(exercice_2027)
    await db.flush()

    report = await reporter_a_nouveaux(
        db, organisation_id=org.id, exercice_id=exercice.id,
        exercice_suivant_id=exercice_2027.id, user_id=user.id,
    )
    assert report["deja_fait"] is False
    assert report["nb_comptes"] == 2  # caisse (débit) et résultat (crédit)

    # L'exercice suivant s'ouvre sur un bilan équilibré, sans aucune écriture
    # d'exploitation.
    controle = await controler_bilan(
        db, organisation_id=org.id, exercice_id=exercice_2027.id, date_arrete=date(2027, 12, 31)
    )
    assert controle.equilibre
    assert controle.total_actif == Decimal("4200")

    rejeu = await reporter_a_nouveaux(
        db, organisation_id=org.id, exercice_id=exercice.id,
        exercice_suivant_id=exercice_2027.id, user_id=user.id,
    )
    assert rejeu["deja_fait"] is True


@pytest.mark.asyncio
async def test_a_nouveaux_refuses_si_exercice_non_cloture(db_session):
    """Reporter les soldes d'un exercice encore ouvert produirait une
    ouverture fausse dès la prochaine écriture."""
    db = db_session
    org = await _org(db)
    societe, exercice = await _activer(db, org)
    user = await _admin(db, org)

    exercice_2027 = ComptaExercice(
        organisation_id=org.id, societe_id=societe.id, code="2027", libelle="Exercice 2027",
        date_debut=date(2027, 1, 1), date_fin=date(2027, 12, 31),
        referentiel_id=exercice.referentiel_id, statut="OUVERT",
    )
    db.add(exercice_2027)
    await db.flush()

    with pytest.raises(ClotureError) as exc:
        await reporter_a_nouveaux(
            db, organisation_id=org.id, exercice_id=exercice.id,
            exercice_suivant_id=exercice_2027.id, user_id=user.id,
        )
    assert "clôturé" in str(exc.value)


@pytest.mark.asyncio
async def test_cloture_passe_le_trigger_d_immuabilite_reel(db_session):
    """Le schéma de test est bâti par `create_all` et ne porte donc PAS les
    triggers : sans ce test, la clôture passerait ici et échouerait en
    production, où le trigger du Lot 1 n'autorisait qu'une transition vers
    ANNULEE. Le Lot 5 y ajoute VALIDEE → CLOTUREE.
    """
    db = db_session
    lot5 = _load_migration("20260801_compta_etats_financiers.py")
    fondations = _load_migration("20260731_compta_fondations.py")
    await db.execute(text(lot5.TRIGGER_ECRITURE_FUNCTION_LOT5))
    await db.execute(
        text(fondations.TRIGGER_ECRITURE_CREATE_SQL.replace("CREATE TRIGGER", "CREATE OR REPLACE TRIGGER"))
    )
    await db.commit()

    try:
        org = await _org(db)
        societe, exercice = await _activer(db, org)
        user = await _admin(db, org)
        caisse = await _compte(db, org, "571")
        cotisations = await _compte(db, org, "70")
        journal = await _journal(db, org, "CA")

        await _ecriture(db, org, societe, exercice, journal, jour=date(2026, 3, 1),
                        lignes=[(caisse, Decimal("900"), Decimal("0")),
                                (cotisations, Decimal("0"), Decimal("900"))], user=user)
        await determiner_resultat(
            db, organisation_id=org.id, exercice_id=exercice.id, user_id=user.id
        )
        resume = await cloturer_exercice(
            db, organisation_id=org.id, exercice_id=exercice.id, user_id=user.id
        )
        assert resume["ecritures_cloturees"] >= 2
    finally:
        # Le trigger est global à la base de test : le retirer évite d'imposer
        # ses contraintes aux autres tests, qui n'en tiennent pas compte.
        await db.rollback()
        await db.execute(text("DROP TRIGGER IF EXISTS trg_compta_ecriture_immutable ON compta_ecritures"))
        await db.commit()


@pytest.mark.asyncio
async def test_etats_ne_voient_pas_une_autre_organisation(db_session):
    db = db_session
    org_a = await _org(db)
    org_b = await _org(db)
    societe_a, exercice_a = await _activer(db, org_a)
    societe_b, exercice_b = await _activer(db, org_b)
    user_a = await _admin(db, org_a)
    user_b = await _admin(db, org_b)

    await _ecriture(db, org_a, societe_a, exercice_a, await _journal(db, org_a, "CA"),
                    jour=date(2026, 3, 1),
                    lignes=[(await _compte(db, org_a, "571"), Decimal("100"), Decimal("0")),
                            (await _compte(db, org_a, "70"), Decimal("0"), Decimal("100"))],
                    user=user_a)
    await _ecriture(db, org_b, societe_b, exercice_b, await _journal(db, org_b, "CA"),
                    jour=date(2026, 3, 1),
                    lignes=[(await _compte(db, org_b, "571"), Decimal("7777"), Decimal("0")),
                            (await _compte(db, org_b, "70"), Decimal("0"), Decimal("7777"))],
                    user=user_b)

    actif_a = await calculer_etat(
        db, organisation_id=org_a.id, exercice_id=exercice_a.id, type_etat="BILAN_ACTIF"
    )
    assert actif_a.total == Decimal("100")
