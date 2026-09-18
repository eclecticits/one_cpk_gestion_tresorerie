"""Parcours réel de la collation, du login à l'ordre créé.

Passe par l'application entière — routage, authentification, schémas, règles —
comme le ferait le navigateur de la caisse. Les tests unitaires appellent la
fonction ; celui-ci frappe l'URL.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


@pytest.mark.asyncio(loop_scope="session")
async def test_parcours_collation_par_http(app_client: AsyncClient, admin_access_token, async_engine: AsyncEngine):
    from app.models.caisse_centrale import CaisseCentrale
    from app.models.organisation import Organisation
    from app.models.service import Service
    from sqlalchemy import select

    from tests.conftest import E2E_ORG_SLUG

    # L'organisation se relit ici plutôt que par l'objet de la fixture : celui-ci
    # est détaché de sa session, et lire un de ses attributs le rechargerait hors
    # contexte.
    async with AsyncSession(async_engine) as session:
        org_id = (
            await session.execute(select(Organisation.id).where(Organisation.slug == E2E_ORG_SLUG))
        ).scalar_one()
    entetes = {"Authorization": f"Bearer {admin_access_token}", "X-Tenant-ID": str(org_id)}

    async with AsyncSession(async_engine, expire_on_commit=False) as session:
        service = (
            await session.execute(select(Service).where(Service.organisation_id == org_id).limit(1))
        ).scalar_one_or_none()
        if service is None:
            service = Service(
                organisation_id=org_id, code=f"S{uuid.uuid4().hex[:4]}", libelle="Secrétariat", is_active=True
            )
            session.add(service)
        if (
            await session.execute(select(CaisseCentrale).where(CaisseCentrale.organisation_id == org_id))
        ).scalar_one_or_none() is None:
            session.add(
                CaisseCentrale(organisation_id=org_id, est_ouverte=True, solde_usd=Decimal("9000"), solde_cdf=0)
            )
        await session.commit()
        service_id = service.id

    # 1. Les plafonds sont annoncés à l'écran avant tout refus.
    reglages = await app_client.get("/api/v1/organisation/settings", headers=entetes)
    assert reglages.status_code == 200

    reunion = f"Conseil d'administration {uuid.uuid4().hex[:6]}"

    def corps(**extra):
        base = {
            "beneficiaire": "Secrétaire général",
            "devise": "USD",
            "service_id": service_id,
            "motif": "Dépense directe",
        }
        base.update(extra)
        return base

    # 2. Vingt têtes à cinq dollars : la salle tient sous son plafond.
    ok = await app_client.post(
        "/api/v1/ordres-decaissement",
        headers=entetes,
        json=corps(
            montant=1,
            type_sortie="COLLATION",
            reunion_intitule=reunion,
            reunion_date="2026-09-18",
            participants=20,
            montant_par_personne=5,
        ),
    )
    assert ok.status_code == 201, ok.text
    assert Decimal(str(ok.json()["montant"])) == Decimal("100.00")
    assert ok.json()["participants"] == 20

    # 3. Le même montant en sortie simple reste refusé.
    simple = await app_client.post(
        "/api/v1/ordres-decaissement", headers=entetes, json=corps(montant=200)
    )
    assert simple.status_code == 400

    # 4. Deux cents dollars pour deux personnes n'est pas une collation.
    cher = await app_client.post(
        "/api/v1/ordres-decaissement",
        headers=entetes,
        json=corps(
            montant=1,
            type_sortie="COLLATION",
            reunion_intitule=f"Bureau {uuid.uuid4().hex[:6]}",
            reunion_date="2026-09-18",
            participants=2,
            montant_par_personne=200,
        ),
    )
    assert cher.status_code == 400

    # 5. La même réunion ne se sert pas deux fois pour contourner le total :
    #    ce second ordre tient sous le plafond d'une réunion, mais pas une fois
    #    ajouté au premier.
    encore = await app_client.post(
        "/api/v1/ordres-decaissement",
        headers=entetes,
        json=corps(
            montant=1,
            type_sortie="COLLATION",
            reunion_intitule=reunion,
            reunion_date="2026-09-18",
            participants=15,
            montant_par_personne=5,
        ),
    )
    assert encore.status_code == 400
    assert "Fractionnement" in encore.json()["detail"]

    # 6. Et la collation n'a bloqué aucune sortie directe simple du même agent.
    apres = await app_client.post(
        "/api/v1/ordres-decaissement", headers=entetes, json=corps(montant=90)
    )
    assert apres.status_code == 201, apres.text

    # 7. L'ordre se relit tel qu'il a été créé.
    liste = await app_client.get(
        "/api/v1/ordres-decaissement", headers=entetes, params={"sans_requisition": True, "limit": 5}
    )
    assert liste.status_code == 200
    collations = [i for i in liste.json()["items"] if i.get("type_sortie") == "COLLATION"]
    assert collations, "la collation doit se relire dans la liste des sorties directes"
    assert collations[0]["participants"] == 20
    assert collations[0]["reunion_intitule"] == reunion
