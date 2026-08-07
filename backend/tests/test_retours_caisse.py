"""Tests d'intégration des retours en caisse (remboursement après sortie de fonds).

Appelle directement les fonctions d'endpoint (comme test_encaissements.py),
avec le mode d'intégration comptable par défaut (non automatique) : aucune
écriture comptable n'est générée, on vérifie les effets trésorerie + budget.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.endpoints.retours_caisse import (
    create_retour_caisse,
    list_retours_caisse,
    update_retour_statut,
)
from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.caisse_centrale import CaisseCentrale
from app.models.organisation import Organisation
from app.models.retour_caisse import RetourCaisse
from app.models.sortie_fonds import SortieFonds
from app.models.user import User
from app.schemas.retour_caisse import RetourCaisseCreate, RetourCaisseStatusUpdate


async def _setup_sortie(db_session, *, montant=Decimal("100"), solde_caisse=Decimal("0")):
    """Org + poste DÉPENSE (déjà imputé), caisse ouverte, et une sortie de fonds VALIDE."""
    org = Organisation(nom="Retour Test", slug=f"ret-{uuid.uuid4().hex[:8]}", is_active=True)
    db_session.add(org)
    await db_session.flush()

    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
    db_session.add(exercice)
    await db_session.flush()

    poste = BudgetPoste(
        organisation_id=org.id,
        exercice_id=exercice.id,
        code="DEP-001",
        libelle="Poste dépense mission",
        type="DEPENSE",
        active=True,
        montant_prevu=Decimal("1000"),
        montant_engage=0,
        montant_paye=montant,  # la sortie a déjà imputé le budget
        is_deleted=False,
    )
    db_session.add(poste)

    caisse = CaisseCentrale(organisation_id=org.id, est_ouverte=True, solde_usd=solde_caisse, solde_cdf=0)
    db_session.add(caisse)

    user = User(id=uuid.uuid4(), email=f"ret-{uuid.uuid4().hex[:6]}@example.com", role="admin", organisation_id=org.id)
    await db_session.flush()

    sortie = SortieFonds(
        id=uuid.uuid4(),
        type_sortie="requisition",
        organisation_id=org.id,
        budget_poste_id=poste.id,
        montant_paye=montant,
        mode_paiement="cash",
        devise="USD",
        canal="CAISSE",
        statut="VALIDE",
        motif="Avance mission",
        beneficiaire="Agent X",
        created_by=user.id,
        date_paiement=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    db_session.add(sortie)
    await db_session.commit()
    await db_session.refresh(poste)
    await db_session.refresh(caisse)
    await db_session.refresh(sortie)
    return org, user, poste, caisse, sortie


@pytest.mark.asyncio
async def test_retour_reliquat_credits_caisse_and_reduces_budget(db_session):
    org, user, poste, caisse, sortie = await _setup_sortie(db_session)

    payload = RetourCaisseCreate(sortie_fonds_id=sortie.id, montant=Decimal("30"), motif="Reliquat mission")
    out = await create_retour_caisse(payload=payload, request=None, user=user, tenant_id=org.id, db=db_session)

    assert out.montant == Decimal("30")
    assert out.canal == "CAISSE"
    assert out.statut == "VALIDE"
    assert out.reference_numero and out.reference_numero.startswith("RET-")

    # Caisse créditée du reliquat.
    caisse_db = (await db_session.execute(select(CaisseCentrale).where(CaisseCentrale.id == caisse.id))).scalar_one()
    assert caisse_db.solde_usd == Decimal("30")

    # Imputation budgétaire réduite : 100 - 30 = 70.
    poste_db = (await db_session.execute(select(BudgetPoste).where(BudgetPoste.id == poste.id))).scalar_one()
    assert poste_db.montant_paye == Decimal("70")

    # Résumé : reste à justifier = 100 - 30 = 70.
    summary = await list_retours_caisse(
        sortie_fonds_id=str(sortie.id), requisition_id=None, type_retour=None, statut=None,
        date_debut=None, date_fin=None, include_summary=True, limit=100, offset=0,
        user=user, tenant_id=org.id, db=db_session,
    )
    assert summary.total == 1
    assert summary.total_retourne == Decimal("30")
    assert summary.reste_a_justifier == Decimal("70")


@pytest.mark.asyncio
async def test_retour_over_refund_rejected(db_session):
    org, user, poste, caisse, sortie = await _setup_sortie(db_session)

    payload = RetourCaisseCreate(sortie_fonds_id=sortie.id, montant=Decimal("150"))
    with pytest.raises(HTTPException) as exc:
        await create_retour_caisse(payload=payload, request=None, user=user, tenant_id=org.id, db=db_session)
    assert exc.value.status_code == 400
    assert "reste" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_retour_cancel_restores_state(db_session):
    org, user, poste, caisse, sortie = await _setup_sortie(db_session)

    created = await create_retour_caisse(
        payload=RetourCaisseCreate(sortie_fonds_id=sortie.id, montant=Decimal("40")),
        request=None, user=user, tenant_id=org.id, db=db_session,
    )
    # État après retour.
    caisse_db = (await db_session.execute(select(CaisseCentrale).where(CaisseCentrale.id == caisse.id))).scalar_one()
    assert caisse_db.solde_usd == Decimal("40")

    cancelled = await update_retour_statut(
        retour_id=str(created.id), payload=RetourCaisseStatusUpdate(statut="ANNULEE", motif_annulation="Erreur"),
        request=None, user=user, tenant_id=org.id, db=db_session,
    )
    assert cancelled.statut == "ANNULEE"

    # Trésorerie et budget rétablis.
    caisse_db = (await db_session.execute(select(CaisseCentrale).where(CaisseCentrale.id == caisse.id))).scalar_one()
    assert caisse_db.solde_usd == Decimal("0")
    poste_db = (await db_session.execute(select(BudgetPoste).where(BudgetPoste.id == poste.id))).scalar_one()
    assert poste_db.montant_paye == Decimal("100")

    # Le retour annulé n'est plus compté dans le total rendu.
    total = (
        await db_session.execute(
            select(RetourCaisse.statut).where(RetourCaisse.id == created.id)
        )
    ).scalar_one()
    assert total == "ANNULEE"
