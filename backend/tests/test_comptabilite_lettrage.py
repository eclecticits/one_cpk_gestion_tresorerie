"""Lettrage des comptes de tiers.

Points sensibles couverts :
- un groupe lettré se solde, sur un seul compte et un seul tiers, entre
  écritures validées — tout le reste est refusé avec un motif lisible ;
- le lettrage automatique ne rapproche que l'évident (même pièce, même
  montant dans l'ordre des dates) et sa simulation n'écrit rien ;
- le trigger d'immuabilité réel laisse passer le lettrage d'une écriture
  validée, et lui seul : un montant reste intouchable ;
- aucune fuite inter-organisations.
"""

from __future__ import annotations

import importlib.util
import pathlib
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, text, update

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
from app.modules.comptabilite.services.ecriture_service import valider_ecriture
from app.modules.comptabilite.services.lettrage_service import (
    LettrageRefuse,
    code_suivant,
    comptes_a_lettrer,
    definir_lettrable,
    delettrer,
    lettrage_automatique,
    lettrer,
    lignes_du_compte,
)
from app.modules.comptabilite.services.reporting_service import grand_livre
from app.modules.comptabilite.services.setup_service import setup_comptabilite

ALEMBIC_VERSIONS_DIR = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _load_migration(filename: str):
    path = ALEMBIC_VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


class _Dossier:
    """Une organisation avec sa comptabilité activée et de quoi passer des écritures."""

    def __init__(self, db, org, user, societe, exercice):
        self.db, self.org, self.user, self.societe, self.exercice = db, org, user, societe, exercice

    async def compte(self, numero: str) -> ComptaCompte:
        return (
            await self.db.execute(
                select(ComptaCompte).where(
                    ComptaCompte.organisation_id == self.org.id, ComptaCompte.numero == numero
                )
            )
        ).scalar_one()

    async def ecriture(self, jour, montant, debit, credit, *, reference=None, valider=True) -> ComptaEcriture:
        journal = (
            await self.db.execute(
                select(ComptaJournal).where(
                    ComptaJournal.organisation_id == self.org.id, ComptaJournal.code == "OD"
                )
            )
        ).scalar_one()
        ecriture = ComptaEcriture(
            organisation_id=self.org.id, societe_id=self.societe.id, exercice_id=self.exercice.id,
            journal_id=journal.id, date_ecriture=jour, libelle="Opération", statut="BROUILLON",
            devise="USD", reference_piece=reference,
        )
        self.db.add(ecriture)
        await self.db.flush()
        montant = Decimal(montant)
        for ordre, (compte, d, c) in enumerate(((debit, montant, 0), (credit, 0, montant)), start=1):
            self.db.add(ComptaLigneEcriture(
                organisation_id=self.org.id, societe_id=self.societe.id, ecriture_id=ecriture.id,
                compte_id=compte.id, ordre=ordre, debit=Decimal(d), credit=Decimal(c), devise="USD",
                debit_tenue=Decimal(d), credit_tenue=Decimal(c),
            ))
        await self.db.flush()
        if valider:
            await valider_ecriture(
                self.db, ecriture_id=ecriture.id, organisation_id=self.org.id, user_id=self.user.id
            )
        return ecriture

    async def ligne(self, ecriture: ComptaEcriture, compte: ComptaCompte) -> ComptaLigneEcriture:
        return (
            await self.db.execute(
                select(ComptaLigneEcriture).where(
                    ComptaLigneEcriture.ecriture_id == ecriture.id,
                    ComptaLigneEcriture.compte_id == compte.id,
                )
            )
        ).scalar_one()


async def _dossier(db) -> _Dossier:
    org = Organisation(nom="Lettrage Test", slug=f"let-{_suffix()}", is_active=True)
    db.add(org)
    await db.flush()
    user = User(id=uuid.uuid4(), email=f"l{_suffix()}@ex.com", role="admin", organisation_id=org.id)
    db.add(user)
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
    return _Dossier(db, org, user, societe, exercice)


def test_suite_des_lettres():
    assert code_suivant(None) == "AA"
    assert code_suivant("AA") == "AB"
    assert code_suivant("AZ") == "BA"
    assert code_suivant("ZZ") == "AAA"


@pytest.mark.asyncio
async def test_plan_par_defaut_rend_les_comptes_de_tiers_lettrables(db_session):
    d = await _dossier(db_session)
    assert (await d.compte("421")).lettrable is True
    assert (await d.compte("411")).lettrable is True
    assert (await d.compte("571")).lettrable is False


@pytest.mark.asyncio
async def test_lettrer_une_creance_et_son_reglement(db_session):
    d = await _dossier(db_session)
    tiers, caisse, produit = await d.compte("46"), await d.compte("571"), await d.compte("758")

    creance = await d.ecriture(date(2026, 2, 1), "600", tiers, produit)
    reglement = await d.ecriture(date(2026, 3, 10), "600", caisse, tiers)
    autre = await d.ecriture(date(2026, 4, 1), "250", tiers, produit)

    code = await lettrer(
        d.db, organisation_id=d.org.id, user_id=d.user.id,
        ligne_ids=[(await d.ligne(creance, tiers)).id, (await d.ligne(reglement, tiers)).id],
    )
    assert code == "AA"

    ligne = await d.ligne(creance, tiers)
    # La date du lettrage est celle de la pièce qui solde, pas le jour du pointage.
    assert (ligne.lettrage, ligne.date_lettrage, ligne.lettre_par) == ("AA", date(2026, 3, 10), d.user.id)

    # Ce qui reste sans lettre est ce qui reste dû.
    restant = await lignes_du_compte(d.db, organisation_id=d.org.id, compte_id=tiers.id)
    assert [l.ecriture_id for l in restant] == [autre.id]
    etat = {c.numero: c for c in await comptes_a_lettrer(d.db, organisation_id=d.org.id)}
    assert etat["46"].lignes_non_lettrees == 1
    assert etat["46"].solde_non_lettre == Decimal("250")

    # La lettre se lit au Grand Livre.
    livre = await grand_livre(d.db, organisation_id=d.org.id, exercice_id=d.exercice.id, compte_id=tiers.id)
    assert [m.lettrage for m in livre.mouvements] == ["AA", "AA", None]

    # Le lettrage suivant prend la lettre suivante.
    solde = await d.ecriture(date(2026, 5, 1), "250", caisse, tiers)
    assert await lettrer(
        d.db, organisation_id=d.org.id, user_id=d.user.id,
        ligne_ids=[(await d.ligne(autre, tiers)).id, (await d.ligne(solde, tiers)).id],
    ) == "AB"


@pytest.mark.asyncio
async def test_lettrages_refuses(db_session):
    d = await _dossier(db_session)
    tiers, autre_tiers = await d.compte("46"), await d.compte("421")
    caisse, produit = await d.compte("571"), await d.compte("758")

    creance = await d.ecriture(date(2026, 2, 1), "600", tiers, produit)
    partiel = await d.ecriture(date(2026, 3, 1), "400", caisse, tiers)
    brouillon = await d.ecriture(date(2026, 3, 2), "600", caisse, tiers, valider=False)
    ailleurs = await d.ecriture(date(2026, 3, 3), "600", caisse, autre_tiers)
    l_creance = (await d.ligne(creance, tiers)).id

    async def refus(ids) -> str:
        with pytest.raises(LettrageRefuse) as exc:
            await lettrer(d.db, organisation_id=d.org.id, ligne_ids=ids, user_id=d.user.id)
        return str(exc.value)

    assert "au moins deux" in await refus([l_creance])
    assert "ne se soldent pas" in await refus([l_creance, (await d.ligne(partiel, tiers)).id])
    assert "validées" in await refus([l_creance, (await d.ligne(brouillon, tiers)).id])
    assert "même compte" in await refus([l_creance, (await d.ligne(ailleurs, autre_tiers)).id])
    # La caisse n'est pas un compte de tiers.
    assert "pas lettrable" in await refus(
        [(await d.ligne(partiel, caisse)).id, (await d.ligne(ailleurs, caisse)).id]
    )

    reglement = await d.ecriture(date(2026, 4, 1), "600", caisse, tiers)
    l_reglement = (await d.ligne(reglement, tiers)).id
    await lettrer(d.db, organisation_id=d.org.id, ligne_ids=[l_creance, l_reglement], user_id=d.user.id)
    assert "déjà lettrée" in await refus([l_creance, l_reglement])


@pytest.mark.asyncio
async def test_delettrer_libere_tout_le_groupe(db_session):
    d = await _dossier(db_session)
    tiers, caisse, produit = await d.compte("46"), await d.compte("571"), await d.compte("758")
    creance = await d.ecriture(date(2026, 2, 1), "600", tiers, produit)
    reglement = await d.ecriture(date(2026, 3, 1), "600", caisse, tiers)
    ids = [(await d.ligne(creance, tiers)).id, (await d.ligne(reglement, tiers)).id]
    code = await lettrer(d.db, organisation_id=d.org.id, ligne_ids=ids, user_id=d.user.id)

    # Un compte qui porte des lettres ne peut pas cesser d'être lettrable.
    with pytest.raises(LettrageRefuse):
        await definir_lettrable(d.db, organisation_id=d.org.id, compte_id=tiers.id, lettrable=False)

    assert await delettrer(d.db, organisation_id=d.org.id, compte_id=tiers.id, code=code) == 2
    ligne = await d.ligne(creance, tiers)
    assert (ligne.lettrage, ligne.date_lettrage, ligne.lettre_par) == (None, None, None)
    with pytest.raises(LettrageRefuse):
        await delettrer(d.db, organisation_id=d.org.id, compte_id=tiers.id, code=code)

    compte = await definir_lettrable(d.db, organisation_id=d.org.id, compte_id=tiers.id, lettrable=False)
    assert compte.lettrable is False


@pytest.mark.asyncio
async def test_lettrage_automatique_ne_rapproche_que_l_evident(db_session):
    d = await _dossier(db_session)
    tiers, caisse, produit = await d.compte("46"), await d.compte("571"), await d.compte("758")

    # Même pièce, réglée en deux fois : rapprochée par la référence.
    await d.ecriture(date(2026, 1, 5), "1000", tiers, produit, reference="ND-001")
    await d.ecriture(date(2026, 1, 20), "400", caisse, tiers, reference="ND-001")
    await d.ecriture(date(2026, 2, 20), "600", caisse, tiers, reference="nd-001")
    # Deux créances de 300 et un seul règlement : la plus ancienne est soldée.
    ancienne = await d.ecriture(date(2026, 3, 1), "300", tiers, produit)
    recente = await d.ecriture(date(2026, 4, 1), "300", tiers, produit)
    await d.ecriture(date(2026, 5, 1), "300", caisse, tiers)
    # Sans contrepartie de même montant : laissée telle quelle.
    await d.ecriture(date(2026, 6, 1), "75", tiers, produit)

    simulation = await lettrage_automatique(d.db, organisation_id=d.org.id, simulation=True)
    assert [(g.motif, len(g.lignes), g.montant, g.code) for g in simulation.groupes] == [
        ("REFERENCE", 3, Decimal("1000"), None),
        ("MONTANT", 2, Decimal("300"), None),
    ]
    assert len(await lignes_du_compte(d.db, organisation_id=d.org.id, compte_id=tiers.id)) == 7

    reel = await lettrage_automatique(
        d.db, organisation_id=d.org.id, compte_id=tiers.id, simulation=False, user_id=d.user.id
    )
    assert [g.code for g in reel.groupes] == ["AA", "AB"]
    assert reel.lignes_lettrees == 5
    assert (await d.ligne(ancienne, tiers)).lettrage == "AB"
    assert (await d.ligne(recente, tiers)).lettrage is None

    restant = await lignes_du_compte(d.db, organisation_id=d.org.id, compte_id=tiers.id)
    assert sum(l.debit - l.credit for l in restant) == Decimal("375")
    # Rejouer ne trouve plus rien à rapprocher.
    assert (await lettrage_automatique(d.db, organisation_id=d.org.id, simulation=False)).groupes == []


@pytest.mark.asyncio
async def test_lettrage_ne_voit_pas_une_autre_organisation(db_session):
    a = await _dossier(db_session)
    b = await _dossier(db_session)
    tiers_a, caisse_a, produit_a = await a.compte("46"), await a.compte("571"), await a.compte("758")
    creance = await a.ecriture(date(2026, 2, 1), "600", tiers_a, produit_a)
    reglement = await a.ecriture(date(2026, 3, 1), "600", caisse_a, tiers_a)
    ids = [(await a.ligne(creance, tiers_a)).id, (await a.ligne(reglement, tiers_a)).id]

    with pytest.raises(LettrageRefuse):
        await lettrer(a.db, organisation_id=b.org.id, ligne_ids=ids, user_id=b.user.id)
    with pytest.raises(LettrageRefuse):
        await lettrage_automatique(a.db, organisation_id=b.org.id, compte_id=tiers_a.id)
    assert all(c.lignes_non_lettrees == 0 for c in await comptes_a_lettrer(a.db, organisation_id=b.org.id))
    assert (await lettrage_automatique(a.db, organisation_id=b.org.id, simulation=False)).groupes == []
    assert (await a.ligne(creance, tiers_a)).lettrage is None


@pytest.mark.asyncio
async def test_lettrage_passe_le_trigger_d_immuabilite_reel(db_session):
    """Le schéma de test n'a pas les triggers. En production, le trigger des
    lignes refusait TOUTE modification d'une écriture validée — donc tout
    lettrage. La migration ne lève l'interdit que pour les colonnes de lettrage.
    """
    db = db_session
    migration = _load_migration("20261111_compta_lettrage.py")
    fondations = _load_migration("20260731_compta_fondations.py")
    await db.execute(text(migration.TRIGGER_LIGNE_FUNCTION_LETTRAGE))
    await db.execute(
        text(fondations.TRIGGER_LIGNE_CREATE_SQL.replace("CREATE TRIGGER", "CREATE OR REPLACE TRIGGER"))
    )
    await db.commit()

    try:
        d = await _dossier(db)
        tiers, caisse, produit = await d.compte("46"), await d.compte("571"), await d.compte("758")
        creance = await d.ecriture(date(2026, 2, 1), "600", tiers, produit)
        reglement = await d.ecriture(date(2026, 3, 1), "600", caisse, tiers)
        ligne = await d.ligne(creance, tiers)
        ids = [ligne.id, (await d.ligne(reglement, tiers)).id]

        code = await lettrer(db, organisation_id=d.org.id, ligne_ids=ids, user_id=d.user.id)
        assert await delettrer(db, organisation_id=d.org.id, compte_id=tiers.id, code=code) == 2
        await lettrer(db, organisation_id=d.org.id, ligne_ids=ids, user_id=d.user.id)

        # Le reste de la ligne demeure figé, même glissé avec un lettrage.
        with pytest.raises(Exception) as exc:
            async with db.begin_nested():
                await db.execute(
                    update(ComptaLigneEcriture)
                    .where(ComptaLigneEcriture.id == ligne.id)
                    .values(debit_tenue=Decimal("1"), lettrage="ZZ")
                )
        assert "Lignes figées" in str(exc.value)
    finally:
        await db.rollback()
        await db.execute(text("DROP TRIGGER IF EXISTS trg_compta_ligne_immutable ON compta_lignes_ecriture"))
        await db.commit()


# ── Balance âgée ────────────────────────────────────────────────────────────


def test_tranches_d_anciennete():
    from app.modules.comptabilite.services.balance_agee_service import tranche

    assert [tranche(j) for j in (-1, 0, 30, 31, 60, 61, 90, 91, 400)] == [
        "non_echu", "j0_30", "j0_30", "j31_60", "j31_60", "j61_90", "j61_90", "plus_90", "plus_90",
    ]


@pytest.mark.asyncio
async def test_balance_agee_ne_vieillit_que_le_non_lettre(db_session):
    from app.modules.comptabilite.services.balance_agee_service import balance_agee

    d = await _dossier(db_session)
    tiers, autre = await d.compte("46"), await d.compte("421")
    caisse, produit = await d.compte("571"), await d.compte("758")

    soldee = await d.ecriture(date(2026, 1, 10), "600", tiers, produit)
    reglement = await d.ecriture(date(2026, 5, 20), "600", caisse, tiers)
    await d.ecriture(date(2026, 3, 1), "300", tiers, produit)          # 91 jours au 31 mai
    await d.ecriture(date(2026, 5, 15), "80", tiers, produit)          # 16 jours
    a_echoir = await d.ecriture(date(2026, 5, 20), "50", tiers, produit, valider=False)
    (await d.ligne(a_echoir, tiers)).date_echeance = date(2026, 6, 30)  # pas encore échue
    await valider_ecriture(d.db, ecriture_id=a_echoir.id, organisation_id=d.org.id, user_id=d.user.id)
    await d.ecriture(date(2026, 4, 1), "999", caisse, autre)           # tiers créditeur : une dette
    await lettrer(
        d.db, organisation_id=d.org.id, user_id=d.user.id,
        ligne_ids=[(await d.ligne(soldee, tiers)).id, (await d.ligne(reglement, tiers)).id],
    )

    fin_mai = await balance_agee(d.db, organisation_id=d.org.id, date_arret=date(2026, 5, 31))
    (ligne,) = fin_mai.lignes
    assert ligne.compte_numero == "46" and ligne.lignes == 3
    assert ligne.tranches == {
        "non_echu": Decimal("50"), "j0_30": Decimal("80"), "j31_60": Decimal("0"),
        "j61_90": Decimal("0"), "plus_90": Decimal("300"),
    }
    assert fin_mai.total == ligne.solde == Decimal("430")
    assert ligne.plus_ancienne == date(2026, 3, 1)

    # À fin avril, la créance de janvier n'était pas encore soldée : elle compte.
    fin_avril = await balance_agee(d.db, organisation_id=d.org.id, date_arret=date(2026, 4, 30))
    assert fin_avril.total == Decimal("900")
    assert fin_avril.lignes[0].tranches["plus_90"] == Decimal("600")

    # Les dettes se lisent à part, sans jamais se déduire des créances.
    dettes = await balance_agee(d.db, organisation_id=d.org.id, date_arret=date(2026, 5, 31), sens="DETTES")
    assert [(l.compte_numero, l.solde) for l in dettes.lignes] == [("421", Decimal("999"))]

    # Filtre par racine, et cloisonnement entre organisations.
    assert (await balance_agee(
        d.db, organisation_id=d.org.id, date_arret=date(2026, 5, 31), prefixe="41"
    )).lignes == []
    autre_org = await _dossier(db_session)
    assert (await balance_agee(d.db, organisation_id=autre_org.org.id, date_arret=date(2026, 5, 31))).lignes == []
