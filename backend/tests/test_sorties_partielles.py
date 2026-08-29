"""Paiement partiel (complément) d'une réquisition classique.

Vérifie le mécanisme ajouté à create_sortie_fonds :
- un paiement inférieur au total laisse la réquisition EN_DECAISSEMENT ;
- les compléments cumulent jusqu'à solder la réquisition (PAYEE) ;
- tout dépassement du reste dû est refusé ;
- l'endpoint /solde renvoie le reste à payer.

Mode d'intégration comptable par défaut (aucune société comptable) => aucune
écriture générée : on se concentre sur trésorerie + budget + statut.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select

from app.api.v1.endpoints.sorties_fonds import (
    create_sortie_fonds,
    get_requisition_solde,
    update_sortie_statut,
)
from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.caisse_centrale import CaisseCentrale
from app.models.ligne_requisition import LigneRequisition
from app.models.organisation import Organisation
from app.models.requisition import Requisition
from app.models.sortie_fonds import SortieFonds
from app.models.user import User
from app.schemas.sortie_fonds import SortieFondsCreate, SortieFondsStatusUpdate


async def _setup(db_session, *, montant_total=Decimal("100"), solde_caisse=Decimal("500")):
    org = Organisation(nom="Partiel Test", slug=f"part-{uuid.uuid4().hex[:8]}", is_active=True)
    db_session.add(org)
    await db_session.flush()

    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
    db_session.add(exercice)
    await db_session.flush()

    poste = BudgetPoste(
        organisation_id=org.id,
        exercice_id=exercice.id,
        code="DEP-PART-001",
        libelle="Poste dépense",
        type="DEPENSE",
        active=True,
        montant_prevu=Decimal("100000"),
        montant_engage=0,
        montant_paye=0,
        is_deleted=False,
    )
    db_session.add(poste)
    db_session.add(CaisseCentrale(organisation_id=org.id, est_ouverte=True, solde_usd=solde_caisse, solde_cdf=0))
    await db_session.flush()

    user = User(id=uuid.uuid4(), email=f"part-{uuid.uuid4().hex[:6]}@example.com", role="admin", organisation_id=org.id)
    # Sans persistance, l'historique de statut écrit par le paiement référence un
    # auteur introuvable et le contrôle multi-tenant rejette le flush.
    db_session.add(user)

    req = Requisition(
        id=uuid.uuid4(),
        numero_requisition=f"REQ-{uuid.uuid4().hex[:6]}",
        objet="Mission terrain",
        mode_paiement="cash",
        type_requisition="classique",
        status="APPROUVEE",
        montant_total=montant_total,
        devise="USD",
        organisation_id=org.id,
        decaissement_progressif=False,
    )
    db_session.add(req)
    await db_session.flush()

    ligne = LigneRequisition(
        organisation_id=org.id,
        requisition_id=req.id,
        budget_poste_id=poste.id,
        rubrique="Frais",
        description="Frais de mission",
        quantite=1,
        montant_unitaire=montant_total,
        montant_total=montant_total,
        devise="USD",
    )
    db_session.add(ligne)
    await db_session.commit()
    return org, user, poste, req


def _payload(req_id, montant):
    return SortieFondsCreate(
        type_sortie="requisition",
        requisition_id=req_id,
        montant_paye=Decimal(str(montant)),
        mode_paiement="cash",
        devise="USD",
        canal="CAISSE",
        motif="Paiement mission",
        beneficiaire="Agent X",
    )


@pytest.mark.asyncio
async def test_paiement_partiel_laisse_en_decaissement(db_session):
    org, user, poste, req = await _setup(db_session)

    out = await create_sortie_fonds(payload=_payload(req.id, 40), request=None, background_tasks=BackgroundTasks(), user=user, tenant_id=org.id, db=db_session)
    assert Decimal(str(out.montant_paye)) == Decimal("40")

    req_db = (await db_session.execute(select(Requisition).where(Requisition.id == req.id))).scalar_one()
    assert req_db.status == "EN_DECAISSEMENT"

    poste_db = (await db_session.execute(select(BudgetPoste).where(BudgetPoste.id == poste.id))).scalar_one()
    assert poste_db.montant_paye == Decimal("40")  # seule la part payée est imputée

    solde = await get_requisition_solde(req_id=str(req.id), user=user, tenant_id=org.id, db=db_session)
    assert solde["total_paye"] == 40.0
    assert solde["reste"] == 60.0
    assert solde["soldee"] is False


@pytest.mark.asyncio
async def test_complement_solde_la_requisition(db_session):
    org, user, poste, req = await _setup(db_session)

    await create_sortie_fonds(payload=_payload(req.id, 40), request=None, background_tasks=BackgroundTasks(), user=user, tenant_id=org.id, db=db_session)
    await create_sortie_fonds(payload=_payload(req.id, 60), request=None, background_tasks=BackgroundTasks(), user=user, tenant_id=org.id, db=db_session)

    req_db = (await db_session.execute(select(Requisition).where(Requisition.id == req.id))).scalar_one()
    assert req_db.status == "PAYEE"

    solde = await get_requisition_solde(req_id=str(req.id), user=user, tenant_id=org.id, db=db_session)
    assert solde["reste"] == 0.0
    assert solde["soldee"] is True

    # Deux sorties valides rattachées, cumul = 100.
    total = (
        await db_session.execute(
            select(SortieFonds.montant_paye).where(SortieFonds.requisition_id == req.id, SortieFonds.statut == "VALIDE")
        )
    ).scalars().all()
    assert sum(Decimal(str(m)) for m in total) == Decimal("100")


@pytest.mark.asyncio
async def test_depassement_du_reste_refuse(db_session):
    org, user, poste, req = await _setup(db_session)

    # 1er paiement partiel de 70 -> reste 30.
    await create_sortie_fonds(payload=_payload(req.id, 70), request=None, background_tasks=BackgroundTasks(), user=user, tenant_id=org.id, db=db_session)

    # Complément de 50 > reste 30 -> refusé.
    with pytest.raises(HTTPException) as exc:
        await create_sortie_fonds(payload=_payload(req.id, 50), request=None, background_tasks=BackgroundTasks(), user=user, tenant_id=org.id, db=db_session)
    assert exc.value.status_code == 400
    assert "reste" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_requisition_soldee_refuse_nouveau_paiement(db_session):
    org, user, poste, req = await _setup(db_session)

    await create_sortie_fonds(payload=_payload(req.id, 100), request=None, background_tasks=BackgroundTasks(), user=user, tenant_id=org.id, db=db_session)
    req_db = (await db_session.execute(select(Requisition).where(Requisition.id == req.id))).scalar_one()
    assert req_db.status == "PAYEE"

    # Réquisition PAYEE : n'est plus dans les statuts payables.
    with pytest.raises(HTTPException) as exc:
        await create_sortie_fonds(payload=_payload(req.id, 10), request=None, background_tasks=BackgroundTasks(), user=user, tenant_id=org.id, db=db_session)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_annulation_complement_rend_requisition_approuvee(db_session):
    org, user, poste, req = await _setup(db_session, solde_caisse=Decimal("500"))

    out = await create_sortie_fonds(payload=_payload(req.id, 40), request=None, background_tasks=BackgroundTasks(), user=user, tenant_id=org.id, db=db_session)
    caisse_avant = (
        await db_session.execute(select(CaisseCentrale).where(CaisseCentrale.organisation_id == org.id))
    ).scalar_one()
    assert caisse_avant.solde_usd == Decimal("460")  # 500 - 40

    await update_sortie_statut(
        sortie_id=str(out.id),
        payload=SortieFondsStatusUpdate(statut="ANNULEE", motif_annulation="Erreur de saisie"),
        request=None,
        user=user,
        tenant_id=org.id,
        db=db_session,
    )

    # Réquisition revenue à APPROUVEE (plus aucune sortie valide).
    req_db = (await db_session.execute(select(Requisition).where(Requisition.id == req.id))).scalar_one()
    assert req_db.status == "APPROUVEE"

    # Trésorerie et budget rétablis.
    caisse_db = (
        await db_session.execute(select(CaisseCentrale).where(CaisseCentrale.organisation_id == org.id))
    ).scalar_one()
    assert caisse_db.solde_usd == Decimal("500")
    poste_db = (await db_session.execute(select(BudgetPoste).where(BudgetPoste.id == poste.id))).scalar_one()
    assert poste_db.montant_paye == Decimal("0")
