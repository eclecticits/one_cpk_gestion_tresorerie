"""Circuit du dossier de réquisitions, de bout en bout par l'API HTTP.

Le circuit tel que le vivent les écrans :

    constitution  ->  POST /dossiers                    dossier BROUILLON
    soumission    ->  POST /dossiers/{id}/submit-examen dossier EN_EXAMEN
    examen        ->  POST /dossiers/{id}/validate-examen  dossier TRAITEMENT
                  ou  POST /dossiers/{id}/reject-examen    dossier REJETE

Les tests existants (test_submit_requisition_examen.py) attaquent la couche
service. Ceux-ci passent par les endpoints, avec les statuts qu'observe
ensuite l'écran /validation, plus les garde-fous du circuit.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.models.requisition import Requisition
from app.models.service import Service


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _creer_requisition(db_session, *, organisation_id: int, service_id: int | None = None):
    """Une réquisition signée par son service, prête à entrer dans un dossier."""
    req = Requisition(
        numero_requisition=f"REQ-DOS-{uuid.uuid4().hex[:8]}",
        reference_numero=f"REQ-DOS-{uuid.uuid4().hex[:8]}",
        objet="Réquisition du circuit dossier",
        mode_paiement="cash",
        type_requisition="classique",
        status="SIGNEE_SERVICE",
        examen_status="NON_EXAMINE",
        montant_total=Decimal("75.00"),
        organisation_id=organisation_id,
        service_id=service_id,
        created_at=_utcnow(),
        updated_at=_utcnow(),
        is_deleted=False,
    )
    db_session.add(req)
    await db_session.flush()
    return req


async def _statuts(app_client: AsyncClient, headers: dict, *ids: str) -> dict[str, dict]:
    """Relit les réquisitions une à une par le filtre `id` de la liste."""
    etats = {}
    for rid in ids:
        resp = await app_client.get(
            "/api/v1/requisitions", params={"id": rid, "limit": 1}, headers=headers
        )
        assert resp.status_code == 200, resp.text
        corps = resp.json()
        assert len(corps) == 1, f"réquisition {rid} introuvable"
        etats[rid] = corps[0]
    return etats


@pytest.mark.asyncio
async def test_circuit_dossier_jusqu_a_la_validation(
    app_client: AsyncClient, admin_access_token: str, test_organisation, db_session
):
    org_id = test_organisation.id
    headers = {"Authorization": f"Bearer {admin_access_token}"}

    service = Service(
        code=f"SRV-DOS-{uuid.uuid4().hex[:6]}", libelle="Commission dossier", organisation_id=org_id
    )
    db_session.add(service)
    await db_session.flush()

    req_a = await _creer_requisition(db_session, organisation_id=org_id, service_id=service.id)
    req_b = await _creer_requisition(db_session, organisation_id=org_id, service_id=service.id)
    await db_session.commit()
    id_a, id_b = str(req_a.id), str(req_b.id)

    # 1. Constitution du dossier.
    resp = await app_client.post(
        "/api/v1/dossiers",
        json={"requisition_ids": [id_a, id_b], "description": "Dossier du circuit"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    dossier = resp.json()
    dossier_id = dossier["id"]
    assert dossier["status"] == "BROUILLON"
    assert dossier["reference"], "le dossier doit recevoir une référence"

    etats = await _statuts(app_client, headers, id_a, id_b)
    assert {e["dossier_id"] for e in etats.values()} == {dossier_id}
    assert {e["examen_status"] for e in etats.values()} == {"NON_EXAMINE"}

    # Garde-fou : une réquisition déjà rattachée ne peut pas entrer ailleurs.
    resp = await app_client.post(
        "/api/v1/dossiers", json={"requisition_ids": [id_a]}, headers=headers
    )
    assert resp.status_code == 400, resp.text
    assert "déjà rattachée" in resp.json()["detail"]

    # Garde-fou : on n'examine pas un dossier qui n'a pas été soumis.
    resp = await app_client.post(
        f"/api/v1/dossiers/{dossier_id}/validate-examen", json={}, headers=headers
    )
    assert resp.status_code == 400, resp.text
    assert "en examen" in resp.json()["detail"].lower()

    # 2. Soumission à l'examen.
    resp = await app_client.post(f"/api/v1/dossiers/{dossier_id}/submit-examen", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "EN_EXAMEN"

    etats = await _statuts(app_client, headers, id_a, id_b)
    assert {e["examen_status"] for e in etats.values()} == {"EN_EXAMEN"}
    # Rattachées à un service : elles attendent la signature de la commission.
    assert {e["status"] for e in etats.values()} == {"EN_ATTENTE_COMMISSION"}

    # Garde-fou : pas de double soumission.
    resp = await app_client.post(f"/api/v1/dossiers/{dossier_id}/submit-examen", headers=headers)
    assert resp.status_code == 400, resp.text
    assert "déjà soumis" in resp.json()["detail"]

    # 3. Examen validé : le dossier part en traitement.
    resp = await app_client.post(
        f"/api/v1/dossiers/{dossier_id}/validate-examen",
        json={"commentaires_examen": "Pièces conformes"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "TRAITEMENT"

    etats = await _statuts(app_client, headers, id_a, id_b)
    assert {e["examen_status"] for e in etats.values()} == {"EXAMINE"}
    assert {e["examen_commentaire"] for e in etats.values()} == {"Pièces conformes"}

    # 4. Ce que voit l'écran /validation : il ne liste que l'examiné.
    resp = await app_client.get(
        "/api/v1/requisitions",
        params={
            "examen_status": "EXAMINE",
            "include": "demandeur,validateur,approbateur,examinateur,caissier,annexe",
            "order": "created_at.desc",
            "limit": 200,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    listes = {item["id"] for item in resp.json()}
    assert {id_a, id_b} <= listes

    # Et le dossier apparaît dans la section « Dossiers en traitement ».
    resp = await app_client.get(
        "/api/v1/dossiers", params={"include_requisitions": True, "limit": 200}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    par_id = {d["id"]: d for d in resp.json()}
    assert par_id[dossier_id]["status"] == "TRAITEMENT"


@pytest.mark.asyncio
async def test_circuit_dossier_examen_rejete(
    app_client: AsyncClient, admin_access_token: str, test_organisation, db_session
):
    org_id = test_organisation.id
    headers = {"Authorization": f"Bearer {admin_access_token}"}

    service = Service(
        code=f"SRV-REJ-{uuid.uuid4().hex[:6]}", libelle="Commission rejet", organisation_id=org_id
    )
    db_session.add(service)
    await db_session.flush()

    req_a = await _creer_requisition(db_session, organisation_id=org_id, service_id=service.id)
    req_b = await _creer_requisition(db_session, organisation_id=org_id, service_id=service.id)
    await db_session.commit()
    id_a, id_b = str(req_a.id), str(req_b.id)

    resp = await app_client.post(
        "/api/v1/dossiers", json={"requisition_ids": [id_a, id_b]}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    dossier_id = resp.json()["id"]

    resp = await app_client.post(f"/api/v1/dossiers/{dossier_id}/submit-examen", headers=headers)
    assert resp.status_code == 200, resp.text

    resp = await app_client.post(
        f"/api/v1/dossiers/{dossier_id}/reject-examen",
        json={"commentaires_examen": "Justificatifs manquants"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "REJETE"

    etats = await _statuts(app_client, headers, id_a, id_b)
    assert {e["examen_status"] for e in etats.values()} == {"REJETE"}
    assert {e["examen_commentaire"] for e in etats.values()} == {"Justificatifs manquants"}

    # Le rejet sort les réquisitions de l'écran /validation.
    resp = await app_client.get(
        "/api/v1/requisitions",
        params={"examen_status": "EXAMINE", "limit": 200},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    listes = {item["id"] for item in resp.json()}
    assert not ({id_a, id_b} & listes)


@pytest.mark.asyncio
async def test_dossier_a_une_seule_requisition_libere_la_requisition(
    app_client: AsyncClient, admin_access_token: str, test_organisation, db_session
):
    """Cas particulier du circuit : un dossier d'une seule pièce.

    L'examen validé détache la réquisition et rend le dossier au brouillon,
    au lieu de le faire passer en traitement.
    """
    org_id = test_organisation.id
    headers = {"Authorization": f"Bearer {admin_access_token}"}

    # Sans service : la notification « bureau » de ce chemin ne se déclenche
    # que pour une réquisition de commission, et elle construit un PDF
    # officiel qui n'a pas sa place dans un test de circuit.
    req = await _creer_requisition(db_session, organisation_id=org_id, service_id=None)
    await db_session.commit()
    req_id = str(req.id)

    resp = await app_client.post(
        "/api/v1/dossiers", json={"requisition_ids": [req_id]}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    dossier_id = resp.json()["id"]

    resp = await app_client.post(f"/api/v1/dossiers/{dossier_id}/submit-examen", headers=headers)
    assert resp.status_code == 200, resp.text
    # Sans service rattaché, la réquisition attend directement la validation.
    etats = await _statuts(app_client, headers, req_id)
    assert etats[req_id]["status"] == "EN_ATTENTE"

    resp = await app_client.post(
        f"/api/v1/dossiers/{dossier_id}/validate-examen", json={}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "BROUILLON"

    etats = await _statuts(app_client, headers, req_id)
    assert etats[req_id]["examen_status"] == "EXAMINE"
    assert etats[req_id]["dossier_id"] is None
