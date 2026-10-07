"""Brouillons de remboursement de transport.

Ce que ces tests tiennent :
- un brouillon s'enregistre incomplet (pas de poste, pas de montants) et se
  reprend tel quel ;
- il ne consomme ni numéro REM ni réquisition ;
- un membre d'un autre service ne le voit pas et ne peut pas le modifier.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.api.v1.endpoints import remboursements_transport as rt
from app.models.organisation import Organisation
from app.models.remboursement_transport import RemboursementTransport
from app.models.requisition import Requisition
from app.models.service import Service
from app.models.user import User
from app.schemas.remboursement_transport import RemboursementTransportBrouillonSave


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


async def _contexte(db):
    org = Organisation(nom="Brouillons transport", slug=f"rtb-{_suffix()}", is_active=True)
    db.add(org)
    await db.flush()
    commission = Service(organisation_id=org.id, code=f"C{_suffix()[:6]}", libelle=f"Commission {_suffix()}")
    autre = Service(organisation_id=org.id, code=f"A{_suffix()[:6]}", libelle=f"Autre {_suffix()}")
    user = User(id=uuid.uuid4(), email=f"{_suffix()}@ex.com", role="user", organisation_id=org.id)
    db.add_all([commission, autre, user])
    await db.commit()
    return org, commission, autre, user


@pytest.fixture
def services_de(monkeypatch):
    """Restreint l'utilisateur aux services donnés (pas de vue globale)."""

    def poser(service_ids: list[int]):
        async def non(*_a, **_k):
            return False

        async def ids(*_a, **_k):
            return service_ids

        monkeypatch.setattr(rt, "can_view_all_services", non)
        monkeypatch.setattr(rt, "get_user_service_ids", ids)

    return poser


CONTENU = {
    "formData": {"type_reunion": "commission", "date_reunion": "2026-10-09", "lieu": "Siège"},
    "participants": [{"nom": "Jean Mukendi", "titre_fonction": "Président", "montant": 0, "present": True}],
    "assistants": [],
}


@pytest.mark.asyncio
async def test_brouillon_incomplet_se_reprend_sans_numero_ni_requisition(db_session, services_de):
    org, commission, _autre, user = await _contexte(db_session)
    services_de([commission.id])
    rem_avant = await db_session.scalar(select(func.count()).select_from(RemboursementTransport))
    req_avant = await db_session.scalar(select(func.count()).select_from(Requisition))

    cree = await rt.create_brouillon(
        payload=RemboursementTransportBrouillonSave(service_id=commission.id, contenu=CONTENU),
        user=user, tenant_id=org.id, db=db_session,
    )
    assert cree.contenu == CONTENU

    contenu2 = {**CONTENU, "formData": {**CONTENU["formData"], "lieu": "Salle B"}}
    maj = await rt.update_brouillon(
        brouillon_id=str(cree.id),
        payload=RemboursementTransportBrouillonSave(service_id=commission.id, contenu=contenu2),
        user=user, tenant_id=org.id, db=db_session,
    )
    assert maj.contenu["formData"]["lieu"] == "Salle B"

    liste = await rt.list_brouillons(service_id=None, user=user, tenant_id=org.id, db=db_session)
    assert [b.id for b in liste] == [cree.id]

    assert await db_session.scalar(select(func.count()).select_from(RemboursementTransport)) == rem_avant
    assert await db_session.scalar(select(func.count()).select_from(Requisition)) == req_avant

    await rt.delete_brouillon(brouillon_id=str(cree.id), user=user, tenant_id=org.id, db=db_session)
    assert await rt.list_brouillons(service_id=None, user=user, tenant_id=org.id, db=db_session) == []


@pytest.mark.asyncio
async def test_brouillon_reserve_au_service(db_session, services_de):
    org, commission, autre, user = await _contexte(db_session)
    services_de([commission.id])
    cree = await rt.create_brouillon(
        payload=RemboursementTransportBrouillonSave(service_id=commission.id, contenu=CONTENU),
        user=user, tenant_id=org.id, db=db_session,
    )

    with pytest.raises(HTTPException) as exc:
        await rt.create_brouillon(
            payload=RemboursementTransportBrouillonSave(service_id=autre.id, contenu=CONTENU),
            user=user, tenant_id=org.id, db=db_session,
        )
    assert exc.value.status_code == 403

    # Un membre de l'autre service ne voit ni ne touche le brouillon.
    services_de([autre.id])
    assert await rt.list_brouillons(service_id=None, user=user, tenant_id=org.id, db=db_session) == []
    with pytest.raises(HTTPException) as exc:
        await rt.delete_brouillon(brouillon_id=str(cree.id), user=user, tenant_id=org.id, db=db_session)
    assert exc.value.status_code == 403
