"""Écran de paramétrage des mappings comptables.

Le moteur échoue de façon bloquante sur un mapping manquant : cet écran est le
point de contrôle avant mise en service. Les tests portent donc autant sur ce
qu'il REFUSE (compte d'une autre organisation, compte collectif, compte
inactif) que sur ce qu'il enregistre.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.compte_bancaire import CompteBancaire
from app.models.organisation import Organisation
from app.modules.comptabilite.models import (
    RUBRIQUE_PAIE_PERSONNEL_DU,
    RUBRIQUES_TECHNIQUES,
    ComptaCompte,
    ComptaMappingPosteBudgetaire,
    ComptaSociete,
)
from app.modules.comptabilite.routers.parametrage import (
    appliquer_mappings_defaut,
    list_mappings,
    set_caisse_defaut,
    set_mapping_compte_bancaire,
    set_mapping_poste,
    set_mapping_rubrique,
)
from app.modules.comptabilite.schemas.parametrage import MappingCompteIn
from app.modules.comptabilite.services.mapping_defaut_service import generer_mappings_par_defaut
from app.modules.comptabilite.services.setup_service import setup_comptabilite


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


async def _org(db) -> Organisation:
    org = Organisation(nom="Param Test", slug=f"param-{_suffix()}", is_active=True)
    db.add(org)
    await db.flush()
    return org


async def _activer(db, org, *, mapper: bool = False) -> None:
    await setup_comptabilite(
        db, organisation_id=org.id, organisation_nom=org.nom, type_referentiel="SYSCEBNL",
        exercice_date_debut=date(2026, 1, 1), exercice_date_fin=date(2026, 12, 31),
    )
    if mapper:
        await generer_mappings_par_defaut(db, organisation_id=org.id)
    await db.flush()


async def _poste(db, org, *, annee=2026, type_poste="DEPENSE") -> BudgetPoste:
    res = await db.execute(
        select(BudgetExercice).where(
            BudgetExercice.organisation_id == org.id, BudgetExercice.annee == annee
        )
    )
    exercice = res.scalar_one_or_none()
    if exercice is None:
        exercice = BudgetExercice(organisation_id=org.id, annee=annee, statut=StatutBudget.BROUILLON)
        db.add(exercice)
        await db.flush()
    poste = BudgetPoste(
        organisation_id=org.id, exercice_id=exercice.id, code=f"P-{_suffix()}",
        libelle="Poste", type=type_poste, active=True,
        montant_prevu=Decimal("1000"), montant_engage=0, montant_paye=0, is_deleted=False,
    )
    db.add(poste)
    await db.flush()
    return poste


async def _banque(db, org) -> CompteBancaire:
    compte = CompteBancaire(
        organisation_id=org.id, intitule="Compte principal", numero_compte=f"CB-{_suffix()}",
        devise="USD", solde_initial=0, solde_actuel=0, is_active=True, account_type="BANK",
    )
    db.add(compte)
    await db.flush()
    return compte


async def _compte(db, org, numero: str) -> ComptaCompte:
    res = await db.execute(
        select(ComptaCompte).where(
            ComptaCompte.organisation_id == org.id, ComptaCompte.numero == numero
        )
    )
    return res.scalar_one()


# ── Lecture ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mappings_signalent_ce_qui_bloquerait_la_saisie(db_session):
    """Sans mapping, l'écran doit compter exactement ce qui ferait échouer le
    moteur : chaque poste, chaque compte de trésorerie, chaque rubrique, plus
    la caisse par défaut."""
    db = db_session
    org = await _org(db)
    await _activer(db, org)
    await _poste(db, org)
    await _banque(db, org)
    await db.flush()

    out = await list_mappings(tenant_id=org.id, db=db)

    assert len(out.postes) == 1
    assert len(out.comptes_bancaires) == 1
    assert len(out.rubriques) == len(RUBRIQUES_TECHNIQUES)
    assert all(p.compte_id is None for p in out.postes)
    assert out.caisse_defaut_compte_id is None
    # 1 poste + 1 banque + 5 rubriques + caisse par défaut
    assert out.nb_non_mappes == 1 + 1 + len(RUBRIQUES_TECHNIQUES) + 1


@pytest.mark.asyncio
async def test_mappings_apres_defaut_ne_signalent_plus_rien(db_session):
    db = db_session
    org = await _org(db)
    await _activer(db, org)
    await _poste(db, org)
    await _banque(db, org)
    await db.flush()
    await generer_mappings_par_defaut(db, organisation_id=org.id)
    await db.flush()

    out = await list_mappings(tenant_id=org.id, db=db)
    assert out.nb_non_mappes == 0
    assert out.caisse_defaut_compte_numero == "571"
    assert {r.code_rubrique for r in out.rubriques} == set(RUBRIQUES_TECHNIQUES)
    # Le libellé métier doit accompagner le code technique, illisible seul.
    assert all(r.libelle and r.description for r in out.rubriques)


@pytest.mark.asyncio
async def test_mappings_ne_listent_que_le_dernier_exercice_budgetaire(db_session):
    """Sur plusieurs années, seul l'exercice en cours conditionne les saisies."""
    db = db_session
    org = await _org(db)
    await _activer(db, org)
    poste_2025 = await _poste(db, org, annee=2025)
    poste_2026 = await _poste(db, org, annee=2026)
    await db.flush()

    out = await list_mappings(tenant_id=org.id, db=db)
    assert out.budget_exercice_annee == 2026
    assert [p.budget_poste_id for p in out.postes] == [poste_2026.id]

    res = await db.execute(
        select(BudgetExercice).where(
            BudgetExercice.organisation_id == org.id, BudgetExercice.annee == 2025
        )
    )
    exercice_2025 = res.scalar_one()
    out_2025 = await list_mappings(budget_exercice_id=exercice_2025.id, tenant_id=org.id, db=db)
    assert [p.budget_poste_id for p in out_2025.postes] == [poste_2025.id]


# ── Écriture ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mapper_un_poste_puis_le_corriger(db_session):
    """Le cas d'usage central : le mapping par défaut envoie tous les postes de
    dépense sur 605, l'écran sert à les affiner un par un."""
    db = db_session
    org = await _org(db)
    await _activer(db, org)
    poste = await _poste(db, org)
    await db.commit()

    compte_605 = await _compte(db, org, "605")
    out = await set_mapping_poste(
        budget_poste_id=poste.id, payload=MappingCompteIn(compte_id=compte_605.id),
        tenant_id=org.id, db=db,
    )
    assert out.compte_numero == "605"

    compte_625 = await _compte(db, org, "625")
    out = await set_mapping_poste(
        budget_poste_id=poste.id, payload=MappingCompteIn(compte_id=compte_625.id),
        tenant_id=org.id, db=db,
    )
    assert out.compte_numero == "625"

    # Un seul mapping subsiste : la correction remplace, elle n'empile pas.
    res = await db.execute(
        select(ComptaMappingPosteBudgetaire).where(
            ComptaMappingPosteBudgetaire.organisation_id == org.id,
            ComptaMappingPosteBudgetaire.budget_poste_id == poste.id,
        )
    )
    assert len(res.scalars().all()) == 1


@pytest.mark.asyncio
async def test_mapper_le_poste_salaires_sur_un_compte_de_tiers_est_autorise(db_session):
    """Point de paramétrage documenté : le poste « salaires » doit pointer sur
    la dette envers le personnel (421), sinon la charge est comptée deux fois
    (une fois par la paie, une fois par le règlement). Aucune contrainte de
    nature ne doit donc empêcher de mapper une dépense sur un compte de passif."""
    db = db_session
    org = await _org(db)
    await _activer(db, org)
    poste = await _poste(db, org, type_poste="DEPENSE")
    await db.commit()

    compte_421 = await _compte(db, org, "421")
    out = await set_mapping_poste(
        budget_poste_id=poste.id, payload=MappingCompteIn(compte_id=compte_421.id),
        tenant_id=org.id, db=db,
    )
    assert out.compte_numero == "421"


@pytest.mark.asyncio
async def test_mapper_un_compte_collectif_est_refuse(db_session):
    """401/411 exigent un compte auxiliaire par écriture : le moteur en
    générerait que la validation rejetterait. Autant refuser au paramétrage."""
    db = db_session
    org = await _org(db)
    await _activer(db, org)
    poste = await _poste(db, org)
    await db.commit()

    compte_401 = await _compte(db, org, "401")
    assert compte_401.is_collectif
    with pytest.raises(HTTPException) as exc:
        await set_mapping_poste(
            budget_poste_id=poste.id, payload=MappingCompteIn(compte_id=compte_401.id),
            tenant_id=org.id, db=db,
        )
    assert exc.value.status_code == 400
    assert "collectif" in exc.value.detail


@pytest.mark.asyncio
async def test_mapper_un_compte_inactif_est_refuse(db_session):
    db = db_session
    org = await _org(db)
    await _activer(db, org)
    poste = await _poste(db, org)
    compte = await _compte(db, org, "605")
    compte.actif = False
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await set_mapping_poste(
            budget_poste_id=poste.id, payload=MappingCompteIn(compte_id=compte.id),
            tenant_id=org.id, db=db,
        )
    assert exc.value.status_code == 400
    assert "inactif" in exc.value.detail


@pytest.mark.asyncio
async def test_mapper_un_compte_d_une_autre_organisation_est_refuse(db_session):
    """Le plan comptable est scopé par organisation : un identifiant deviné ne
    doit pas permettre de pointer sur le plan d'un autre tenant."""
    db = db_session
    org_a = await _org(db)
    org_b = await _org(db)
    await _activer(db, org_a)
    await _activer(db, org_b)
    poste_a = await _poste(db, org_a)
    await db.commit()

    compte_b = await _compte(db, org_b, "605")
    with pytest.raises(HTTPException) as exc:
        await set_mapping_poste(
            budget_poste_id=poste_a.id, payload=MappingCompteIn(compte_id=compte_b.id),
            tenant_id=org_a.id, db=db,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_mapper_compte_bancaire_rubrique_et_caisse_defaut(db_session):
    db = db_session
    org = await _org(db)
    await _activer(db, org)
    banque = await _banque(db, org)
    await db.commit()

    compte_512 = await _compte(db, org, "512")
    out_banque = await set_mapping_compte_bancaire(
        compte_bancaire_id=banque.id, payload=MappingCompteIn(compte_id=compte_512.id),
        tenant_id=org.id, db=db,
    )
    assert out_banque.compte_numero == "512"

    compte_421 = await _compte(db, org, "421")
    out_rubrique = await set_mapping_rubrique(
        code_rubrique=RUBRIQUE_PAIE_PERSONNEL_DU,
        payload=MappingCompteIn(compte_id=compte_421.id), tenant_id=org.id, db=db,
    )
    assert out_rubrique.compte_numero == "421"

    compte_571 = await _compte(db, org, "571")
    await set_caisse_defaut(
        payload=MappingCompteIn(compte_id=compte_571.id), tenant_id=org.id, db=db
    )
    res = await db.execute(
        select(ComptaSociete).where(
            ComptaSociete.organisation_id == org.id, ComptaSociete.is_default.is_(True)
        )
    )
    assert res.scalar_one().compte_caisse_defaut_id == compte_571.id


@pytest.mark.asyncio
async def test_rubrique_inconnue_est_refusee(db_session):
    db = db_session
    org = await _org(db)
    await _activer(db, org)
    await db.commit()
    compte = await _compte(db, org, "605")

    with pytest.raises(HTTPException) as exc:
        await set_mapping_rubrique(
            code_rubrique="RUBRIQUE_INVENTEE", payload=MappingCompteIn(compte_id=compte.id),
            tenant_id=org.id, db=db,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_appliquer_defaut_ne_touche_pas_un_mapping_affine(db_session):
    """Le bouton « compléter » sert à débloquer, jamais à écraser un
    paramétrage que le comptable a affiné."""
    db = db_session
    org = await _org(db)
    await _activer(db, org)
    poste_affine = await _poste(db, org)
    poste_vierge = await _poste(db, org)
    await db.commit()

    compte_625 = await _compte(db, org, "625")
    await set_mapping_poste(
        budget_poste_id=poste_affine.id, payload=MappingCompteIn(compte_id=compte_625.id),
        tenant_id=org.id, db=db,
    )

    resume = await appliquer_mappings_defaut(tenant_id=org.id, db=db)
    assert resume.postes_mappes == 1  # seul le poste vierge

    out = await list_mappings(tenant_id=org.id, db=db)
    par_poste = {p.budget_poste_id: p.compte_numero for p in out.postes}
    assert par_poste[poste_affine.id] == "625"
    assert par_poste[poste_vierge.id] == "605"


@pytest.mark.asyncio
async def test_parametrage_refuse_si_comptabilite_non_activee(db_session):
    db = db_session
    org = await _org(db)
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await list_mappings(tenant_id=org.id, db=db)
    assert exc.value.status_code == 400
