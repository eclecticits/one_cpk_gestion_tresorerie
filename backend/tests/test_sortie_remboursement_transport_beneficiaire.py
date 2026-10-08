"""Sortie de fonds d'un remboursement transport : le bénéficiaire vient de la caisse.

La réquisition d'un remboursement transport ne désigne aucun bénéficiaire (elle
paie plusieurs participants). Le formulaire de sortie laisse donc la caisse
nommer la personne qui reçoit l'argent ; l'API doit accepter ce nom et le
conserver sur la pièce, et refuser une sortie qui n'en désigne aucun.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select

from app.api.v1.endpoints.sorties_fonds import create_sortie_fonds
from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.caisse_centrale import CaisseCentrale
from app.models.ligne_requisition import LigneRequisition
from app.models.organisation import Organisation
from app.models.requisition import Requisition
from app.models.sortie_fonds import SortieFonds
from app.models.user import User
from app.schemas.sortie_fonds import SortieFondsCreate


async def _setup(db_session, *, montant_total=Decimal("60")):
    org = Organisation(nom="Transport Test", slug=f"rt-{uuid.uuid4().hex[:8]}", is_active=True)
    db_session.add(org)
    await db_session.flush()

    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
    db_session.add(exercice)
    await db_session.flush()

    poste = BudgetPoste(
        organisation_id=org.id,
        exercice_id=exercice.id,
        code="DEP-RT-001",
        libelle="Frais de transport",
        type="DEPENSE",
        active=True,
        montant_prevu=Decimal("100000"),
        montant_engage=0,
        montant_paye=0,
        is_deleted=False,
    )
    db_session.add(poste)
    db_session.add(CaisseCentrale(organisation_id=org.id, est_ouverte=True, solde_usd=Decimal("500"), solde_cdf=0))
    await db_session.flush()

    user = User(id=uuid.uuid4(), email=f"rt-{uuid.uuid4().hex[:6]}@example.com", role="admin", organisation_id=org.id)
    db_session.add(user)

    # Comme la crée l'écran Remboursement transport : ni beneficiaire ni
    # instance_beneficiaire.
    req = Requisition(
        id=uuid.uuid4(),
        numero_requisition=f"REQ-{uuid.uuid4().hex[:6]}",
        objet="Remboursement des frais de transport des participants",
        mode_paiement="cash",
        type_requisition="remboursement_transport",
        status="APPROUVEE",
        montant_total=montant_total,
        devise="USD",
        organisation_id=org.id,
        decaissement_progressif=False,
    )
    db_session.add(req)
    await db_session.flush()

    db_session.add(
        LigneRequisition(
            organisation_id=org.id,
            requisition_id=req.id,
            budget_poste_id=poste.id,
            rubrique="Remboursement transport",
            description="Frais de transport",
            quantite=1,
            montant_unitaire=montant_total,
            montant_total=montant_total,
            devise="USD",
        )
    )
    await db_session.commit()
    return org, user, req


def _payload(req_id, beneficiaire):
    return SortieFondsCreate(
        type_sortie="remboursement",
        requisition_id=req_id,
        montant_paye=Decimal("60"),
        mode_paiement="cash",
        devise="USD",
        canal="CAISSE",
        motif="Remboursement transport",
        beneficiaire=beneficiaire,
    )


@pytest.mark.asyncio
async def test_beneficiaire_saisi_par_la_caisse_est_retenu(db_session):
    org, user, req = await _setup(db_session)

    out = await create_sortie_fonds(
        payload=_payload(req.id, "  Jean Kabila  "),
        request=None,
        background_tasks=BackgroundTasks(),
        user=user,
        tenant_id=org.id,
        db=db_session,
    )

    sortie = (await db_session.execute(select(SortieFonds).where(SortieFonds.id == out.id))).scalar_one()
    assert sortie.beneficiaire == "Jean Kabila"
    assert sortie.type_sortie == "remboursement"


@pytest.mark.asyncio
async def test_sans_beneficiaire_la_sortie_est_refusee(db_session):
    org, user, req = await _setup(db_session)

    with pytest.raises(HTTPException) as exc:
        await create_sortie_fonds(
            payload=_payload(req.id, ""),
            request=None,
            background_tasks=BackgroundTasks(),
            user=user,
            tenant_id=org.id,
            db=db_session,
        )
    assert exc.value.status_code == 400
    assert "Bénéficiaire requis" in str(exc.value.detail)
