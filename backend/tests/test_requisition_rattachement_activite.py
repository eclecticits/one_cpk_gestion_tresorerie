"""Rattacher après coup une réquisition, même payée, à un projet ou une activité."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.projets_activites import mouvements_projet_activite
from app.api.v1.endpoints.requisitions import RattachementActiviteIn, rattacher_activite
from app.models.organisation import Organisation
from app.models.projet_activite import ProjetActivite
from app.models.requisition import Requisition
from app.models.sortie_fonds import SortieFonds
from app.models.user import User

QUAND = datetime(2026, 5, 10, 10, 0, tzinfo=timezone.utc)


def _s() -> str:
    return uuid.uuid4().hex[:8]


class _Requete:
    client = None
    headers: dict = {}


async def _contexte(db):
    org = Organisation(nom="Rattachement", slug=f"rt-{_s()}", is_active=True)
    db.add(org)
    await db.flush()
    user = User(id=uuid.uuid4(), email=f"{_s()}@example.com", nom="Kasa", prenom="Ada", role="admin", organisation_id=org.id, active=True)
    a = ProjetActivite(organisation_id=org.id, code=f"A-{_s()}", libelle="Formation", type="ACTIVITE")
    b = ProjetActivite(organisation_id=org.id, code=f"B-{_s()}", libelle="Atelier", type="ACTIVITE")
    db.add_all([user, a, b])
    await db.flush()
    req = Requisition(
        numero_requisition=f"REQ-{_s()}", reference_numero=f"REQ-{_s()}", objet="Atelier", mode_paiement="cash",
        type_requisition="classique", status="PAYEE", examen_status="EXAMINE", montant_total=Decimal("200"),
        organisation_id=org.id, created_at=QUAND, updated_at=QUAND, is_deleted=False,
    )
    db.add(req)
    await db.flush()
    sortie = SortieFonds(
        organisation_id=org.id, type_sortie="requisition", montant_paye=Decimal("200"), mode_paiement="cash", devise="USD",
        canal="CAISSE", motif="Atelier", beneficiaire="Fournisseur", statut="VALIDE", date_paiement=QUAND,
        created_by=user.id, reference_numero=f"PAY-{_s()}", requisition_id=req.id,
    )
    db.add(sortie)
    await db.commit()
    return org, user, a, b, req, sortie


async def _rattacher(db, org, user, req, projet_id, motif="Activité oubliée à la saisie"):
    return await rattacher_activite(
        requisition_id=str(req.id), payload=RattachementActiviteIn(project_activity_id=projet_id, motif=motif),
        request=_Requete(), db=db, user=user, tenant_id=org.id,
    )


async def _sorties_du_projet(db, org, user, projet):
    m = await mouvements_projet_activite(item_id=projet.id, date_debut=None, date_fin=None, user=user, tenant_id=org.id, db=db)
    return m["totaux"]["sorties"]


@pytest.mark.asyncio
async def test_une_requisition_payee_se_rattache_et_ses_sorties_suivent(db_session):
    org, user, a, b, req, sortie = await _contexte(db_session)
    assert await _sorties_du_projet(db_session, org, user, a) == {}

    await _rattacher(db_session, org, user, req, a.id)
    await db_session.refresh(req)
    assert (req.project_activity_id, req.status) == (a.id, "PAYEE")
    # La sortie, sans projet propre, hérite de celui de la réquisition.
    assert await _sorties_du_projet(db_session, org, user, a) == {"USD": Decimal("200")}

    # Une sortie qui portait l'ancien projet est reportée sur le nouveau.
    sortie.project_activity_id = a.id
    await db_session.commit()
    resultat = await _rattacher(db_session, org, user, req, b.id, motif="Mauvaise activité")
    assert resultat["sorties_reportees"] == 1
    assert await _sorties_du_projet(db_session, org, user, a) == {}
    assert await _sorties_du_projet(db_session, org, user, b) == {"USD": Decimal("200")}


@pytest.mark.asyncio
async def test_refus_inchange_et_activite_inactive(db_session):
    org, user, a, b, req, _sortie = await _contexte(db_session)
    with pytest.raises(HTTPException) as inchange:
        await _rattacher(db_session, org, user, req, None)
    assert inchange.value.status_code == 400
    b.is_active = False
    await db_session.commit()
    with pytest.raises(HTTPException) as inactive:
        await _rattacher(db_session, org, user, req, b.id)
    assert "inactive" in inactive.value.detail
    # Retirer le rattachement reste possible.
    await _rattacher(db_session, org, user, req, a.id)
    await _rattacher(db_session, org, user, req, None, motif="Rattachement à tort")
    await db_session.refresh(req)
    assert req.project_activity_id is None
