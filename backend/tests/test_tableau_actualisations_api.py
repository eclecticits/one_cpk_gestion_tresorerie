from datetime import date, datetime, timezone, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.expert_comptable import ExpertComptable
from app.modules.tableau.models import TableauActualisation, TableauActualisationInput, TableauActualisationRow, TableauMemberIdentity, TableauImport
from app.modules.tableau.official_reference import capture_official_snapshot


async def _dataset(db, user):
    existing = (await db.execute(select(TableauActualisation.id))).scalars().all()
    situation = date(2026, 9, 30) + timedelta(days=len(existing))
    expert = ExpertComptable(numero_ordre=f"EC/26.{uuid4().hex[:5]}", nom_denomination="API NOM", type_ec="EC", categorie_personne="Personne Physique", active=True)
    db.add(expert)
    await db.commit()
    snapshot = await capture_official_snapshot(db, user)
    identity = TableauMemberIdentity(organisation_id=user.organisation_id, numero_ordre=expert.numero_ordre, numero_ordre_normalise=expert.numero_ordre, member_kind="EC", person_kind="PHYSIQUE", origin_type="OFFICIAL", reference_status="MATCHED_OFFICIAL", expert_comptable_id=expert.id)
    db.add(identity)
    await db.flush()
    actual = TableauActualisation(organisation_id=user.organisation_id, date_situation=situation, revision_number=1, actualized_at=datetime.now(timezone.utc), reference_snapshot_id=snapshot.id, ruleset_version="test", ruleset_json={}, status="completed", created_by=user.id)
    db.add(actual)
    await db.flush()
    imp = TableauImport(organisation_id=user.organisation_id, user_id=user.id, exercice="2026", date_situation=situation, source_type="personnes_physiques", file_name="api.xlsx", file_sha256="a" * 64, status="completed", total_rows=1, imported_rows=1)
    db.add(imp)
    await db.flush()
    db.add(TableauActualisationInput(actualisation_id=actual.id, import_id=imp.id, source_type="PP", date_situation=situation, file_name="api.xlsx", file_sha256="a" * 64))
    db.add(TableauActualisationRow(actualisation_id=actual.id, identity_id=identity.id, official_expert_id=expert.id, numero_ordre=expert.numero_ordre, reference_status="MATCHED_OFFICIAL", proposal_status="UPDATE_PROPOSED", official_values={"nom_denomination": "API NOM"}, proposed_values={"nom_denomination": "API NOM 2"}, field_provenance={"nom_denomination": {"source_type": "PP"}}, differences_json=[{"field": "nom_denomination"}], anomalies_json=[{"code": "TEST_ANOMALY"}]))
    await db.commit()
    return actual


@pytest.mark.asyncio
async def test_actualisations_api_liste_detail_stats_et_lignes(app_client, admin_access_token, db_session, test_admin_user):
    actual = await _dataset(db_session, test_admin_user)
    headers = {"Authorization": f"Bearer {admin_access_token}", "X-Tenant-ID": str(test_admin_user.organisation_id)}
    listed = await app_client.get("/api/v1/tableau/actualisations", headers=headers)
    assert listed.status_code == 200 and listed.json()["items"][0]["is_current"] is True
    detail = await app_client.get(f"/api/v1/tableau/actualisations/{actual.id}", headers=headers)
    assert detail.status_code == 200 and detail.json()["total_rows"] == 1
    rows = await app_client.get(f"/api/v1/tableau/actualisations/{actual.id}/lignes?limit=1", headers=headers)
    assert rows.status_code == 200 and rows.json()["total"] == 1
    ligne_id = rows.json()["items"][0]["id"]
    line = await app_client.get(f"/api/v1/tableau/actualisations/{actual.id}/lignes/{ligne_id}", headers=headers)
    assert line.status_code == 200 and line.json()["anomaly_codes"] == ["TEST_ANOMALY"]
    stats = await app_client.get(f"/api/v1/tableau/actualisations/{actual.id}/stats", headers=headers)
    assert stats.status_code == 200 and stats.json()["proposal_status"]["UPDATE_PROPOSED"] == 1


@pytest.mark.asyncio
async def test_actualisations_api_filtres_recherche_et_limites(app_client, admin_access_token, db_session, test_admin_user):
    actual = await _dataset(db_session, test_admin_user)
    headers = {"Authorization": f"Bearer {admin_access_token}", "X-Tenant-ID": str(test_admin_user.organisation_id)}
    base = f"/api/v1/tableau/actualisations/{actual.id}/lignes"
    assert (await app_client.get(base + "?proposal_status=CONFLICT", headers=headers)).json()["total"] == 0
    assert (await app_client.get(base + "?has_anomalies=true", headers=headers)).status_code == 200
    assert (await app_client.get(base + "?q=api%20nom", headers=headers)).json()["total"] == 1
    assert (await app_client.get(base + "?limit=0", headers=headers)).status_code == 422
    assert (await app_client.get(base + "?sort=not_allowed", headers=headers)).status_code == 422


@pytest.mark.asyncio
async def test_actualisations_api_auth_et_isolation(app_client, admin_access_token, test_admin_user):
    headers = {"Authorization": f"Bearer {admin_access_token}", "X-Tenant-ID": str(test_admin_user.organisation_id)}
    assert (await app_client.get("/api/v1/tableau/actualisations", headers=headers)).status_code == 200
    assert (await app_client.get("/api/v1/tableau/actualisations/999999", headers=headers)).status_code == 404
    assert (await app_client.get("/api/v1/tableau/actualisations")).status_code == 401
