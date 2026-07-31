"""Tests du moteur de génération automatique (Lot 2).

Couvre : résolution de comptes via mapping (succès + échec bloquant),
génération encaissement/sortie de fonds (structure, journal selon canal),
idempotence (rejeu ne duplique jamais).

⚠️ Ces fonctions ne sont pas encore appelées depuis les endpoints réels
(`encaissements`, `sorties_fonds`) — voir docstring de
`generation_service.py`. Ces tests valident le moteur en isolation.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

import app.db.session  # noqa: F401 — enregistre les event listeners de scoping tenant
from app.core.tenant_context import set_current_tenant_id
from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.compte_bancaire import CompteBancaire
from app.models.organisation import Organisation
from app.modules.comptabilite.models import (
    ComptaCompte,
    ComptaEcriture,
    ComptaExercice,
    ComptaJournal,
    ComptaMappingCompteBancaire,
    ComptaMappingPosteBudgetaire,
    ComptaReferentiel,
    ComptaSociete,
)
from app.modules.comptabilite.services.generation_service import (
    generer_ecriture_encaissement,
    generer_ecriture_sortie_fonds,
    generer_ecriture_transfert_interne,
    resolve_compte_poste_budgetaire,
    resolve_compte_tresorerie,
)


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


def _org(slug: str) -> Organisation:
    now = datetime.now(timezone.utc)
    return Organisation(
        nom=f"Org {slug}", slug=slug, plan_type="ACTIVE", status_abonnement="ACTIVE",
        limite_utilisateurs=10, is_active=True, created_at=now, updated_at=now,
    )


async def _setup(db, organisation_id: int):
    """Société + référentiel (2 comptes) + journaux CA/BQ + exercice ouvert
    + poste budgétaire + compte bancaire (BANK) + caisse (CASH), NON mappés."""
    societe = ComptaSociete(organisation_id=organisation_id, code="SOC", raison_sociale="Société de test")
    referentiel = ComptaReferentiel(
        organisation_id=organisation_id, code="REF", libelle="Référentiel test", type_referentiel="PERSONNALISE",
    )
    db.add_all([societe, referentiel])
    await db.flush()

    compte_charge = ComptaCompte(
        organisation_id=organisation_id, referentiel_id=referentiel.id,
        numero="6132", libelle="Locations", nature="CHARGE", sens_normal="DEBIT",
    )
    compte_produit = ComptaCompte(
        organisation_id=organisation_id, referentiel_id=referentiel.id,
        numero="706", libelle="Services vendus", nature="PRODUIT", sens_normal="CREDIT",
    )
    compte_banque = ComptaCompte(
        organisation_id=organisation_id, referentiel_id=referentiel.id,
        numero="512", libelle="Banque", nature="ACTIF", sens_normal="DEBIT",
    )
    compte_caisse = ComptaCompte(
        organisation_id=organisation_id, referentiel_id=referentiel.id,
        numero="571", libelle="Caisse", nature="ACTIF", sens_normal="DEBIT",
    )
    compte_charge_2 = ComptaCompte(
        organisation_id=organisation_id, referentiel_id=referentiel.id,
        numero="607", libelle="Achats de marchandises", nature="CHARGE", sens_normal="DEBIT",
    )
    db.add_all([compte_charge, compte_produit, compte_banque, compte_caisse, compte_charge_2])
    await db.flush()

    journal_ca = ComptaJournal(
        organisation_id=organisation_id, societe_id=societe.id, code="CA", libelle="Caisse", type_journal="CA",
    )
    journal_bq = ComptaJournal(
        organisation_id=organisation_id, societe_id=societe.id, code="BQ", libelle="Banque", type_journal="BQ",
    )
    journal_od = ComptaJournal(
        organisation_id=organisation_id, societe_id=societe.id, code="OD", libelle="Opérations diverses", type_journal="OD",
    )
    db.add_all([journal_ca, journal_bq, journal_od])
    await db.flush()

    exercice = ComptaExercice(
        organisation_id=organisation_id, societe_id=societe.id, code="2026",
        date_debut=date(2026, 1, 1), date_fin=date(2026, 12, 31),
        referentiel_id=referentiel.id, statut="OUVERT",
    )
    db.add(exercice)
    await db.flush()

    budget_exercice = BudgetExercice(organisation_id=organisation_id, annee=2026, statut=StatutBudget.VOTE)
    db.add(budget_exercice)
    await db.flush()
    # Deux postes distincts : un poste ne mappe jamais qu'à UN SEUL compte
    # comptable (une dépense ne devient pas une recette selon l'opération).
    budget_poste_depense = BudgetPoste(
        organisation_id=organisation_id, exercice_id=budget_exercice.id,
        code="DEP1", libelle="Poste de dépense test", type="DEPENSE",
        montant_prevu=Decimal("1000"),
    )
    budget_poste_recette = BudgetPoste(
        organisation_id=organisation_id, exercice_id=budget_exercice.id,
        code="REC1", libelle="Poste de recette test", type="RECETTE",
        montant_prevu=Decimal("1000"),
    )
    budget_poste_depense_2 = BudgetPoste(
        organisation_id=organisation_id, exercice_id=budget_exercice.id,
        code="DEP2", libelle="Deuxième poste de dépense test", type="DEPENSE",
        montant_prevu=Decimal("1000"),
    )
    db.add_all([budget_poste_depense, budget_poste_recette, budget_poste_depense_2])
    await db.flush()

    compte_bq = CompteBancaire(
        organisation_id=organisation_id, intitule="Banque test", numero_compte="00112233",
        devise="USD", account_type="BANK",
    )
    caisse_bq = CompteBancaire(
        organisation_id=organisation_id, intitule="Caisse test", numero_compte="CAISSE-01",
        devise="USD", account_type="CASH",
    )
    db.add_all([compte_bq, caisse_bq])
    await db.flush()

    return {
        "societe": societe, "exercice": exercice,
        "compte_charge": compte_charge, "compte_produit": compte_produit,
        "compte_banque": compte_banque, "compte_caisse": compte_caisse,
        "compte_charge_2": compte_charge_2,
        "budget_poste": budget_poste_depense, "budget_poste_recette": budget_poste_recette,
        "budget_poste_depense_2": budget_poste_depense_2,
        "compte_bancaire": compte_bq, "caisse": caisse_bq,
    }


async def _map(db, organisation_id: int, ctx: dict):
    db.add_all([
        ComptaMappingPosteBudgetaire(
            organisation_id=organisation_id, budget_poste_id=ctx["budget_poste"].id,
            compte_id=ctx["compte_charge"].id,
        ),
        ComptaMappingPosteBudgetaire(
            organisation_id=organisation_id, budget_poste_id=ctx["budget_poste_recette"].id,
            compte_id=ctx["compte_produit"].id,
        ),
        ComptaMappingPosteBudgetaire(
            organisation_id=organisation_id, budget_poste_id=ctx["budget_poste_depense_2"].id,
            compte_id=ctx["compte_charge_2"].id,
        ),
        ComptaMappingCompteBancaire(
            organisation_id=organisation_id, compte_bancaire_id=ctx["compte_bancaire"].id,
            compte_id=ctx["compte_banque"].id,
        ),
        ComptaMappingCompteBancaire(
            organisation_id=organisation_id, compte_bancaire_id=ctx["caisse"].id,
            compte_id=ctx["compte_caisse"].id,
        ),
    ])
    await db.flush()


# ── Résolution de comptes ─────────────────────────────────────────────────────


async def test_resolve_compte_poste_budgetaire_echoue_si_non_mappe(db_session):
    set_current_tenant_id(None)
    org = _org(f"resolve-poste-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    ctx = await _setup(db_session, org.id)

    with pytest.raises(HTTPException) as exc_info:
        await resolve_compte_poste_budgetaire(db_session, org.id, ctx["budget_poste"].id)
    assert exc_info.value.status_code == 400
    assert "mappé" in exc_info.value.detail

    set_current_tenant_id(None)


async def test_resolve_compte_poste_budgetaire_reussit_si_mappe(db_session):
    set_current_tenant_id(None)
    org = _org(f"resolve-poste-ok-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    ctx = await _setup(db_session, org.id)
    await _map(db_session, org.id, ctx)

    compte = await resolve_compte_poste_budgetaire(db_session, org.id, ctx["budget_poste"].id)
    assert compte.id == ctx["compte_charge"].id

    set_current_tenant_id(None)


async def test_resolve_compte_tresorerie_echoue_si_non_mappe(db_session):
    set_current_tenant_id(None)
    org = _org(f"resolve-tres-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    ctx = await _setup(db_session, org.id)

    with pytest.raises(HTTPException) as exc_info:
        await resolve_compte_tresorerie(db_session, org.id, ctx["societe"], "BANQUE", ctx["compte_bancaire"].id)
    assert exc_info.value.status_code == 400

    set_current_tenant_id(None)


async def test_resolve_compte_tresorerie_caisse_unique_utilise_compte_defaut_societe(db_session):
    """Canal CAISSE sans compte_bancaire_id (caisse unique CaisseCentrale) :
    résolution via `societe.compte_caisse_defaut_id`, pas via un mapping."""
    set_current_tenant_id(None)
    org = _org(f"resolve-caisse-unique-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    ctx = await _setup(db_session, org.id)

    with pytest.raises(HTTPException):
        await resolve_compte_tresorerie(db_session, org.id, ctx["societe"], "CAISSE", None)

    ctx["societe"].compte_caisse_defaut_id = ctx["compte_caisse"].id
    await db_session.flush()

    compte = await resolve_compte_tresorerie(db_session, org.id, ctx["societe"], "CAISSE", None)
    assert compte.id == ctx["compte_caisse"].id

    set_current_tenant_id(None)


# ── Génération encaissement ───────────────────────────────────────────────────


async def test_generer_ecriture_encaissement_banque(db_session):
    set_current_tenant_id(None)
    org = _org(f"gen-enc-bq-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    ctx = await _setup(db_session, org.id)
    await _map(db_session, org.id, ctx)

    encaissement_id = str(uuid.uuid4())
    ecriture = await generer_ecriture_encaissement(
        db_session,
        organisation_id=org.id, encaissement_id=encaissement_id,
        date_operation=date(2026, 6, 1), montant=Decimal("500.00"), devise="USD",
        canal="BANQUE", compte_bancaire_id=ctx["compte_bancaire"].id,
        budget_poste_id=ctx["budget_poste_recette"].id, libelle="Cotisation membre",
    )
    await db_session.commit()

    assert ecriture.statut == "BROUILLON"
    assert ecriture.module_origine == "encaissements"
    assert ecriture.objet_origine_id == encaissement_id

    journal = await db_session.get(ComptaJournal, ecriture.journal_id)
    assert journal.code == "BQ"

    res2 = await db_session.execute(
        select(ComptaEcriture).options(selectinload(ComptaEcriture.lignes)).where(ComptaEcriture.id == ecriture.id)
    )
    reloaded = res2.scalar_one()
    lignes_by_compte = {l.compte_id: l for l in reloaded.lignes}
    assert lignes_by_compte[ctx["compte_banque"].id].debit == Decimal("500.00")
    assert lignes_by_compte[ctx["compte_produit"].id].credit == Decimal("500.00")

    set_current_tenant_id(None)


async def test_generer_ecriture_encaissement_caisse_utilise_journal_ca(db_session):
    set_current_tenant_id(None)
    org = _org(f"gen-enc-ca-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    ctx = await _setup(db_session, org.id)
    await _map(db_session, org.id, ctx)

    ecriture = await generer_ecriture_encaissement(
        db_session,
        organisation_id=org.id, encaissement_id=str(uuid.uuid4()),
        date_operation=date(2026, 6, 1), montant=Decimal("50.00"), devise="USD",
        canal="CAISSE", compte_bancaire_id=ctx["caisse"].id,
        budget_poste_id=ctx["budget_poste_recette"].id, libelle="Cotisation cash",
    )
    await db_session.commit()
    journal = await db_session.get(ComptaJournal, ecriture.journal_id)
    assert journal.code == "CA"

    set_current_tenant_id(None)


async def test_generer_ecriture_encaissement_bloque_sans_poste_budgetaire(db_session):
    set_current_tenant_id(None)
    org = _org(f"gen-enc-nopiste-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    ctx = await _setup(db_session, org.id)
    await _map(db_session, org.id, ctx)

    with pytest.raises(HTTPException) as exc_info:
        await generer_ecriture_encaissement(
            db_session,
            organisation_id=org.id, encaissement_id=str(uuid.uuid4()),
            date_operation=date(2026, 6, 1), montant=Decimal("50.00"), devise="USD",
            canal="CAISSE", compte_bancaire_id=ctx["caisse"].id,
            budget_poste_id=None, libelle="Cotisation sans poste",
        )
    assert exc_info.value.status_code == 400

    await db_session.rollback()
    set_current_tenant_id(None)


async def test_generer_ecriture_encaissement_est_idempotent(db_session):
    set_current_tenant_id(None)
    org = _org(f"gen-enc-idem-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    ctx = await _setup(db_session, org.id)
    await _map(db_session, org.id, ctx)

    encaissement_id = str(uuid.uuid4())
    kwargs = dict(
        organisation_id=org.id, encaissement_id=encaissement_id,
        date_operation=date(2026, 6, 1), montant=Decimal("500.00"), devise="USD",
        canal="BANQUE", compte_bancaire_id=ctx["compte_bancaire"].id,
        budget_poste_id=ctx["budget_poste_recette"].id, libelle="Cotisation membre",
    )
    e1 = await generer_ecriture_encaissement(db_session, **kwargs)
    await db_session.commit()
    e2 = await generer_ecriture_encaissement(db_session, **kwargs)
    await db_session.commit()

    assert e1.id == e2.id

    count_res = await db_session.execute(
        select(ComptaEcriture).where(
            ComptaEcriture.organisation_id == org.id,
            ComptaEcriture.objet_origine_id == encaissement_id,
        )
    )
    assert len(count_res.scalars().all()) == 1

    set_current_tenant_id(None)


async def test_contrainte_unique_db_bloque_un_doublon_d_origine(db_session):
    """Filet de sécurité en base : même en cas de bug applicatif contournant
    `_find_existing_ecriture`, la contrainte unique doit empêcher le doublon."""
    set_current_tenant_id(None)
    org = _org(f"gen-enc-db-unique-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    ctx = await _setup(db_session, org.id)
    await _map(db_session, org.id, ctx)

    origine_id = str(uuid.uuid4())
    for _ in range(2):
        e = ComptaEcriture(
            organisation_id=org.id, societe_id=ctx["societe"].id, exercice_id=ctx["exercice"].id,
            journal_id=(await db_session.execute(
                select(ComptaJournal).where(ComptaJournal.organisation_id == org.id, ComptaJournal.code == "BQ")
            )).scalar_one().id,
            numero=None, date_ecriture=date(2026, 6, 1), libelle="Doublon test",
            statut="BROUILLON", module_origine="encaissements", type_origine="encaissement",
            objet_origine_id=origine_id,
        )
        db_session.add(e)

    with pytest.raises(IntegrityError):
        await db_session.flush()

    await db_session.rollback()
    set_current_tenant_id(None)


# ── Génération sortie de fonds ────────────────────────────────────────────────


async def test_generer_ecriture_sortie_fonds_caisse(db_session):
    set_current_tenant_id(None)
    org = _org(f"gen-sortie-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    ctx = await _setup(db_session, org.id)
    await _map(db_session, org.id, ctx)


    sortie_id = str(uuid.uuid4())
    ecriture = await generer_ecriture_sortie_fonds(
        db_session,
        organisation_id=org.id, sortie_fonds_id=sortie_id,
        date_operation=date(2026, 6, 2), montant=Decimal("80.00"), devise="USD",
        canal="CAISSE", compte_bancaire_id=ctx["caisse"].id,
        budget_poste_id=ctx["budget_poste"].id, libelle="Achat fournitures",
    )
    await db_session.commit()

    assert ecriture.module_origine == "sorties_fonds"
    res2 = await db_session.execute(
        select(ComptaEcriture).options(selectinload(ComptaEcriture.lignes)).where(ComptaEcriture.id == ecriture.id)
    )
    reloaded = res2.scalar_one()
    lignes_by_compte = {l.compte_id: l for l in reloaded.lignes}
    assert lignes_by_compte[ctx["compte_charge"].id].debit == Decimal("80.00")
    assert lignes_by_compte[ctx["compte_caisse"].id].credit == Decimal("80.00")

    set_current_tenant_id(None)


async def test_generer_ecriture_sortie_fonds_est_isolee_par_organisation(db_session):
    """Deux organisations avec le même `sortie_fonds_id` (collision improbable
    mais à couvrir) ne doivent jamais se voir mutuellement."""
    set_current_tenant_id(None)
    org_a = _org(f"gen-sortie-tenant-a-{_suffix()}")
    org_b = _org(f"gen-sortie-tenant-b-{_suffix()}")
    db_session.add_all([org_a, org_b])
    await db_session.flush()

    set_current_tenant_id(org_a.id)
    ctx_a = await _setup(db_session, org_a.id)
    await _map(db_session, org_a.id, ctx_a)

    set_current_tenant_id(org_b.id)
    ctx_b = await _setup(db_session, org_b.id)
    await _map(db_session, org_b.id, ctx_b)

    sortie_id = str(uuid.uuid4())

    set_current_tenant_id(org_a.id)
    ecr_a = await generer_ecriture_sortie_fonds(
        db_session, organisation_id=org_a.id, sortie_fonds_id=sortie_id,
        date_operation=date(2026, 6, 2), montant=Decimal("10.00"), devise="USD",
        canal="CAISSE", compte_bancaire_id=ctx_a["caisse"].id,
        budget_poste_id=ctx_a["budget_poste"].id, libelle="Org A",
    )
    await db_session.commit()

    set_current_tenant_id(org_b.id)
    ecr_b = await generer_ecriture_sortie_fonds(
        db_session, organisation_id=org_b.id, sortie_fonds_id=sortie_id,
        date_operation=date(2026, 6, 2), montant=Decimal("20.00"), devise="USD",
        canal="CAISSE", compte_bancaire_id=ctx_b["caisse"].id,
        budget_poste_id=ctx_b["budget_poste"].id, libelle="Org B",
    )
    await db_session.commit()

    assert ecr_a.id != ecr_b.id
    assert ecr_a.organisation_id == org_a.id
    assert ecr_b.organisation_id == org_b.id

    set_current_tenant_id(None)


# ── Génération sortie de fonds — répartition multi-postes ────────────────────


async def test_generer_ecriture_sortie_fonds_multi_poste(db_session):
    """Ordre de décaissement réparti sur plusieurs postes : une ligne de
    débit par poste, une seule ligne de crédit trésorerie pour le total."""
    set_current_tenant_id(None)
    org = _org(f"gen-sortie-multi-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    ctx = await _setup(db_session, org.id)
    await _map(db_session, org.id, ctx)

    sortie_id = str(uuid.uuid4())
    ecriture = await generer_ecriture_sortie_fonds(
        db_session,
        organisation_id=org.id, sortie_fonds_id=sortie_id,
        date_operation=date(2026, 6, 2), montant=Decimal("100.00"), devise="USD",
        canal="CAISSE", compte_bancaire_id=ctx["caisse"].id,
        budget_poste_id=None, libelle="Décaissement réparti",
        imputations=[
            (ctx["budget_poste"].id, Decimal("60.00")),
            (ctx["budget_poste_depense_2"].id, Decimal("40.00")),
        ],
    )
    await db_session.commit()

    res2 = await db_session.execute(
        select(ComptaEcriture).options(selectinload(ComptaEcriture.lignes)).where(ComptaEcriture.id == ecriture.id)
    )
    reloaded = res2.scalar_one()
    assert len(reloaded.lignes) == 3
    lignes_by_compte = {l.compte_id: l for l in reloaded.lignes}
    assert lignes_by_compte[ctx["compte_charge"].id].debit == Decimal("60.00")
    assert lignes_by_compte[ctx["compte_charge_2"].id].debit == Decimal("40.00")
    assert lignes_by_compte[ctx["compte_caisse"].id].credit == Decimal("100.00")
    total_debit = sum((l.debit for l in reloaded.lignes), Decimal("0"))
    total_credit = sum((l.credit for l in reloaded.lignes), Decimal("0"))
    assert total_debit == total_credit == Decimal("100.00")

    set_current_tenant_id(None)


async def test_generer_ecriture_sortie_fonds_multi_poste_montant_incoherent_leve_erreur(db_session):
    set_current_tenant_id(None)
    org = _org(f"gen-sortie-multi-err-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    ctx = await _setup(db_session, org.id)
    await _map(db_session, org.id, ctx)

    with pytest.raises(HTTPException) as exc_info:
        await generer_ecriture_sortie_fonds(
            db_session,
            organisation_id=org.id, sortie_fonds_id=str(uuid.uuid4()),
            date_operation=date(2026, 6, 2), montant=Decimal("100.00"), devise="USD",
            canal="CAISSE", compte_bancaire_id=ctx["caisse"].id,
            budget_poste_id=None, libelle="Répartition incohérente",
            imputations=[
                (ctx["budget_poste"].id, Decimal("60.00")),
                (ctx["budget_poste_depense_2"].id, Decimal("30.00")),
            ],
        )
    assert exc_info.value.status_code == 400

    await db_session.rollback()
    set_current_tenant_id(None)


# ── Génération transfert interne (versement banque / approvisionnement caisse) ──


async def test_generer_ecriture_transfert_interne_versement_banque(db_session):
    """Caisse -> banque : débit compte bancaire destination, crédit caisse
    unique (via `compte_caisse_defaut_id`), journal OD."""
    set_current_tenant_id(None)
    org = _org(f"gen-transfert-versement-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    ctx = await _setup(db_session, org.id)
    await _map(db_session, org.id, ctx)
    ctx["societe"].compte_caisse_defaut_id = ctx["compte_caisse"].id
    await db_session.flush()

    sortie_id = str(uuid.uuid4())
    ecriture = await generer_ecriture_transfert_interne(
        db_session,
        organisation_id=org.id, sortie_fonds_id=sortie_id,
        date_operation=date(2026, 6, 3), montant=Decimal("200.00"), devise="USD",
        compte_origine_bancaire_id=None, compte_destination_bancaire_id=ctx["compte_bancaire"].id,
        libelle="Versement à la banque",
    )
    await db_session.commit()

    assert ecriture.type_origine == "transfert_interne"
    journal = await db_session.get(ComptaJournal, ecriture.journal_id)
    assert journal.code == "OD"

    res2 = await db_session.execute(
        select(ComptaEcriture).options(selectinload(ComptaEcriture.lignes)).where(ComptaEcriture.id == ecriture.id)
    )
    reloaded = res2.scalar_one()
    lignes_by_compte = {l.compte_id: l for l in reloaded.lignes}
    assert lignes_by_compte[ctx["compte_banque"].id].debit == Decimal("200.00")
    assert lignes_by_compte[ctx["compte_caisse"].id].credit == Decimal("200.00")

    set_current_tenant_id(None)


async def test_generer_ecriture_transfert_interne_approvisionnement_caisse(db_session):
    """Banque -> caisse : débit caisse unique, crédit compte bancaire origine."""
    set_current_tenant_id(None)
    org = _org(f"gen-transfert-appro-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    ctx = await _setup(db_session, org.id)
    await _map(db_session, org.id, ctx)
    ctx["societe"].compte_caisse_defaut_id = ctx["compte_caisse"].id
    await db_session.flush()

    ecriture = await generer_ecriture_transfert_interne(
        db_session,
        organisation_id=org.id, sortie_fonds_id=str(uuid.uuid4()),
        date_operation=date(2026, 6, 4), montant=Decimal("75.00"), devise="USD",
        compte_origine_bancaire_id=ctx["compte_bancaire"].id, compte_destination_bancaire_id=None,
        libelle="Approvisionnement caisse",
    )
    await db_session.commit()

    res2 = await db_session.execute(
        select(ComptaEcriture).options(selectinload(ComptaEcriture.lignes)).where(ComptaEcriture.id == ecriture.id)
    )
    reloaded = res2.scalar_one()
    lignes_by_compte = {l.compte_id: l for l in reloaded.lignes}
    assert lignes_by_compte[ctx["compte_caisse"].id].debit == Decimal("75.00")
    assert lignes_by_compte[ctx["compte_banque"].id].credit == Decimal("75.00")

    set_current_tenant_id(None)


async def test_generer_ecriture_transfert_interne_est_idempotent(db_session):
    set_current_tenant_id(None)
    org = _org(f"gen-transfert-idem-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    ctx = await _setup(db_session, org.id)
    await _map(db_session, org.id, ctx)
    ctx["societe"].compte_caisse_defaut_id = ctx["compte_caisse"].id
    await db_session.flush()

    sortie_id = str(uuid.uuid4())
    kwargs = dict(
        organisation_id=org.id, sortie_fonds_id=sortie_id,
        date_operation=date(2026, 6, 3), montant=Decimal("200.00"), devise="USD",
        compte_origine_bancaire_id=None, compte_destination_bancaire_id=ctx["compte_bancaire"].id,
        libelle="Versement à la banque",
    )
    e1 = await generer_ecriture_transfert_interne(db_session, **kwargs)
    await db_session.commit()
    e2 = await generer_ecriture_transfert_interne(db_session, **kwargs)
    await db_session.commit()

    assert e1.id == e2.id

    set_current_tenant_id(None)
