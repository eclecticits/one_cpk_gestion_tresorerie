"""Tests du module Comptabilité — Lot 1 (fondations).

Couvre : numérotation (unicité, concurrence par journal), contrôle
d'équilibre à la validation, immuabilité (trigger DB), contre-passation,
isolation tenant, cohérence des données RBAC comptable et du plan de
démarrage SYSCOHADA/SYSCEBNL.
"""

from __future__ import annotations

import importlib.util
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

import app.db.session  # noqa: F401  — enregistre les event listeners de scoping tenant
from app.core.tenant_context import set_current_tenant_id
from app.models.organisation import Organisation
from app.modules.comptabilite.models import (
    ComptaCompte,
    ComptaEcriture,
    ComptaExercice,
    ComptaJournal,
    ComptaLigneEcriture,
    ComptaReferentiel,
    ComptaSociete,
)
from app.modules.comptabilite.services.ecriture_service import (
    contrepasser_ecriture,
    controler_equilibre,
    valider_ecriture,
)
from app.modules.comptabilite.services.numerotation import generer_numero_ecriture
from app.modules.comptabilite.services.plans_comptables import (
    PLANS_PAR_TYPE,
    SYSCEBNL_SEED,
    SYSCOHADA_SEED,
    seeder_referentiel,
)

ALEMBIC_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _load_migration(filename: str):
    """Charge un fichier de migration Alembic comme module Python autonome.

    `alembic/versions/` n'est pas un package (pas d'`__init__.py`, chargement
    dynamique par Alembic) : un import classique échoue. Utile aux tests pour
    rejouer le contenu exact d'une migration (SQL des triggers, données RBAC)
    sur le schéma de test, qui est construit via `Base.metadata.create_all`
    et n'exécute donc pas l'historique Alembic.
    """
    path = ALEMBIC_VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


def _org(slug: str) -> Organisation:
    now = datetime.now(timezone.utc)
    return Organisation(
        nom=f"Org {slug}",
        slug=slug,
        plan_type="ACTIVE",
        status_abonnement="ACTIVE",
        limite_utilisateurs=10,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


async def _setup_compta_base(db, organisation_id: int, *, referentiel_code: str = "REF"):
    """Crée société + référentiel/comptes + journal + exercice ouvert."""
    societe = ComptaSociete(
        organisation_id=organisation_id,
        code="SOC",
        raison_sociale="Société de test",
    )
    referentiel = ComptaReferentiel(
        organisation_id=organisation_id,
        code=referentiel_code,
        libelle="Référentiel de test",
        type_referentiel="PERSONNALISE",
        is_default=True,
    )
    db.add_all([societe, referentiel])
    await db.flush()

    compte_charge = ComptaCompte(
        organisation_id=organisation_id,
        referentiel_id=referentiel.id,
        numero="601",
        libelle="Achats",
        nature="CHARGE",
        sens_normal="DEBIT",
    )
    compte_caisse = ComptaCompte(
        organisation_id=organisation_id,
        referentiel_id=referentiel.id,
        numero="571",
        libelle="Caisse",
        nature="ACTIF",
        sens_normal="DEBIT",
    )
    db.add_all([compte_charge, compte_caisse])
    await db.flush()

    journal = ComptaJournal(
        organisation_id=organisation_id,
        societe_id=societe.id,
        code="CA",
        libelle="Caisse",
        type_journal="CA",
    )
    db.add(journal)
    await db.flush()

    exercice = ComptaExercice(
        organisation_id=organisation_id,
        societe_id=societe.id,
        code="2026",
        date_debut=date(2026, 1, 1),
        date_fin=date(2026, 12, 31),
        referentiel_id=referentiel.id,
        statut="OUVERT",
    )
    db.add(exercice)
    await db.flush()

    return {
        "societe": societe,
        "referentiel": referentiel,
        "compte_charge": compte_charge,
        "compte_caisse": compte_caisse,
        "journal": journal,
        "exercice": exercice,
    }


def _ecriture_brouillon(*, organisation_id, societe_id, exercice_id, journal_id, date_ecriture=date(2026, 6, 15)):
    return ComptaEcriture(
        organisation_id=organisation_id,
        societe_id=societe_id,
        exercice_id=exercice_id,
        journal_id=journal_id,
        numero=None,
        date_ecriture=date_ecriture,
        libelle="Écriture de test",
        statut="BROUILLON",
    )


def _ligne(*, organisation_id, societe_id, ecriture_id, compte_id, debit=Decimal("0"), credit=Decimal("0")):
    return ComptaLigneEcriture(
        organisation_id=organisation_id,
        societe_id=societe_id,
        ecriture_id=ecriture_id,
        compte_id=compte_id,
        debit=debit,
        credit=credit,
        debit_tenue=debit,
        credit_tenue=credit,
    )


# ── Numérotation ──────────────────────────────────────────────────────────────


async def test_numerotation_incremente_et_est_isolee_par_journal(db_session):
    set_current_tenant_id(None)
    org = _org(f"num-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)

    ctx = await _setup_compta_base(db_session, org.id)
    journal_b = ComptaJournal(
        organisation_id=org.id,
        societe_id=ctx["societe"].id,
        code="BQ",
        libelle="Banque",
        type_journal="BQ",
    )
    db_session.add(journal_b)
    await db_session.flush()

    n1 = await generer_numero_ecriture(
        db_session,
        organisation_id=org.id,
        societe_id=ctx["societe"].id,
        exercice_id=ctx["exercice"].id,
        journal_id=ctx["journal"].id,
    )
    n2 = await generer_numero_ecriture(
        db_session,
        organisation_id=org.id,
        societe_id=ctx["societe"].id,
        exercice_id=ctx["exercice"].id,
        journal_id=ctx["journal"].id,
    )
    n_autre_journal = await generer_numero_ecriture(
        db_session,
        organisation_id=org.id,
        societe_id=ctx["societe"].id,
        exercice_id=ctx["exercice"].id,
        journal_id=journal_b.id,
    )

    assert n1 == "CA-2026-00001"
    assert n2 == "CA-2026-00002"
    # Un autre journal du même exercice a sa PROPRE séquence (repart à 1).
    assert n_autre_journal == "BQ-2026-00001"

    set_current_tenant_id(None)


# ── Contrôle d'équilibre et validation ───────────────────────────────────────


async def test_valider_ecriture_rejette_une_ecriture_desequilibree(db_session):
    set_current_tenant_id(None)
    org = _org(f"desequ-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    ctx = await _setup_compta_base(db_session, org.id)

    ecriture = _ecriture_brouillon(
        organisation_id=org.id,
        societe_id=ctx["societe"].id,
        exercice_id=ctx["exercice"].id,
        journal_id=ctx["journal"].id,
    )
    db_session.add(ecriture)
    await db_session.flush()
    db_session.add_all([
        _ligne(
            organisation_id=org.id, societe_id=ctx["societe"].id, ecriture_id=ecriture.id,
            compte_id=ctx["compte_charge"].id, debit=Decimal("100.00"),
        ),
        _ligne(
            organisation_id=org.id, societe_id=ctx["societe"].id, ecriture_id=ecriture.id,
            compte_id=ctx["compte_caisse"].id, credit=Decimal("90.00"),
        ),
    ])
    await db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        await valider_ecriture(db_session, ecriture_id=ecriture.id, organisation_id=org.id, user_id=None)
    assert exc_info.value.status_code == 400
    assert "déséquilibrée" in exc_info.value.detail

    await db_session.rollback()
    set_current_tenant_id(None)


async def test_valider_ecriture_equilibree_reussit_et_attribue_un_numero(db_session):
    set_current_tenant_id(None)
    org = _org(f"equ-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    ctx = await _setup_compta_base(db_session, org.id)

    ecriture = _ecriture_brouillon(
        organisation_id=org.id,
        societe_id=ctx["societe"].id,
        exercice_id=ctx["exercice"].id,
        journal_id=ctx["journal"].id,
    )
    db_session.add(ecriture)
    await db_session.flush()
    assert ecriture.numero is None  # pas de numéro au brouillon

    db_session.add_all([
        _ligne(
            organisation_id=org.id, societe_id=ctx["societe"].id, ecriture_id=ecriture.id,
            compte_id=ctx["compte_charge"].id, debit=Decimal("150.00"),
        ),
        _ligne(
            organisation_id=org.id, societe_id=ctx["societe"].id, ecriture_id=ecriture.id,
            compte_id=ctx["compte_caisse"].id, credit=Decimal("150.00"),
        ),
    ])
    await db_session.flush()

    validee = await valider_ecriture(db_session, ecriture_id=ecriture.id, organisation_id=org.id, user_id=None)
    await db_session.commit()

    assert validee.statut == "VALIDEE"
    assert validee.numero == "CA-2026-00001"
    assert validee.valide_le is not None

    set_current_tenant_id(None)


async def test_valider_ecriture_rejette_compte_inactif(db_session):
    set_current_tenant_id(None)
    org = _org(f"inactif-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    ctx = await _setup_compta_base(db_session, org.id)
    ctx["compte_charge"].actif = False
    await db_session.flush()

    ecriture = _ecriture_brouillon(
        organisation_id=org.id, societe_id=ctx["societe"].id,
        exercice_id=ctx["exercice"].id, journal_id=ctx["journal"].id,
    )
    db_session.add(ecriture)
    await db_session.flush()
    db_session.add_all([
        _ligne(organisation_id=org.id, societe_id=ctx["societe"].id, ecriture_id=ecriture.id,
               compte_id=ctx["compte_charge"].id, debit=Decimal("10.00")),
        _ligne(organisation_id=org.id, societe_id=ctx["societe"].id, ecriture_id=ecriture.id,
               compte_id=ctx["compte_caisse"].id, credit=Decimal("10.00")),
    ])
    await db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        await valider_ecriture(db_session, ecriture_id=ecriture.id, organisation_id=org.id, user_id=None)
    assert exc_info.value.status_code == 400
    assert "inactif" in exc_info.value.detail

    await db_session.rollback()
    set_current_tenant_id(None)


async def test_valider_ecriture_rejette_date_hors_exercice(db_session):
    set_current_tenant_id(None)
    org = _org(f"hors-ex-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    ctx = await _setup_compta_base(db_session, org.id)

    ecriture = _ecriture_brouillon(
        organisation_id=org.id, societe_id=ctx["societe"].id,
        exercice_id=ctx["exercice"].id, journal_id=ctx["journal"].id,
        date_ecriture=date(2027, 1, 15),  # hors de l'exercice 2026
    )
    db_session.add(ecriture)
    await db_session.flush()
    db_session.add_all([
        _ligne(organisation_id=org.id, societe_id=ctx["societe"].id, ecriture_id=ecriture.id,
               compte_id=ctx["compte_charge"].id, debit=Decimal("10.00")),
        _ligne(organisation_id=org.id, societe_id=ctx["societe"].id, ecriture_id=ecriture.id,
               compte_id=ctx["compte_caisse"].id, credit=Decimal("10.00")),
    ])
    await db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        await valider_ecriture(db_session, ecriture_id=ecriture.id, organisation_id=org.id, user_id=None)
    assert exc_info.value.status_code == 400
    assert "hors de l'exercice" in exc_info.value.detail

    await db_session.rollback()
    set_current_tenant_id(None)


def test_controler_equilibre_arrondit_au_centime():
    ligne_a = ComptaLigneEcriture(debit_tenue=Decimal("10.005"), credit_tenue=Decimal("0"))
    ligne_b = ComptaLigneEcriture(debit_tenue=Decimal("0"), credit_tenue=Decimal("10.005"))
    total_debit, total_credit = controler_equilibre([ligne_a, ligne_b])
    assert total_debit == total_credit == Decimal("10.01")  # ROUND_HALF_UP


# ── Immuabilité (trigger DB) ─────────────────────────────────────────────────


async def test_ecriture_validee_est_immuable(db_session):
    # `Base.metadata.create_all` ne crée que les tables : les triggers (SQL
    # brut de la migration) doivent être posés explicitement pour ce test.
    fondations = _load_migration("20260731_compta_fondations.py")
    await db_session.execute(text(fondations.TRIGGER_ECRITURE_FUNCTION_SQL))
    await db_session.execute(text(fondations.TRIGGER_ECRITURE_CREATE_SQL.replace(
        "CREATE TRIGGER", "CREATE OR REPLACE TRIGGER"
    )))
    await db_session.commit()

    set_current_tenant_id(None)
    org = _org(f"immut-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    ctx = await _setup_compta_base(db_session, org.id)

    ecriture = _ecriture_brouillon(
        organisation_id=org.id, societe_id=ctx["societe"].id,
        exercice_id=ctx["exercice"].id, journal_id=ctx["journal"].id,
    )
    db_session.add(ecriture)
    await db_session.flush()
    db_session.add_all([
        _ligne(organisation_id=org.id, societe_id=ctx["societe"].id, ecriture_id=ecriture.id,
               compte_id=ctx["compte_charge"].id, debit=Decimal("25.00")),
        _ligne(organisation_id=org.id, societe_id=ctx["societe"].id, ecriture_id=ecriture.id,
               compte_id=ctx["compte_caisse"].id, credit=Decimal("25.00")),
    ])
    await db_session.flush()

    await valider_ecriture(db_session, ecriture_id=ecriture.id, organisation_id=org.id, user_id=None)
    await db_session.commit()

    # Tentative de modification d'un champ figé après validation : le trigger
    # PostgreSQL doit lever une exception, pas seulement une règle applicative.
    ecriture.libelle = "Tentative de modification interdite"
    with pytest.raises(DBAPIError):
        await db_session.flush()

    await db_session.rollback()
    set_current_tenant_id(None)

    # Le trigger est posé sur la base de test tout entière : le laisser en
    # place imposerait ses règles aux tests suivants, qui n'en tiennent pas
    # compte et échoueraient selon l'ordre d'exécution.
    await db_session.execute(
        text("DROP TRIGGER IF EXISTS trg_compta_ecriture_immutable ON compta_ecritures")
    )
    await db_session.commit()


async def test_contrepasser_ecriture_inverse_les_montants_et_annule_origine(db_session):
    set_current_tenant_id(None)
    org = _org(f"cp-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    ctx = await _setup_compta_base(db_session, org.id)

    ecriture = _ecriture_brouillon(
        organisation_id=org.id, societe_id=ctx["societe"].id,
        exercice_id=ctx["exercice"].id, journal_id=ctx["journal"].id,
    )
    db_session.add(ecriture)
    await db_session.flush()
    db_session.add_all([
        _ligne(organisation_id=org.id, societe_id=ctx["societe"].id, ecriture_id=ecriture.id,
               compte_id=ctx["compte_charge"].id, debit=Decimal("40.00")),
        _ligne(organisation_id=org.id, societe_id=ctx["societe"].id, ecriture_id=ecriture.id,
               compte_id=ctx["compte_caisse"].id, credit=Decimal("40.00")),
    ])
    await db_session.flush()
    await valider_ecriture(db_session, ecriture_id=ecriture.id, organisation_id=org.id, user_id=None)
    await db_session.commit()

    inverse = await contrepasser_ecriture(
        db_session,
        ecriture_id=ecriture.id,
        organisation_id=org.id,
        user_id=None,
        motif="Erreur de saisie",
    )
    await db_session.commit()

    assert inverse.statut == "BROUILLON"
    assert inverse.contrepasse_ecriture_id == ecriture.id

    lignes_res = await db_session.execute(
        select(ComptaLigneEcriture).where(ComptaLigneEcriture.ecriture_id == inverse.id)
    )
    lignes_inverse = {l.compte_id: l for l in lignes_res.scalars().all()}
    assert lignes_inverse[ctx["compte_charge"].id].credit == Decimal("40.00")
    assert lignes_inverse[ctx["compte_charge"].id].debit == Decimal("0.00")
    assert lignes_inverse[ctx["compte_caisse"].id].debit == Decimal("40.00")

    await db_session.refresh(ecriture)
    assert ecriture.statut == "ANNULEE"
    assert ecriture.motif_annulation == "Erreur de saisie"

    set_current_tenant_id(None)


async def test_contrepasser_ecriture_refuse_un_brouillon(db_session):
    set_current_tenant_id(None)
    org = _org(f"cp-brouillon-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    ctx = await _setup_compta_base(db_session, org.id)

    ecriture = _ecriture_brouillon(
        organisation_id=org.id, societe_id=ctx["societe"].id,
        exercice_id=ctx["exercice"].id, journal_id=ctx["journal"].id,
    )
    db_session.add(ecriture)
    await db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        await contrepasser_ecriture(
            db_session, ecriture_id=ecriture.id, organisation_id=org.id, user_id=None, motif="test",
        )
    assert exc_info.value.status_code == 400

    await db_session.rollback()
    set_current_tenant_id(None)


# ── Isolation tenant ──────────────────────────────────────────────────────────


async def test_ecritures_sont_strictement_isolees_par_organisation(db_session):
    set_current_tenant_id(None)
    org_a = _org(f"tenant-a-{_suffix()}")
    org_b = _org(f"tenant-b-{_suffix()}")
    db_session.add_all([org_a, org_b])
    await db_session.flush()

    set_current_tenant_id(org_a.id)
    ctx_a = await _setup_compta_base(db_session, org_a.id)
    ecriture_a = _ecriture_brouillon(
        organisation_id=org_a.id, societe_id=ctx_a["societe"].id,
        exercice_id=ctx_a["exercice"].id, journal_id=ctx_a["journal"].id,
    )
    db_session.add(ecriture_a)
    await db_session.flush()

    set_current_tenant_id(org_b.id)
    ctx_b = await _setup_compta_base(db_session, org_b.id)
    ecriture_b = _ecriture_brouillon(
        organisation_id=org_b.id, societe_id=ctx_b["societe"].id,
        exercice_id=ctx_b["exercice"].id, journal_id=ctx_b["journal"].id,
    )
    db_session.add(ecriture_b)
    await db_session.commit()

    # Sous le contexte tenant B, l'écriture de A ne doit jamais apparaître.
    set_current_tenant_id(org_b.id)
    res = await db_session.execute(select(ComptaEcriture))
    visibles = {e.id for e in res.scalars().all()}
    assert ecriture_b.id in visibles
    assert ecriture_a.id not in visibles

    set_current_tenant_id(None)


# ── Plans comptables de démarrage ────────────────────────────────────────────


@pytest.mark.parametrize("type_referentiel", ["SYSCOHADA", "SYSCEBNL"])
async def test_seeder_referentiel_cree_le_plan_et_resout_la_hierarchie(db_session, type_referentiel):
    set_current_tenant_id(None)
    org = _org(f"plan-{type_referentiel.lower()}-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)

    referentiel = await seeder_referentiel(
        db_session,
        organisation_id=org.id,
        type_referentiel=type_referentiel,
        code=type_referentiel,
        libelle=f"Plan {type_referentiel}",
        is_default=True,
    )
    await db_session.commit()

    seed = PLANS_PAR_TYPE[type_referentiel]
    res = await db_session.execute(
        select(ComptaCompte).where(ComptaCompte.referentiel_id == referentiel.id)
    )
    comptes = {c.numero: c for c in res.scalars().all()}
    assert len(comptes) == len(seed)

    # Vérifie la résolution de hiérarchie sur un exemple connu (401 sous 40).
    assert comptes["401"].parent_id == comptes["40"].id

    set_current_tenant_id(None)


async def test_seeder_referentiel_est_idempotent(db_session):
    set_current_tenant_id(None)
    org = _org(f"plan-idem-{_suffix()}")
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)

    r1 = await seeder_referentiel(
        db_session, organisation_id=org.id, type_referentiel="SYSCOHADA",
        code="SYSCOHADA", libelle="Plan", is_default=True,
    )
    await db_session.commit()
    r2 = await seeder_referentiel(
        db_session, organisation_id=org.id, type_referentiel="SYSCOHADA",
        code="SYSCOHADA", libelle="Plan", is_default=True,
    )
    await db_session.commit()

    assert r1.id == r2.id
    res = await db_session.execute(
        select(ComptaCompte).where(ComptaCompte.referentiel_id == r1.id)
    )
    assert len(res.scalars().all()) == len(SYSCOHADA_SEED)  # pas de doublons

    set_current_tenant_id(None)


def test_plans_de_demarrage_nont_pas_de_numero_duplique():
    for type_referentiel, seed in PLANS_PAR_TYPE.items():
        numeros = [item.numero for item in seed]
        assert len(numeros) == len(set(numeros)), f"Doublon de numéro dans le plan {type_referentiel}"
        for item in seed:
            if item.parent_numero:
                assert item.parent_numero in numeros, (
                    f"{type_referentiel}: parent {item.parent_numero} du compte {item.numero} introuvable"
                )


# ── RBAC comptable (cohérence des données de la migration) ──────────────────


def test_rbac_comptable_roles_ne_referencent_que_des_permissions_declarees():
    migration = _load_migration("20260731_compta_rbac.py")
    permission_codes = {code for code, _ in migration.PERMISSIONS}
    assert len(permission_codes) == len(migration.PERMISSIONS), "Code de permission dupliqué"

    role_codes = [code for code, *_ in migration.ROLES]
    assert len(role_codes) == len(set(role_codes)), "Code de rôle dupliqué"

    for code, _label, _description, perm_codes in migration.ROLES:
        inconnues = set(perm_codes) - permission_codes
        assert not inconnues, f"Rôle {code} référence des permissions non déclarées : {inconnues}"

    # Matrice actée : chef_comptable et daf doivent pouvoir valider ; seuls
    # auditeur/CAC sont strictement lecture seule.
    roles_par_code = {code: perms for code, _, _, perms in migration.ROLES}
    assert "compta.validation" in roles_par_code["chef_comptable"]
    assert "compta.validation" in roles_par_code["daf"]
    assert "compta.cloture" in roles_par_code["daf"]
    assert "compta.validation" not in roles_par_code["auditeur_comptable"]
    assert "compta.validation" not in roles_par_code["cac"]
    assert "compta.export" in roles_par_code["cac"]


async def test_rbac_comptable_migration_upgrade_produit_les_bonnes_attributions(db_session):
    """Exécute réellement `upgrade()` de la migration (pas une reformulation
    de son SQL) via un vrai contexte Alembic, sur le schéma de test.

    La fixture de test crée le schéma via `metadata.create_all` (pas via un
    run Alembic complet) : ce test fait donc tourner `upgrade()` directement,
    ce qui aurait détecté par exemple une interpolation SQL cassée par une
    apostrophe dans un libellé français (bug réel rencontré et corrigé ici).
    """
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    migration = _load_migration("20260731_compta_rbac.py")

    conn = await db_session.connection()

    def _upgrade(sync_conn):
        ctx = MigrationContext.configure(sync_conn)
        with Operations.context(ctx):
            migration.upgrade()

    await conn.run_sync(_upgrade)
    await db_session.flush()  # visible à cette transaction, jamais commit :
    # `permissions`/`roles` sont des catalogues globaux partagés par toute la
    # suite (cf. test_secretariat_module.py qui suppose `permissions` propre).

    result = await db_session.execute(
        text(
            """
            SELECT r.code, p.code
            FROM roles r
            JOIN role_permissions rp ON rp.role_id = r.id
            JOIN permissions p ON p.id = rp.permission_id
            WHERE r.code IN ('comptable', 'chef_comptable', 'daf', 'auditeur_comptable', 'cac')
            """
        )
    )
    grants: dict[str, set[str]] = {}
    for role_code, perm_code in result.all():
        grants.setdefault(role_code, set()).add(perm_code)

    assert grants.get("comptable") == {"compta.saisie", "compta.lecture"}
    assert grants.get("chef_comptable") == {"compta.saisie", "compta.validation", "compta.lecture"}
    assert grants.get("daf") == {
        "compta.saisie", "compta.validation", "compta.cloture", "compta.parametrage", "compta.lecture",
    }
    assert grants.get("auditeur_comptable") == {"compta.lecture"}
    assert grants.get("cac") == {"compta.lecture", "compta.export"}

    await db_session.rollback()
