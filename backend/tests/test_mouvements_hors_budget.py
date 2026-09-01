from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select

from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.fonds_tiers_operation import FondsTiersOperation
from app.models.mouvement_budget_imputation import MouvementBudgetImputation
from app.models.organisation import Organisation
from app.models.user import User
from app.models.regularisation_budgetaire import RegularisationBudgetaire
from app.schemas.payment import AffecterBudgetPayload, BudgetAffectationLine, EncaissementCancelPayload, EncaissementCreate, FondsTiersCreate
from app.schemas.sortie_fonds import SortieFondsCreate, SortieFondsStatusUpdate

# Les écritures comptables sont générées dans le flux : sans cet import, les
# tables `compta_*` manquent aux métadonnées quand ce fichier tourne seul.
from app.modules.comptabilite import models as _compta_models  # noqa: F401


class _FakeRequest:
    headers: dict = {}
    client = None


async def _org(db, slug_prefix="hb"):
    org = Organisation(nom="Hors Budget", slug=f"{slug_prefix}-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    return org


async def _admin(db, org):
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex[:8]}@ex.com", role="admin", organisation_id=org.id)
    db.add(user)
    await db.flush()
    return user


async def _poste(db, org, type_="RECETTE", montant_prevu=Decimal("10000")):
    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
    db.add(exercice)
    await db.flush()
    poste = BudgetPoste(
        organisation_id=org.id,
        exercice_id=exercice.id,
        code=f"{type_[:3]}-{uuid.uuid4().hex[:6]}",
        libelle=f"Poste {type_}",
        type=type_,
        active=True,
        montant_prevu=montant_prevu,
        montant_engage=0,
        montant_paye=0,
        is_deleted=False,
    )
    db.add(poste)
    await db.flush()
    return poste


async def _caisse(db, org, usd=Decimal("0")):
    caisse = CaisseCentrale(organisation_id=org.id, solde_usd=usd, solde_cdf=0, est_ouverte=True)
    db.add(caisse)
    await db.flush()
    return caisse


async def _banque(db, org, solde=Decimal("0")):
    compte = CompteBancaire(
        organisation_id=org.id,
        intitule="Equity",
        numero_compte=f"EQ-{uuid.uuid4().hex[:10]}",
        devise="USD",
        solde_initial=solde,
        solde_actuel=solde,
        is_active=True,
        account_type="BANK",
    )
    db.add(compte)
    await db.flush()
    return compte


@pytest.mark.asyncio
async def test_encaissement_hors_budget_affecte_tresorerie_pas_budget_puis_regularise(db_session, monkeypatch):
    db = db_session
    org = await _org(db)
    user = await _admin(db, org)
    poste = await _poste(db, org, "RECETTE")
    caisse = await _caisse(db, org, Decimal("0"))
    await db.commit()

    async def fake_recu(**_kwargs):
        return "REC-HB-1"

    monkeypatch.setattr("app.api.v1.endpoints.encaissements._generate_numero_recu", fake_recu)
    from app.api.v1.endpoints.encaissements import affecter_encaissement_budget, create_encaissement

    enc = await create_encaissement(
        payload=EncaissementCreate(
            type_client="client_externe",
            client_nom="CPK",
            libelle="Recette non prévue",
            montant=Decimal("2000"),
            montant_total=Decimal("2000"),
            montant_paye=Decimal("2000"),
            nature_mouvement="HORS_BUDGET_A_REGULARISER",
            mode_paiement="cash",
            canal="CAISSE",
        ),
        background_tasks=BackgroundTasks(),
        user=user,
        tenant_id=org.id,
        db=db,
    )
    await db.refresh(caisse)
    await db.refresh(poste)
    assert caisse.solde_usd == Decimal("2000")
    assert poste.montant_paye == Decimal("0")

    await affecter_encaissement_budget(
        encaissement_id=str(enc["id"]),
        payload=AffecterBudgetPayload(
            lignes=[BudgetAffectationLine(budget_poste_id=poste.id, montant=Decimal("1200"))],
            justification="Affectation validée",
            idempotency_key="reg-hb-1",
        ),
        request=_FakeRequest(),
        user=user,
        tenant_id=org.id,
        db=db,
    )
    await db.refresh(poste)
    assert poste.montant_paye == Decimal("1200")

    await affecter_encaissement_budget(
        encaissement_id=str(enc["id"]),
        payload=AffecterBudgetPayload(
            lignes=[BudgetAffectationLine(budget_poste_id=poste.id, montant=Decimal("1200"))],
            justification="Retry",
            idempotency_key="reg-hb-1",
        ),
        request=_FakeRequest(),
        user=user,
        tenant_id=org.id,
        db=db,
    )
    await db.refresh(poste)
    assert poste.montant_paye == Decimal("1200")


@pytest.mark.asyncio
async def test_fonds_tiers_remboursements_partiels_et_surremboursement_rejete(db_session, monkeypatch):
    db = db_session
    org = await _org(db, "ft")
    user = await _admin(db, org)
    banque = await _banque(db, org, Decimal("0"))
    await db.commit()

    async def fake_recu(**_kwargs):
        return "REC-FT-1"

    monkeypatch.setattr("app.api.v1.endpoints.encaissements._generate_numero_recu", fake_recu)

    async def fake_num(*_args, **_kwargs):
        return f"PAY-{uuid.uuid4().hex[:8]}"

    monkeypatch.setattr("app.api.v1.endpoints.sorties_fonds.generate_document_number", fake_num)

    from app.api.v1.endpoints.encaissements import create_encaissement
    from app.api.v1.endpoints.sorties_fonds import create_sortie_fonds

    await create_encaissement(
        payload=EncaissementCreate(
            type_client="client_externe",
            client_nom="Autre conseil",
            libelle="Fonds reçus pour compte de tiers",
            montant=Decimal("500"),
            montant_total=Decimal("500"),
            montant_paye=Decimal("500"),
            nature_mouvement="FONDS_DE_TIERS",
            mode_paiement="virement",
            canal="BANQUE",
            compte_bancaire_id=banque.id,
            fonds_tiers=FondsTiersCreate(tiers_concerne="CP Sud", beneficiaire_reel="CP Sud"),
        ),
        background_tasks=BackgroundTasks(),
        user=user,
        tenant_id=org.id,
        db=db,
    )
    op = (await db.execute(select(FondsTiersOperation).where(FondsTiersOperation.organisation_id == org.id))).scalar_one()
    await db.refresh(banque)
    assert banque.solde_actuel == Decimal("500")

    for amount in (Decimal("200"), Decimal("300")):
        await create_sortie_fonds(
            payload=SortieFondsCreate(
                type_sortie="autre",
                nature_mouvement="FONDS_DE_TIERS",
                fonds_tiers_operation_id=op.id,
                montant_paye=amount,
                mode_paiement="virement",
                devise="USD",
                canal="BANQUE",
                compte_bancaire_id=banque.id,
                motif="Remboursement tiers",
                beneficiaire="CP Sud",
            ),
            request=_FakeRequest(),
            background_tasks=BackgroundTasks(),
            user=user,
            tenant_id=org.id,
            db=db,
        )
    await db.refresh(op)
    await db.refresh(banque)
    assert op.statut == "REGULARISE"
    assert banque.solde_actuel == Decimal("0")

    with pytest.raises(HTTPException):
        await create_sortie_fonds(
            payload=SortieFondsCreate(
                type_sortie="autre",
                nature_mouvement="FONDS_DE_TIERS",
                fonds_tiers_operation_id=op.id,
                montant_paye=Decimal("1"),
                mode_paiement="virement",
                devise="USD",
                canal="BANQUE",
                compte_bancaire_id=banque.id,
                motif="Trop",
                beneficiaire="CP Sud",
            ),
            request=_FakeRequest(),
            background_tasks=BackgroundTasks(),
            user=user,
            tenant_id=org.id,
            db=db,
        )


@pytest.mark.asyncio
async def test_annulation_sortie_utilise_imputations_persistantes(db_session, monkeypatch):
    db = db_session
    org = await _org(db, "imp")
    user = await _admin(db, org)
    poste = await _poste(db, org, "DEPENSE")
    caisse = await _caisse(db, org, Decimal("500"))
    await db.commit()

    async def fake_num(*_args, **_kwargs):
        return f"PAY-{uuid.uuid4().hex[:8]}"

    monkeypatch.setattr("app.api.v1.endpoints.sorties_fonds.generate_document_number", fake_num)
    from app.api.v1.endpoints.sorties_fonds import create_sortie_fonds, update_sortie_statut

    sortie = await create_sortie_fonds(
        payload=SortieFondsCreate(
            type_sortie="autre",
            montant_paye=Decimal("120"),
            mode_paiement="cash",
            devise="USD",
            canal="CAISSE",
            motif="Dépense",
            beneficiaire="Fournisseur",
            budget_poste_id=poste.id,
        ),
        request=_FakeRequest(),
        background_tasks=BackgroundTasks(),
        user=user,
        tenant_id=org.id,
        db=db,
    )
    imps = (await db.execute(select(MouvementBudgetImputation).where(MouvementBudgetImputation.sortie_fonds_id == sortie.id))).scalars().all()
    assert len(imps) == 1

    await update_sortie_statut(
        sortie_id=str(sortie.id),
        payload=SortieFondsStatusUpdate(statut="ANNULEE", motif_annulation="Erreur"),
        request=_FakeRequest(),
        user=user,
        tenant_id=org.id,
        db=db,
    )
    await db.refresh(poste)
    await db.refresh(caisse)
    assert poste.montant_paye == Decimal("0")
    assert caisse.solde_usd == Decimal("500")


@pytest.mark.asyncio
async def test_sortie_hors_budget_est_affectee_puis_reprise_a_l_annulation(db_session, monkeypatch):
    db = db_session
    org = await _org(db, "sfhb")
    user = await _admin(db, org)
    poste = await _poste(db, org, "DEPENSE")
    caisse = await _caisse(db, org, Decimal("500"))
    await db.commit()

    async def fake_num(*_args, **_kwargs):
        return f"PAY-{uuid.uuid4().hex[:8]}"

    monkeypatch.setattr("app.api.v1.endpoints.sorties_fonds.generate_document_number", fake_num)
    from app.api.v1.endpoints.sorties_fonds import affecter_sortie_budget, create_sortie_fonds, update_sortie_statut

    sortie = await create_sortie_fonds(
        payload=SortieFondsCreate(
            type_sortie="autre",
            nature_mouvement="HORS_BUDGET_A_REGULARISER",
            montant_paye=Decimal("120"),
            mode_paiement="cash",
            devise="USD",
            canal="CAISSE",
            motif="Urgence non budgétée",
            beneficiaire="Fournisseur",
        ),
        request=_FakeRequest(),
        background_tasks=BackgroundTasks(),
        user=user,
        tenant_id=org.id,
        db=db,
    )
    await db.refresh(poste)
    await db.refresh(caisse)
    # La caisse a bougé, le budget non.
    assert caisse.solde_usd == Decimal("380")
    assert poste.montant_paye == Decimal("0")
    assert sortie.hors_budget_status == "A_REGULARISER"

    await affecter_sortie_budget(
        sortie_id=str(sortie.id),
        payload=AffecterBudgetPayload(
            lignes=[BudgetAffectationLine(budget_poste_id=poste.id, montant=Decimal("120"))],
            justification="Imputée après coup sur le poste dépense",
            idempotency_key="reg-sf-1",
        ),
        request=_FakeRequest(),
        user=user,
        tenant_id=org.id,
        db=db,
    )
    await db.refresh(poste)
    assert poste.montant_paye == Decimal("120")
    reg = (
        await db.execute(select(RegularisationBudgetaire).where(RegularisationBudgetaire.sortie_fonds_id == sortie.id))
    ).scalar_one()
    assert reg.ancien_nature_mouvement == "HORS_BUDGET_A_REGULARISER"

    # Rejouer la même clé n'impute pas deux fois.
    await affecter_sortie_budget(
        sortie_id=str(sortie.id),
        payload=AffecterBudgetPayload(
            lignes=[BudgetAffectationLine(budget_poste_id=poste.id, montant=Decimal("120"))],
            justification="Retry",
            idempotency_key="reg-sf-1",
        ),
        request=_FakeRequest(),
        user=user,
        tenant_id=org.id,
        db=db,
    )
    await db.refresh(poste)
    assert poste.montant_paye == Decimal("120")

    await update_sortie_statut(
        sortie_id=str(sortie.id),
        payload=SortieFondsStatusUpdate(statut="ANNULEE", motif_annulation="Erreur"),
        request=_FakeRequest(),
        user=user,
        tenant_id=org.id,
        db=db,
    )
    await db.refresh(poste)
    await db.refresh(caisse)
    assert poste.montant_paye == Decimal("0")
    assert caisse.solde_usd == Decimal("500")


@pytest.mark.asyncio
async def test_annulation_encaissement_regularise_rend_le_budget(db_session, monkeypatch):
    """Un encaissement hors budget régularisé puis annulé ne doit rien laisser au poste.

    L'imputation vient de la régularisation (portée par l'encaissement), pas du
    paiement : elle doit être reprise même quand l'encaissement a des paiements
    actifs à annuler.
    """
    db = db_session
    org = await _org(db, "regann")
    user = await _admin(db, org)
    poste = await _poste(db, org, "RECETTE")
    caisse = await _caisse(db, org, Decimal("0"))
    await db.commit()

    async def fake_recu(**_kwargs):
        return f"REC-{uuid.uuid4().hex[:6]}"

    monkeypatch.setattr("app.api.v1.endpoints.encaissements._generate_numero_recu", fake_recu)
    from app.api.v1.endpoints.encaissements import (
        affecter_encaissement_budget,
        cancel_encaissement_operation,
        create_encaissement,
    )

    enc = await create_encaissement(
        payload=EncaissementCreate(
            type_client="client_externe",
            client_nom="CPK",
            libelle="Recette non prévue",
            montant=Decimal("800"),
            montant_total=Decimal("800"),
            montant_paye=Decimal("800"),
            nature_mouvement="HORS_BUDGET_A_REGULARISER",
            mode_paiement="cash",
            canal="CAISSE",
        ),
        background_tasks=BackgroundTasks(),
        user=user,
        tenant_id=org.id,
        db=db,
    )
    await affecter_encaissement_budget(
        encaissement_id=str(enc["id"]),
        payload=AffecterBudgetPayload(
            lignes=[BudgetAffectationLine(budget_poste_id=poste.id, montant=Decimal("800"))],
            justification="Affectation validée",
            idempotency_key="reg-ann-1",
        ),
        request=_FakeRequest(),
        user=user,
        tenant_id=org.id,
        db=db,
    )
    await db.refresh(poste)
    assert poste.montant_paye == Decimal("800")

    await cancel_encaissement_operation(
        encaissement_id=str(enc["id"]),
        payload=EncaissementCancelPayload(motif_annulation="Encaissement erroné"),
        request=_FakeRequest(),
        user=user,
        tenant_id=org.id,
        db=db,
    )
    await db.refresh(poste)
    await db.refresh(caisse)
    assert poste.montant_paye == Decimal("0")
    assert caisse.solde_usd == Decimal("0")
    restantes = (
        await db.execute(
            select(MouvementBudgetImputation).where(
                MouvementBudgetImputation.organisation_id == org.id,
                MouvementBudgetImputation.statut == "ACTIVE",
            )
        )
    ).scalars().all()
    assert restantes == []


@pytest.mark.asyncio
async def test_dashboard_separe_tresorerie_et_budget(db_session, monkeypatch):
    """Le hors budget gonfle la trésorerie, jamais l'exécution budgétaire.

    C'est toute la raison d'être de la séparation : un encaissement hors budget
    est bien de l'argent reçu — il doit apparaître en trésorerie — mais il n'a
    alimenté aucun poste, et le dire dans les mêmes chiffres ferait croire à
    une recette budgétaire qui n'existe pas.
    """
    db = db_session
    org = await _org(db, "dash")
    user = await _admin(db, org)
    poste = await _poste(db, org, "RECETTE")
    await _caisse(db, org, Decimal("0"))
    await db.commit()

    async def fake_recu(**_kwargs):
        return f"REC-{uuid.uuid4().hex[:6]}"

    monkeypatch.setattr("app.api.v1.endpoints.encaissements._generate_numero_recu", fake_recu)
    # Le cache Redis servirait la réponse d'un autre test : on le neutralise.
    monkeypatch.setattr("app.api.v1.endpoints.dashboard.cache_get", lambda *_a, **_k: _none())
    monkeypatch.setattr("app.api.v1.endpoints.dashboard.cache_set", lambda *_a, **_k: _none())

    from app.api.v1.endpoints.dashboard import stats as dashboard_stats
    from app.api.v1.endpoints.encaissements import create_encaissement

    async def _encaisser(nature: str, montant: Decimal, poste_id: int | None):
        return await create_encaissement(
            payload=EncaissementCreate(
                type_client="client_externe",
                client_nom="CPK",
                libelle="Recette",
                montant=montant,
                montant_total=montant,
                montant_paye=montant,
                nature_mouvement=nature,
                budget_poste_id=poste_id,
                mode_paiement="cash",
                canal="CAISSE",
            ),
            background_tasks=BackgroundTasks(),
            user=user,
            tenant_id=org.id,
            db=db,
        )

    await _encaisser("BUDGETAIRE", Decimal("300"), poste.id)
    await _encaisser("HORS_BUDGET_A_REGULARISER", Decimal("700"), None)
    await db.commit()

    res = await dashboard_stats(
        period_type="month",
        tenant_id=org.id,
        user=user,
        db=db,
    )
    # Trésorerie : tout l'argent reçu.
    assert Decimal(res.stats.total_encaissements_period) == Decimal("1000.00")
    # Budget : seulement ce qui a alimenté un poste.
    assert Decimal(res.stats.total_recettes_budgetaires_period) == Decimal("300.00")
    assert Decimal(res.stats.total_recettes_hors_budget_period) == Decimal("700.00")
    # Et l'encours qui appelle une décision.
    assert Decimal(res.stats.hors_budget_a_regulariser_montant) == Decimal("700.00")
    assert res.stats.hors_budget_a_regulariser_count == 1


async def _none():
    return None


@pytest.mark.asyncio
async def test_export_encaissements_porte_la_nature_budgetaire(db_session, monkeypatch):
    """L'export nomme ce que chaque ligne fait au budget.

    Sans cette colonne, une recette budgétaire et un fonds de tiers se
    ressemblent trait pour trait dans le classeur : même montant, même date,
    même client.
    """
    from io import BytesIO

    from openpyxl import load_workbook

    db = db_session
    org = await _org(db, "exp")
    user = await _admin(db, org)
    banque = await _banque(db, org, Decimal("0"))
    await db.commit()

    async def fake_recu(**_kwargs):
        return f"REC-{uuid.uuid4().hex[:6]}"

    monkeypatch.setattr("app.api.v1.endpoints.encaissements._generate_numero_recu", fake_recu)
    from app.api.v1.endpoints.encaissements import create_encaissement
    from app.api.v1.endpoints.exports import construire_classeur_encaissements

    await create_encaissement(
        payload=EncaissementCreate(
            type_client="client_externe",
            client_nom="CP Sud",
            libelle="Fonds pour compte de tiers",
            montant=Decimal("250"),
            montant_total=Decimal("250"),
            montant_paye=Decimal("250"),
            nature_mouvement="FONDS_DE_TIERS",
            mode_paiement="virement",
            canal="BANQUE",
            compte_bancaire_id=banque.id,
            fonds_tiers=FondsTiersCreate(tiers_concerne="CP Sud"),
        ),
        background_tasks=BackgroundTasks(),
        user=user,
        tenant_id=org.id,
        db=db,
    )
    await db.commit()

    classeur, _nom = await construire_classeur_encaissements(db, org.id)
    buffer = BytesIO()
    classeur.save(buffer)
    buffer.seek(0)
    ws = load_workbook(buffer, data_only=False)["Encaissements"]
    lignes = list(ws.iter_rows(values_only=True))

    entete = next(row for row in lignes if "Nature budgétaire" in [str(v) for v in row if v])
    index_nature = [str(v) for v in entete].index("Nature budgétaire")
    ligne = next(row for row in lignes if row[index_nature] == "Fonds de tiers")
    assert ligne[index_nature] == "Fonds de tiers"
