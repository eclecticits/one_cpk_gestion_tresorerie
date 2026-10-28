"""Projet d'une sortie directe programmée : facultatif, choisi à la programmation."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.ordres_decaissement import create_ordre_decaissement, update_ordre_decaissement
from app.api.v1.endpoints.sorties_fonds import _projet_sortie_directe
from app.models.ordre_decaissement import OrdreDecaissement
from app.models.caisse_centrale import CaisseCentrale
from app.models.organisation import Organisation
from app.models.projet_activite import ProjetActivite
from app.models.service import Service
from app.models.user import User
from app.schemas.ordre_decaissement import OrdreDecaissementCreate


async def _contexte(db):
    org = Organisation(nom="Projet direct", slug=f"pd-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    service = Service(organisation_id=org.id, code=f"S{uuid.uuid4().hex[:4]}", libelle="Secrétariat", is_active=True)
    user = User(id=uuid.uuid4(), email=f"pd-{uuid.uuid4().hex[:6]}@example.com", role="admin", organisation_id=org.id)
    projet = ProjetActivite(organisation_id=org.id, code=f"P-{uuid.uuid4().hex[:6]}", libelle="Formation", type="PROJET")
    db.add_all([service, user, projet])
    db.add(CaisseCentrale(organisation_id=org.id, est_ouverte=True, solde_usd=Decimal("5000"), solde_cdf=0))
    await db.commit()
    return org, user, service, projet


def _payload(service, **extra) -> OrdreDecaissementCreate:
    return OrdreDecaissementCreate(
        requisition_id=None, beneficiaire="Secrétaire général", montant=Decimal("40"),
        devise="USD", service_id=service.id, motif="Achat urgent", **extra,
    )


@pytest.mark.asyncio
async def test_projet_choisi_a_la_programmation_puis_corrige(db_session):
    org, user, service, projet = await _contexte(db_session)
    appel = dict(request=None, user=user, tenant_id=org.id, db=db_session)

    sans = await create_ordre_decaissement(payload=_payload(service), **appel)
    assert sans["project_activity_id"] is None

    with pytest.raises(HTTPException) as exc:
        await create_ordre_decaissement(payload=_payload(service, project_activity_id=999_999), **appel)
    assert exc.value.status_code == 400

    ordre = await create_ordre_decaissement(payload=_payload(service, project_activity_id=projet.id), **appel)
    assert ordre["project_activity_id"] == projet.id

    # Désactivé depuis : corriger le bon sans changer de projet reste possible.
    projet.is_active = False
    await db_session.commit()
    corrige = await update_ordre_decaissement(
        ordre_id=str(ordre["id"]), payload=_payload(service, project_activity_id=projet.id), **appel
    )
    assert corrige["project_activity_id"] == projet.id

    retire = await update_ordre_decaissement(ordre_id=str(ordre["id"]), payload=_payload(service), **appel)
    assert retire["project_activity_id"] is None


@pytest.mark.asyncio
async def test_paiement_conserve_le_projet_desactive_de_l_ordre(db_session):
    org, _user, _service, projet = await _contexte(db_session)
    ordre = OrdreDecaissement(organisation_id=org.id, project_activity_id=projet.id)

    projet.is_active = False
    await db_session.commit()

    assert await _projet_sortie_directe(
        db_session,
        tenant_id=org.id,
        ordre=ordre,
        project_activity_id=projet.id,
    ) == projet.id

    # Un autre identifiant ne bénéficie pas de l'héritage historique.
    with pytest.raises(HTTPException) as exc:
        await _projet_sortie_directe(
            db_session,
            tenant_id=org.id,
            ordre=ordre,
            project_activity_id=999_999,
        )
    assert exc.value.status_code == 400
