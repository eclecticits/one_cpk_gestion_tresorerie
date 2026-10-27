"""Import du plan comptable depuis Excel.

L'import enrichit le plan de démarrage. Les tests portent sur ses garde-fous :
la simulation n'écrit rien, une seule erreur bloque tout le fichier, une
colonne absente n'écrase rien, et un compte mouvementé ou mappé garde ce qui
le rend utilisable.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.organisation import Organisation
from app.modules.comptabilite.models import (
    ComptaCompte,
    ComptaEcriture,
    ComptaExercice,
    ComptaJournal,
    ComptaLigneEcriture,
    ComptaSociete,
)
from app.modules.comptabilite.schemas.plan_import import LignePlanIn
from app.modules.comptabilite.services.import_plan_service import (
    ReferentielIntrouvable,
    deduire_nature_sens,
    importer_plan_comptable,
    normaliser_numero,
)
from app.modules.comptabilite.services.mapping_defaut_service import generer_mappings_par_defaut
from app.modules.comptabilite.services.setup_service import setup_comptabilite


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


async def _org(db) -> Organisation:
    org = Organisation(nom="Plan Test", slug=f"plan-{_suffix()}", is_active=True)
    db.add(org)
    await db.flush()
    return org


async def _activer(db, org) -> None:
    await setup_comptabilite(
        db, organisation_id=org.id, organisation_nom=org.nom, type_referentiel="SYSCEBNL",
        exercice_date_debut=date(2026, 1, 1), exercice_date_fin=date(2026, 12, 31),
    )
    await db.flush()


async def _compte(db, org, numero: str) -> ComptaCompte | None:
    return (
        await db.execute(
            select(ComptaCompte).where(ComptaCompte.organisation_id == org.id, ComptaCompte.numero == numero)
        )
    ).scalar_one_or_none()


def _ligne(ligne: int, numero: str, libelle: str, **autres) -> LignePlanIn:
    return LignePlanIn(ligne=ligne, numero=numero, libelle=libelle, **autres)


async def _importer(db, org, lignes, *, mode="update_existing", simulation=False):
    return await importer_plan_comptable(
        db, organisation_id=org.id, lignes=lignes, mode=mode, simulation=simulation
    )


# ── Déductions ─────────────────────────────────────────────────────────────


def test_nature_et_sens_deduits_de_la_numerotation_ohada():
    assert deduire_nature_sens("101") == ("PASSIF", "CREDIT")
    assert deduire_nature_sens("2183") == ("ACTIF", "DEBIT")
    assert deduire_nature_sens("2813") == ("ACTIF", "CREDIT")
    assert deduire_nature_sens("401") == ("PASSIF", "CREDIT")
    assert deduire_nature_sens("411") == ("ACTIF", "DEBIT")
    assert deduire_nature_sens("561") == ("PASSIF", "CREDIT")
    assert deduire_nature_sens("571") == ("ACTIF", "DEBIT")
    assert deduire_nature_sens("605") == ("CHARGE", "DEBIT")
    assert deduire_nature_sens("706") == ("PRODUIT", "CREDIT")
    assert deduire_nature_sens("811") == ("CHARGE", "DEBIT")
    assert deduire_nature_sens("821") == ("PRODUIT", "CREDIT")
    assert deduire_nature_sens("901") == ("ENGAGEMENT", "DEBIT")


def test_numero_saisi_avec_separateurs_est_normalise():
    assert normaliser_numero(" 601 100 ") == "601100"
    assert normaliser_numero("601.100") == "601100"
    assert normaliser_numero("411-cli") == "411CLI"


# ── Simulation et création ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_simulation_n_ecrit_rien_et_annonce_les_deductions(db_session):
    db = db_session
    org = await _activer_org(db)

    out = await _importer(db, org, [_ligne(2, "605100", "Fournitures de bureau")], simulation=True)

    assert out.simulation and not out.enregistre
    assert out.crees == 1 and out.erreurs == 0
    ligne = out.lignes[0]
    assert ligne.action == "CREER"
    assert (ligne.nature, ligne.sens_normal, ligne.parent_numero) == ("CHARGE", "DEBIT", "605")
    assert set(ligne.deduits) == {"nature", "sens", "parent"}
    assert await _compte(db, org, "605100") is None


@pytest.mark.asyncio
async def test_import_cree_les_comptes_et_les_rattache_entre_eux(db_session):
    """Un compte peut avoir pour parent un autre compte du même fichier."""
    db = db_session
    org = await _activer_org(db)

    out = await _importer(
        db,
        org,
        [
            _ligne(2, "6058", "Autres achats"),
            _ligne(3, "60581", "Achats de petit matériel"),
            _ligne(4, "47199", "Compte d'attente", nature="Passif", sens="Crédit"),
        ],
    )

    assert out.enregistre and out.crees == 3
    parent = await _compte(db, org, "6058")
    enfant = await _compte(db, org, "60581")
    attente = await _compte(db, org, "47199")
    assert enfant.parent_id == parent.id
    assert parent.parent_id == (await _compte(db, org, "605")).id
    assert (attente.nature, attente.sens_normal, attente.classe) == ("PASSIF", "CREDIT", "4")


# ── Tout ou rien ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_une_ligne_en_erreur_bloque_tout_le_fichier(db_session):
    db = db_session
    org = await _activer_org(db)

    out = await _importer(
        db,
        org,
        [
            _ligne(2, "605200", "Valide"),
            _ligne(3, "0AB", "Classe impossible"),
            _ligne(4, "605300", "Nature inconnue", nature="Dépense"),
            _ligne(5, "605200", "Doublon"),
            _ligne(6, "605400", "Parent absent", parent="999999"),
        ],
    )

    assert not out.enregistre
    assert out.erreurs == 4
    assert [l.ligne for l in out.lignes if l.action == "ERREUR"] == [3, 4, 5, 6]
    assert "ligne 2" in out.lignes[3].message
    assert await _compte(db, org, "605200") is None


@pytest.mark.asyncio
async def test_rattachement_circulaire_refuse(db_session):
    db = db_session
    org = await _activer_org(db)

    out = await _importer(
        db,
        org,
        [_ligne(2, "6091", "A", parent="6092"), _ligne(3, "6092", "B", parent="6091")],
        simulation=True,
    )

    assert out.erreurs == 2
    assert all("circulaire" in l.message for l in out.lignes)


# ── Comptes existants ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mise_a_jour_ne_touche_que_les_colonnes_renseignees(db_session):
    db = db_session
    org = await _activer_org(db)
    avant = await _compte(db, org, "605")

    out = await _importer(db, org, [_ligne(2, "605", "Autres achats (révisé)")])

    assert out.mis_a_jour == 1
    assert out.lignes[0].changements == ["libelle"]
    apres = await _compte(db, org, "605")
    assert apres.libelle == "Autres achats (révisé)"
    assert (apres.nature, apres.sens_normal, apres.actif) == (avant.nature, avant.sens_normal, True)


@pytest.mark.asyncio
async def test_ajout_seul_laisse_les_comptes_existants(db_session):
    db = db_session
    org = await _activer_org(db)

    out = await _importer(
        db, org, [_ligne(2, "605", "Ne doit pas passer"), _ligne(3, "605500", "Nouveau")], mode="add_only"
    )

    assert (out.ignores, out.crees) == (1, 1)
    assert (await _compte(db, org, "605")).libelle != "Ne doit pas passer"


@pytest.mark.asyncio
async def test_ligne_identique_au_plan_reste_inchangee(db_session):
    db = db_session
    org = await _activer_org(db)
    compte = await _compte(db, org, "605")

    out = await _importer(db, org, [_ligne(2, "605", compte.libelle)], simulation=True)

    assert out.inchanges == 1 and out.mis_a_jour == 0
    assert out.message.startswith("Le plan est déjà à jour")


@pytest.mark.asyncio
async def test_compte_mouvemente_garde_sa_nature(db_session):
    db = db_session
    org = await _activer_org(db)
    compte = await _compte(db, org, "605")
    societe = (await db.execute(select(ComptaSociete).where(ComptaSociete.organisation_id == org.id))).scalar_one()
    exercice = (await db.execute(select(ComptaExercice).where(ComptaExercice.organisation_id == org.id))).scalars().first()
    journal = (await db.execute(select(ComptaJournal).where(ComptaJournal.organisation_id == org.id))).scalars().first()
    ecriture = ComptaEcriture(
        organisation_id=org.id, societe_id=societe.id, exercice_id=exercice.id, journal_id=journal.id,
        date_ecriture=date(2026, 3, 1), libelle="Achat", statut="BROUILLON", devise="USD",
    )
    db.add(ecriture)
    await db.flush()
    db.add(
        ComptaLigneEcriture(
            organisation_id=org.id, societe_id=societe.id, ecriture_id=ecriture.id, compte_id=compte.id,
            ordre=1, libelle="Achat", debit=Decimal("10"), credit=Decimal("0"), devise="USD",
            debit_tenue=Decimal("10"), credit_tenue=Decimal("0"),
        )
    )
    await db.flush()

    out = await _importer(db, org, [_ligne(2, "605", compte.libelle, nature="Produit", sens="Crédit")])

    assert not out.enregistre and out.erreurs == 1
    assert "mouvementé" in out.lignes[0].message
    assert (await _compte(db, org, "605")).nature == "CHARGE"


@pytest.mark.asyncio
async def test_compte_mappe_ne_peut_pas_etre_desactive(db_session):
    db = db_session
    org = await _activer_org(db)
    await generer_mappings_par_defaut(db, organisation_id=org.id)
    await db.flush()
    societe = (await db.execute(select(ComptaSociete).where(ComptaSociete.organisation_id == org.id))).scalar_one()
    caisse = await db.get(ComptaCompte, societe.compte_caisse_defaut_id)

    out = await _importer(db, org, [_ligne(2, caisse.numero, caisse.libelle, actif="Non")], simulation=True)

    assert out.erreurs == 1
    assert "mapping" in out.lignes[0].message


@pytest.mark.asyncio
async def test_import_refuse_sans_comptabilite_activee(db_session):
    db = db_session
    org = await _org(db)

    with pytest.raises(ReferentielIntrouvable):
        await _importer(db, org, [_ligne(2, "605", "X")], simulation=True)


async def _activer_org(db) -> Organisation:
    org = await _org(db)
    await _activer(db, org)
    return org
