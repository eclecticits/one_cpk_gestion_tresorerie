"""POST /requisitions/{id}/reject refuse une pièce payée, en décaissement ou déjà rejetée.

L'écran Validation masquait déjà le bouton dans ces cas ; le serveur, lui,
acceptait tout, et rejeter une réquisition payée libérait son engagement
budgétaire alors que l'argent était sorti.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.requisition import Requisition
from app.models.service import Service


async def _requisition(async_engine, user, *, statut: str, type_requisition: str = "classique") -> uuid.UUID:
    async with AsyncSession(async_engine) as db:
        service = Service(
            organisation_id=user.organisation_id, code=f"S{uuid.uuid4().hex[:4]}", libelle=f"Service {uuid.uuid4().hex[:6]}", is_active=True
        )
        db.add(service)
        await db.flush()
        req = Requisition(
            organisation_id=user.organisation_id,
            service_id=service.id,
            numero_requisition=f"REQ-{uuid.uuid4().hex[:8]}",
            reference_numero=f"REF-{uuid.uuid4().hex[:8]}",
            objet="Rejet",
            mode_paiement="cash",
            type_requisition=type_requisition,
            status=statut,
            examen_status="VALIDE",
            montant_total=10,
            devise="USD",
            created_by=user.id,
        )
        db.add(req)
        await db.flush()
        rid = req.id
        await db.commit()
        return rid


def _entetes(token, user):
    return {"Authorization": f"Bearer {token}", "X-Tenant-ID": str(user.organisation_id)}


@pytest.mark.parametrize("statut", ["PAYEE", "EN_DECAISSEMENT", "REJETEE"])
async def test_rejet_refuse_hors_decision(app_client, admin_access_token, test_admin_user, async_engine, statut):
    rid = await _requisition(async_engine, test_admin_user, statut=statut)
    r = await app_client.post(
        f"/api/v1/requisitions/{rid}/reject",
        json={"motif_rejet": "Trop tard"},
        headers=_entetes(admin_access_token, test_admin_user),
    )
    assert r.status_code == 400, r.text
    async with AsyncSession(async_engine) as db:
        assert (await db.get(Requisition, rid)).status == statut


@pytest.mark.parametrize(
    "statut,type_requisition",
    [("EN_ATTENTE", "classique"), ("AUTORISEE", "remboursement_transport"), ("APPROUVEE", "classique")],
)
async def test_rejet_accepte_en_cours_de_decision(
    app_client, admin_access_token, test_admin_user, async_engine, statut, type_requisition
):
    rid = await _requisition(async_engine, test_admin_user, statut=statut, type_requisition=type_requisition)
    r = await app_client.post(
        f"/api/v1/requisitions/{rid}/reject",
        json={"motif_rejet": "Pièces manquantes"},
        headers=_entetes(admin_access_token, test_admin_user),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "REJETEE"
