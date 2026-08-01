"""Lot 3 — faits générateurs restants et reprise d'historique.

Couvre :
- transfert interne autonome (module Transferts) : la trésorerie bougeait
  sans produire la moindre écriture avant ce lot ;
- paie : constatation de la charge au journal SAL, une écriture par devise ;
- annulation : brouillon annulé sur place, écriture validée contre-passée ;
- reprise d'historique : script de backfill, idempotent et non bloquant ;
- non-régression : une organisation sans comptabilité n'est jamais affectée.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.hr import HREmployee, HRPayrollEntry, HRSalarySlip
from app.models.organisation import Organisation
from app.models.service import Service
from app.models.user import User
from app.modules.comptabilite.models import (
    RUBRIQUES_TECHNIQUES,
    ComptaCompte,
    ComptaEcriture,
    ComptaMappingRubrique,
)
from app.modules.comptabilite.services.ecriture_service import valider_ecriture
from app.modules.comptabilite.services.generation_service import generer_ecriture_paie
from app.modules.comptabilite.services.mapping_defaut_service import generer_mappings_par_defaut
from app.modules.comptabilite.services.setup_service import setup_comptabilite
from app.schemas.payment import EncaissementCancelPayload
from app.schemas.sortie_fonds import SortieFondsCreate, SortieFondsStatusUpdate
from app.schemas.transfert import TransfertInterneCreate


class _FakeRequest:
    headers: dict = {}
    client = None


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


async def _org(db) -> Organisation:
    org = Organisation(nom="Lot3 Test", slug=f"lot3-{_suffix()}", is_active=True)
    db.add(org)
    await db.flush()
    return org


async def _admin(db, org) -> User:
    user = User(id=uuid.uuid4(), email=f"a{_suffix()}@ex.com", role="admin", organisation_id=org.id)
    db.add(user)
    await db.flush()
    return user


async def _caisse(db, org, *, usd=Decimal("0")) -> CaisseCentrale:
    caisse = CaisseCentrale(
        organisation_id=org.id, solde_usd=usd, solde_cdf=Decimal("0"), est_ouverte=True
    )
    db.add(caisse)
    await db.flush()
    return caisse


async def _banque(db, org, *, solde=Decimal("0")) -> CompteBancaire:
    compte = CompteBancaire(
        organisation_id=org.id, intitule="Compte banque", numero_compte=f"TEST-{_suffix()}",
        devise="USD", solde_initial=solde, solde_actuel=solde, is_active=True, account_type="BANK",
    )
    db.add(compte)
    await db.flush()
    return compte


async def _service(db, org) -> Service:
    service = Service(organisation_id=org.id, code=f"S{_suffix()[:4]}", libelle="Service", is_active=True)
    db.add(service)
    await db.flush()
    return service


async def _depense_poste(db, org) -> tuple[BudgetPoste, BudgetExercice]:
    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
    db.add(exercice)
    await db.flush()
    poste = BudgetPoste(
        organisation_id=org.id, exercice_id=exercice.id, code=f"DEP-{_suffix()}",
        libelle="Poste dépense", type="DEPENSE", active=True,
        montant_prevu=Decimal("100000"), montant_engage=0, montant_paye=0, is_deleted=False,
    )
    db.add(poste)
    await db.flush()
    return poste, exercice


async def _recette_poste(db, org, exercice) -> BudgetPoste:
    poste = BudgetPoste(
        organisation_id=org.id, exercice_id=exercice.id, code=f"REC-{_suffix()}",
        libelle="Poste recette", type="RECETTE", active=True,
        montant_prevu=Decimal("100000"), montant_engage=0, montant_paye=0, is_deleted=False,
    )
    db.add(poste)
    await db.flush()
    return poste


async def _activer_comptabilite(db, org, *, mapper: bool = True) -> None:
    await setup_comptabilite(
        db, organisation_id=org.id, organisation_nom=org.nom, type_referentiel="SYSCEBNL",
        exercice_date_debut=date(2026, 1, 1), exercice_date_fin=date(2026, 12, 31),
    )
    if mapper:
        await generer_mappings_par_defaut(db, organisation_id=org.id)
    await db.flush()


async def _ecriture_pour(db, module_origine, type_origine, objet_origine_id) -> ComptaEcriture | None:
    res = await db.execute(
        select(ComptaEcriture)
        .options(selectinload(ComptaEcriture.lignes))
        .where(
            ComptaEcriture.module_origine == module_origine,
            ComptaEcriture.type_origine == type_origine,
            ComptaEcriture.objet_origine_id == str(objet_origine_id),
        )
    )
    return res.scalar_one_or_none()


async def _numero_compte(db, compte_id: int) -> str:
    compte = await db.get(ComptaCompte, compte_id)
    return compte.numero


def _totaux(ecriture) -> tuple[Decimal, Decimal]:
    return (
        sum((l.debit for l in ecriture.lignes), Decimal("0")),
        sum((l.credit for l in ecriture.lignes), Decimal("0")),
    )


# ── Mappings de rubriques ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mapping_defaut_couvre_toutes_les_rubriques_techniques(db_session):
    """Toute rubrique déclarée doit être mappée par le provisionnement, sinon
    le fait générateur correspondant échouerait dès la première utilisation."""
    db = db_session
    org = await _org(db)
    await _activer_comptabilite(db, org)

    res = await db.execute(
        select(ComptaMappingRubrique.code_rubrique).where(
            ComptaMappingRubrique.organisation_id == org.id
        )
    )
    assert {row for row, in res.all()} == set(RUBRIQUES_TECHNIQUES)


# ── Transfert interne autonome (module Transferts) ──────────────────────────


@pytest.mark.asyncio
async def test_transfert_sans_comptabilite_ne_genere_rien(db_session):
    db = db_session
    org = await _org(db)
    await _caisse(db, org, usd=Decimal("500"))
    banque = await _banque(db, org)
    await db.commit()
    user = await _admin(db, org)

    from app.api.v1.endpoints.transferts import create_transfert

    payload = TransfertInterneCreate(
        source_type="CAISSE", destination_type="BANQUE", destination_id=banque.id,
        montant=Decimal("200"), devise="USD", reference="Versement du jour",
    )
    transfert = await create_transfert(payload=payload, user=user, tenant_id=org.id, db=db)

    assert await _ecriture_pour(db, "transferts", "transfert_interne", transfert.id) is None
    await db.refresh(banque)
    assert Decimal(str(banque.solde_actuel)) == Decimal("200")


@pytest.mark.asyncio
async def test_transfert_caisse_vers_banque_genere_ecriture(db_session):
    db = db_session
    org = await _org(db)
    await _caisse(db, org, usd=Decimal("500"))
    banque = await _banque(db, org)
    await _activer_comptabilite(db, org)
    await db.commit()
    user = await _admin(db, org)

    from app.api.v1.endpoints.transferts import create_transfert

    payload = TransfertInterneCreate(
        source_type="CAISSE", destination_type="BANQUE", destination_id=banque.id,
        montant=Decimal("200"), devise="USD", reference="Versement du jour",
    )
    transfert = await create_transfert(payload=payload, user=user, tenant_id=org.id, db=db)

    ecriture = await _ecriture_pour(db, "transferts", "transfert_interne", transfert.id)
    assert ecriture is not None
    assert ecriture.statut == "BROUILLON"
    total_debit, total_credit = _totaux(ecriture)
    assert total_debit == total_credit == Decimal("200")

    # Débit = destination (banque 512), crédit = origine (caisse 571).
    ligne_debit = next(l for l in ecriture.lignes if l.debit > 0)
    ligne_credit = next(l for l in ecriture.lignes if l.credit > 0)
    assert await _numero_compte(db, ligne_debit.compte_id) == "512"
    assert await _numero_compte(db, ligne_credit.compte_id) == "571"


# ── Paie ────────────────────────────────────────────────────────────────────


async def _employe(db, org) -> HREmployee:
    employe = HREmployee(
        tenant_id=org.id, matricule=f"M-{_suffix()}", nom="Employé test", statut="actif"
    )
    db.add(employe)
    await db.flush()
    return employe


async def _run_de_paie(db, org, *, slips: list[tuple[Decimal, Decimal, Decimal, str]]) -> HRPayrollEntry:
    """slips : (salaire_base, cnss, ipr, devise) — le net est déduit."""
    entry = HRPayrollEntry(tenant_id=org.id, mois=3, annee=2026, statut="brouillon")
    db.add(entry)
    await db.flush()
    for base, cnss, ipr, devise in slips:
        employe = await _employe(db, org)
        db.add(
            HRSalarySlip(
                tenant_id=org.id, payroll_entry_id=entry.id, employee_id=employe.id,
                salaire_base=base, total_primes=Decimal("0"), ipr=ipr, cnss_salarie=cnss,
                total_retenues=cnss + ipr, net_a_payer=base - cnss - ipr, devise=devise,
                statut="brouillon",
            )
        )
    entry.nb_bulletins = len(slips)
    await db.flush()
    return entry


@pytest.mark.asyncio
async def test_paie_sans_comptabilite_ne_genere_rien(db_session):
    db = db_session
    org = await _org(db)
    entry = await _run_de_paie(db, org, slips=[(Decimal("1000"), Decimal("50"), Decimal("100"), "USD")])
    await db.commit()
    user = await _admin(db, org)

    from app.api.v1.endpoints.hr import validate_payroll_entry

    await validate_payroll_entry(entry_id=entry.id, db=db, user=user, tenant_id=org.id)

    assert await _ecriture_pour(db, "hr", "paie", f"{entry.id}:USD") is None
    await db.refresh(entry)
    assert entry.statut == "validé"


@pytest.mark.asyncio
async def test_paie_genere_ecriture_sal_equilibree(db_session):
    db = db_session
    org = await _org(db)
    await _activer_comptabilite(db, org)
    entry = await _run_de_paie(
        db, org,
        slips=[
            (Decimal("1000"), Decimal("50"), Decimal("100"), "USD"),
            (Decimal("600"), Decimal("30"), Decimal("40"), "USD"),
        ],
    )
    await db.commit()
    user = await _admin(db, org)

    from app.api.v1.endpoints.hr import validate_payroll_entry

    await validate_payroll_entry(entry_id=entry.id, db=db, user=user, tenant_id=org.id)

    ecriture = await _ecriture_pour(db, "hr", "paie", f"{entry.id}:USD")
    assert ecriture is not None
    assert ecriture.statut == "BROUILLON"
    # Charge rattachée au mois de paie, pas au jour de la validation.
    assert ecriture.date_ecriture == date(2026, 3, 31)

    total_debit, total_credit = _totaux(ecriture)
    assert total_debit == total_credit == Decimal("1600")

    par_compte = {}
    for ligne in ecriture.lignes:
        par_compte[await _numero_compte(db, ligne.compte_id)] = (ligne.debit, ligne.credit)
    assert par_compte["661"] == (Decimal("1600"), Decimal("0"))   # charges de personnel (brut)
    assert par_compte["421"] == (Decimal("0"), Decimal("1380"))   # net dû au personnel
    assert par_compte["431"] == (Decimal("0"), Decimal("80"))     # CNSS salarié
    assert par_compte["447"] == (Decimal("0"), Decimal("140"))    # IPR retenu


@pytest.mark.asyncio
async def test_paie_multi_devise_genere_une_ecriture_par_devise(db_session):
    db = db_session
    org = await _org(db)
    await _activer_comptabilite(db, org)
    entry = await _run_de_paie(
        db, org,
        slips=[
            (Decimal("1000"), Decimal("50"), Decimal("100"), "USD"),
            (Decimal("500000"), Decimal("0"), Decimal("0"), "CDF"),
        ],
    )
    await db.commit()
    user = await _admin(db, org)

    from app.api.v1.endpoints.hr import validate_payroll_entry

    await validate_payroll_entry(entry_id=entry.id, db=db, user=user, tenant_id=org.id)

    ecriture_usd = await _ecriture_pour(db, "hr", "paie", f"{entry.id}:USD")
    ecriture_cdf = await _ecriture_pour(db, "hr", "paie", f"{entry.id}:CDF")
    assert ecriture_usd is not None and ecriture_cdf is not None
    assert ecriture_usd.devise == "USD" and ecriture_cdf.devise == "CDF"
    # Aucune retenue en CDF : pas de ligne au montant nul (interdite en base).
    assert len(ecriture_cdf.lignes) == 2
    assert _totaux(ecriture_cdf) == (Decimal("500000"), Decimal("500000"))


@pytest.mark.asyncio
async def test_paie_est_idempotente(db_session):
    """Un rejeu du fait générateur ne peut pas produire une seconde écriture."""
    db = db_session
    org = await _org(db)
    await _activer_comptabilite(db, org)
    entry = await _run_de_paie(db, org, slips=[(Decimal("1000"), Decimal("50"), Decimal("100"), "USD")])
    await db.flush()

    commun = dict(
        organisation_id=org.id, payroll_entry_id=entry.id, devise="USD",
        date_operation=date(2026, 3, 31), total_brut=Decimal("1000"), total_net=Decimal("850"),
        total_cnss=Decimal("50"), total_ipr=Decimal("100"), libelle="Paie 03/2026",
    )
    premiere = await generer_ecriture_paie(db, **commun)
    seconde = await generer_ecriture_paie(db, **commun)
    assert premiere.id == seconde.id


# ── Annulation : contre-passation ───────────────────────────────────────────


async def _creer_sortie(db, org, user, poste, service, monkeypatch, montant=Decimal("120")):
    async def fake_num(*a, **k):
        return f"PAY-{_suffix()}"

    monkeypatch.setattr("app.api.v1.endpoints.sorties_fonds.generate_document_number", fake_num)
    from app.api.v1.endpoints.sorties_fonds import create_sortie_fonds

    payload = SortieFondsCreate(
        type_sortie="autre", montant_paye=montant, mode_paiement="cash",
        devise="USD", canal="CAISSE", motif="Achat fournitures", beneficiaire="Fournisseur",
        service_id=service.id, budget_poste_id=poste.id,
    )
    return await create_sortie_fonds(
        payload=payload, request=_FakeRequest(), user=user, tenant_id=org.id, db=db
    )


@pytest.mark.asyncio
async def test_annulation_sortie_annule_le_brouillon_sur_place(db_session, monkeypatch):
    """Un brouillon n'a jamais atteint le Grand Livre : le contre-passer
    polluerait le journal de deux écritures qui s'annulent."""
    db = db_session
    org = await _org(db)
    poste, _ = await _depense_poste(db, org)
    service = await _service(db, org)
    await _caisse(db, org, usd=Decimal("500"))
    await _activer_comptabilite(db, org)
    await db.commit()
    user = await _admin(db, org)

    monkeypatch.setattr(
        "app.api.v1.endpoints.sorties_fonds._user_has_permission",
        lambda *a, **k: _true(),
    )
    sortie = await _creer_sortie(db, org, user, poste, service, monkeypatch)

    from app.api.v1.endpoints.sorties_fonds import update_sortie_statut

    await update_sortie_statut(
        sortie_id=str(sortie.id),
        payload=SortieFondsStatusUpdate(statut="ANNULEE", motif_annulation="Erreur de saisie"),
        request=_FakeRequest(), user=user, tenant_id=org.id, db=db,
    )

    ecriture = await _ecriture_pour(db, "sorties_fonds", "sortie_fonds", sortie.id)
    assert ecriture is not None
    assert ecriture.statut == "ANNULEE"
    assert ecriture.motif_annulation == "Erreur de saisie"
    # Aucune contre-passation créée pour un brouillon.
    res = await db.execute(
        select(ComptaEcriture).where(
            ComptaEcriture.organisation_id == org.id,
            ComptaEcriture.contrepasse_ecriture_id == ecriture.id,
        )
    )
    assert res.scalar_one_or_none() is None


async def _true() -> bool:
    return True


@pytest.mark.asyncio
async def test_annulation_sortie_contrepasse_une_ecriture_validee(db_session, monkeypatch):
    db = db_session
    org = await _org(db)
    poste, _ = await _depense_poste(db, org)
    service = await _service(db, org)
    await _caisse(db, org, usd=Decimal("500"))
    await _activer_comptabilite(db, org)
    await db.commit()
    user = await _admin(db, org)

    monkeypatch.setattr(
        "app.api.v1.endpoints.sorties_fonds._user_has_permission",
        lambda *a, **k: _true(),
    )
    sortie = await _creer_sortie(db, org, user, poste, service, monkeypatch)

    ecriture = await _ecriture_pour(db, "sorties_fonds", "sortie_fonds", sortie.id)
    await valider_ecriture(db, ecriture_id=ecriture.id, organisation_id=org.id, user_id=user.id)
    assert ecriture.statut == "VALIDEE"

    from app.api.v1.endpoints.sorties_fonds import update_sortie_statut

    await update_sortie_statut(
        sortie_id=str(sortie.id),
        payload=SortieFondsStatusUpdate(statut="ANNULEE", motif_annulation="Paiement contesté"),
        request=_FakeRequest(), user=user, tenant_id=org.id, db=db,
    )

    await db.refresh(ecriture)
    assert ecriture.statut == "ANNULEE"

    res = await db.execute(
        select(ComptaEcriture)
        .options(selectinload(ComptaEcriture.lignes))
        .where(
            ComptaEcriture.organisation_id == org.id,
            ComptaEcriture.contrepasse_ecriture_id == ecriture.id,
        )
    )
    contrepassation = res.scalar_one_or_none()
    assert contrepassation is not None
    debit_cp, credit_cp = _totaux(contrepassation)
    debit_origine, credit_origine = _totaux(ecriture)
    # Sens inversés, montants identiques.
    assert debit_cp == credit_origine and credit_cp == debit_origine


@pytest.mark.asyncio
async def test_annulation_encaissement_annule_son_ecriture(db_session, monkeypatch):
    db = db_session
    org = await _org(db)
    _, exercice_budget = await _depense_poste(db, org)
    poste_recette = await _recette_poste(db, org, exercice_budget)
    await _caisse(db, org, usd=Decimal("0"))
    await _activer_comptabilite(db, org)
    await db.commit()
    user = await _admin(db, org)

    from app.models.encaissement import Encaissement

    encaissement = Encaissement(
        organisation_id=org.id, numero_recu=f"ND-{_suffix()}", est_proforma=False,
        type_client="autre", client_nom="Adhérent", libelle="Cotisation 2026",
        montant=Decimal("300"), montant_total=Decimal("300"), montant_paye=Decimal("300"),
        montant_percu=Decimal("300"), devise_perception="USD", canal="CAISSE",
        budget_poste_id=poste_recette.id, statut_paiement="complet", mode_paiement="cash",
        date_encaissement=datetime(2026, 3, 10, tzinfo=timezone.utc),
        date_paiement=datetime(2026, 3, 10, tzinfo=timezone.utc), created_by=user.id,
    )
    db.add(encaissement)
    await db.flush()

    from app.modules.comptabilite.services.generation_service import generer_ecriture_encaissement

    await generer_ecriture_encaissement(
        db, organisation_id=org.id, encaissement_id=str(encaissement.id),
        date_operation=date(2026, 3, 10), montant=Decimal("300"), devise="USD",
        canal="CAISSE", compte_bancaire_id=None, budget_poste_id=poste_recette.id,
        libelle=encaissement.libelle, created_by=user.id,
    )
    await db.commit()

    monkeypatch.setattr(
        "app.api.v1.endpoints.encaissements._user_has_permission",
        lambda *a, **k: _true(),
    )
    from app.api.v1.endpoints.encaissements import cancel_encaissement_operation

    await cancel_encaissement_operation(
        encaissement_id=str(encaissement.id),
        payload=EncaissementCancelPayload(motif_annulation="Chèque sans provision"),
        request=_FakeRequest(), user=user, tenant_id=org.id, db=db,
    )

    ecriture = await _ecriture_pour(db, "encaissements", "encaissement", encaissement.id)
    assert ecriture is not None
    assert ecriture.statut == "ANNULEE"


# ── Reprise d'historique ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reprise_historique_rattrape_les_operations_anterieures(db_session, monkeypatch):
    """Scénario réel : l'organisation travaille d'abord sans comptabilité,
    l'active ensuite — l'historique doit pouvoir être reconstitué."""
    db = db_session
    org = await _org(db)
    poste, exercice_budget = await _depense_poste(db, org)
    service = await _service(db, org)
    await _caisse(db, org, usd=Decimal("1000"))
    banque = await _banque(db, org)
    await db.commit()
    user = await _admin(db, org)

    # 1. Opérations saisies AVANT l'activation : aucune écriture générée.
    sortie = await _creer_sortie(db, org, user, poste, service, monkeypatch)

    from app.api.v1.endpoints.transferts import create_transfert

    transfert = await create_transfert(
        payload=TransfertInterneCreate(
            source_type="CAISSE", destination_type="BANQUE", destination_id=banque.id,
            montant=Decimal("100"), devise="USD", reference="Versement",
        ),
        user=user, tenant_id=org.id, db=db,
    )
    assert await _ecriture_pour(db, "sorties_fonds", "sortie_fonds", sortie.id) is None
    assert await _ecriture_pour(db, "transferts", "transfert_interne", transfert.id) is None

    # 2. Activation de la comptabilité, puis reprise.
    await _activer_comptabilite(db, org)
    await db.commit()

    from scripts.backfill_compta_ecritures_historique import reprendre_organisation

    rapport = await reprendre_organisation(db, organisation_id=org.id, depuis=None)
    await db.commit()

    assert rapport.echecs == []
    assert rapport.creees == 2
    assert await _ecriture_pour(db, "sorties_fonds", "sortie_fonds", sortie.id) is not None
    assert await _ecriture_pour(db, "transferts", "transfert_interne", transfert.id) is not None

    # 3. Rejeu : idempotent, aucune écriture supplémentaire.
    rapport_rejeu = await reprendre_organisation(db, organisation_id=org.id, depuis=None)
    assert rapport_rejeu.creees == 0
    assert rapport_rejeu.deja_en_compta == 2


@pytest.mark.asyncio
async def test_reprise_historique_ne_bloque_pas_sur_un_mapping_manquant(db_session, monkeypatch):
    """Contrairement à la saisie en ligne (échec bloquant), la reprise
    rapporte l'opération non reprise et poursuit les suivantes."""
    db = db_session
    org = await _org(db)
    poste, _ = await _depense_poste(db, org)
    service = await _service(db, org)
    await _caisse(db, org, usd=Decimal("1000"))
    banque = await _banque(db, org)
    await db.commit()
    user = await _admin(db, org)

    sortie = await _creer_sortie(db, org, user, poste, service, monkeypatch)

    from app.api.v1.endpoints.transferts import create_transfert

    transfert = await create_transfert(
        payload=TransfertInterneCreate(
            source_type="CAISSE", destination_type="BANQUE", destination_id=banque.id,
            montant=Decimal("100"), devise="USD", reference="Versement",
        ),
        user=user, tenant_id=org.id, db=db,
    )

    # Comptabilité activée SANS mapping : le poste budgétaire de la sortie
    # n'est pas résolvable, la trésorerie du transfert non plus.
    await _activer_comptabilite(db, org, mapper=False)
    await db.commit()

    from scripts.backfill_compta_ecritures_historique import reprendre_organisation

    rapport = await reprendre_organisation(db, organisation_id=org.id, depuis=None)

    assert rapport.creees == 0
    assert len(rapport.echecs) == 2
    assert await _ecriture_pour(db, "sorties_fonds", "sortie_fonds", sortie.id) is None
    assert await _ecriture_pour(db, "transferts", "transfert_interne", transfert.id) is None


@pytest.mark.asyncio
async def test_reprise_historique_respecte_la_date_de_depart(db_session, monkeypatch):
    db = db_session
    org = await _org(db)
    poste, _ = await _depense_poste(db, org)
    service = await _service(db, org)
    await _caisse(db, org, usd=Decimal("1000"))
    await _activer_comptabilite(db, org)
    await db.commit()
    user = await _admin(db, org)

    sortie = await _creer_sortie(db, org, user, poste, service, monkeypatch)
    # L'écriture générée en ligne est écartée pour isoler l'effet du filtre.
    ecriture = await _ecriture_pour(db, "sorties_fonds", "sortie_fonds", sortie.id)
    await db.delete(ecriture)
    # `create_sortie_fonds` retourne un schéma de sortie : la date doit être
    # antidatée sur la ligne en base, pas sur l'objet de réponse.
    from app.models.sortie_fonds import SortieFonds

    sortie_db = await db.get(SortieFonds, uuid.UUID(str(sortie.id)))
    sortie_db.date_paiement = datetime(2026, 1, 15, tzinfo=timezone.utc)
    await db.flush()

    from scripts.backfill_compta_ecritures_historique import reprendre_organisation

    rapport = await reprendre_organisation(db, organisation_id=org.id, depuis=date(2026, 6, 1))
    assert rapport.creees == 0
    assert await _ecriture_pour(db, "sorties_fonds", "sortie_fonds", sortie.id) is None

    rapport = await reprendre_organisation(db, organisation_id=org.id, depuis=date(2026, 1, 1))
    assert rapport.creees == 1
    assert await _ecriture_pour(db, "sorties_fonds", "sortie_fonds", sortie.id) is not None
