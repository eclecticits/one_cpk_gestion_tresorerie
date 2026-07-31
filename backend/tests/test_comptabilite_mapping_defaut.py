"""Tests du mapping par défaut (bridge pragmatique débloquant la génération
automatique sans écran de paramétrage complet).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

import app.db.session  # noqa: F401 — enregistre les event listeners de scoping tenant
from app.core.tenant_context import set_current_tenant_id
from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.compte_bancaire import CompteBancaire
from app.models.organisation import Organisation
from app.modules.comptabilite.models import ComptaMappingCompteBancaire, ComptaMappingPosteBudgetaire, ComptaSociete
from app.modules.comptabilite.services.generation_service import (
    generer_ecriture_encaissement,
    generer_ecriture_sortie_fonds,
)
from app.modules.comptabilite.services.mapping_defaut_service import generer_mappings_par_defaut
from app.modules.comptabilite.services.setup_service import setup_comptabilite


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


def _org(slug: str) -> Organisation:
    now = datetime.now(timezone.utc)
    return Organisation(
        nom=f"Org {slug}", slug=slug, plan_type="ACTIVE", status_abonnement="ACTIVE",
        limite_utilisateurs=10, is_active=True, created_at=now, updated_at=now,
    )


async def _setup_via_provisioning(db, organisation_id: int, type_referentiel: str = "SYSCEBNL"):
    """Provisionne comme le ferait l'écran d'activation (société + plan réel
    + journaux), puis ajoute un poste dépense, un poste recette, une banque
    et une caisse nommée — tous NON mappés, comme en conditions réelles."""
    result = await setup_comptabilite(
        db, organisation_id=organisation_id, organisation_nom="Org test",
        type_referentiel=type_referentiel,
        exercice_date_debut=date(2026, 1, 1), exercice_date_fin=date(2026, 12, 31),
    )

    budget_exercice = BudgetExercice(organisation_id=organisation_id, annee=2026, statut=StatutBudget.VOTE)
    db.add(budget_exercice)
    await db.flush()
    poste_depense = BudgetPoste(
        organisation_id=organisation_id, exercice_id=budget_exercice.id,
        code="DEP1", libelle="Fournitures", type="DEPENSE", montant_prevu=Decimal("500"),
    )
    poste_recette = BudgetPoste(
        organisation_id=organisation_id, exercice_id=budget_exercice.id,
        code="REC1", libelle="Cotisations", type="RECETTE", montant_prevu=Decimal("2000"),
    )
    db.add_all([poste_depense, poste_recette])

    compte_banque = CompteBancaire(
        organisation_id=organisation_id, intitule="Banque test", numero_compte="00998877",
        devise="USD", account_type="BANK",
    )
    db.add(compte_banque)
    await db.flush()

    return {**result, "poste_depense": poste_depense, "poste_recette": poste_recette, "compte_banque": compte_banque}


async def test_generer_mappings_par_defaut_mappe_postes_et_comptes(db_session):
    set_current_tenant_id(None)
    org = _org(f"mapdef-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    ctx = await _setup_via_provisioning(db_session, org.id)

    resume = await generer_mappings_par_defaut(db_session, organisation_id=org.id)
    await db_session.commit()

    assert resume["postes_mappes"] == 2
    assert resume["comptes_bancaires_mappes"] == 1
    assert resume["compte_caisse_defaut_id"] is not None

    societe_res = await db_session.get(ComptaSociete, ctx["societe_id"])
    assert societe_res.compte_caisse_defaut_id == resume["compte_caisse_defaut_id"]

    set_current_tenant_id(None)


async def test_generer_mappings_par_defaut_est_idempotent(db_session):
    set_current_tenant_id(None)
    org = _org(f"mapdef-idem-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    ctx = await _setup_via_provisioning(db_session, org.id)

    await generer_mappings_par_defaut(db_session, organisation_id=org.id)
    await db_session.commit()
    resume2 = await generer_mappings_par_defaut(db_session, organisation_id=org.id)
    await db_session.commit()

    # Rien à mapper la deuxième fois : tout est déjà couvert.
    assert resume2["postes_mappes"] == 0
    assert resume2["comptes_bancaires_mappes"] == 0

    from sqlalchemy import select
    postes_res = await db_session.execute(
        select(ComptaMappingPosteBudgetaire).where(ComptaMappingPosteBudgetaire.organisation_id == org.id)
    )
    assert len(postes_res.scalars().all()) == 2

    set_current_tenant_id(None)


async def test_generer_mappings_par_defaut_respecte_un_mapping_deja_configure(db_session):
    """Un mapping déjà posé manuellement (granularité fine) n'est jamais écrasé."""
    set_current_tenant_id(None)
    org = _org(f"mapdef-preserve-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    ctx = await _setup_via_provisioning(db_session, org.id)

    from app.modules.comptabilite.services.plans_comptables import seeder_referentiel
    from sqlalchemy import select
    from app.modules.comptabilite.models import ComptaCompte, ComptaReferentiel

    ref_res = await db_session.execute(
        select(ComptaReferentiel).where(
            ComptaReferentiel.organisation_id == org.id, ComptaReferentiel.is_default.is_(True)
        )
    )
    referentiel = ref_res.scalar_one()
    compte_specifique_res = await db_session.execute(
        select(ComptaCompte).where(ComptaCompte.referentiel_id == referentiel.id, ComptaCompte.numero == "6132")
    )
    compte_specifique = compte_specifique_res.scalar_one()

    db_session.add(
        ComptaMappingPosteBudgetaire(
            organisation_id=org.id, budget_poste_id=ctx["poste_depense"].id, compte_id=compte_specifique.id,
        )
    )
    await db_session.flush()

    await generer_mappings_par_defaut(db_session, organisation_id=org.id)
    await db_session.commit()

    mapping_res = await db_session.execute(
        select(ComptaMappingPosteBudgetaire).where(
            ComptaMappingPosteBudgetaire.organisation_id == org.id,
            ComptaMappingPosteBudgetaire.budget_poste_id == ctx["poste_depense"].id,
        )
    )
    mapping = mapping_res.scalar_one()
    assert mapping.compte_id == compte_specifique.id  # inchangé, pas écrasé par le générique

    set_current_tenant_id(None)


async def test_generation_ecriture_fonctionne_de_bout_en_bout_apres_mapping_par_defaut(db_session):
    """Le scénario réel : provisionner, mapper par défaut, puis générer une
    écriture d'encaissement ET de sortie de fonds sans configuration
    supplémentaire — c'est exactement ce que débloque le mapping par défaut."""
    set_current_tenant_id(None)
    org = _org(f"e2e-mapdef-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    ctx = await _setup_via_provisioning(db_session, org.id)
    await generer_mappings_par_defaut(db_session, organisation_id=org.id)
    await db_session.commit()

    # Encaissement en banque (poste recette).
    ecr_enc = await generer_ecriture_encaissement(
        db_session, organisation_id=org.id, encaissement_id=str(uuid.uuid4()),
        date_operation=date(2026, 6, 1), montant=Decimal("300.00"), devise="USD",
        canal="BANQUE", compte_bancaire_id=ctx["compte_banque"].id,
        budget_poste_id=ctx["poste_recette"].id, libelle="Cotisation",
    )
    assert ecr_enc.statut == "BROUILLON"

    # Sortie de fonds en caisse unique (pas de compte_bancaire_id — CaisseCentrale).
    ecr_sortie = await generer_ecriture_sortie_fonds(
        db_session, organisation_id=org.id, sortie_fonds_id=str(uuid.uuid4()),
        date_operation=date(2026, 6, 2), montant=Decimal("40.00"), devise="USD",
        canal="CAISSE", compte_bancaire_id=None,
        budget_poste_id=ctx["poste_depense"].id, libelle="Fournitures bureau",
    )
    assert ecr_sortie.statut == "BROUILLON"
    await db_session.commit()

    set_current_tenant_id(None)
