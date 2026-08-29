from __future__ import annotations

import asyncio
import io
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.security import create_access_token, hash_password
from app.models.hr import (
    HRAttendanceAgent,
    HRAttendanceAgentCommand,
    HRAttendanceAgentEnrollment,
    HRAttendanceAgentRelease,
    HRAttendanceDevice,
    HRAttendanceDeviceEmployeeMapping,
    HRAttendancePunch,
    HRAttendanceUnmappedPunch,
    HREmployee,
)
from app.models.organisation import Organisation
from app.models.user import User
from app.services.hr_attendance_agent_auth import hash_agent_token

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "attendance-agent"))

from onec_attendance_agent.config import AgentConfig, DeviceConfig  # noqa: E402
from onec_attendance_agent.sync.worker import AttendanceSyncWorker  # noqa: E402


async def _setup_agent(db, slug: str = "agent-cpk"):
    org = Organisation(nom=f"Tenant {slug}", slug=slug, is_active=True)
    db.add(org)
    await db.flush()
    agent = HRAttendanceAgent(
        tenant_id=org.id,
        agent_id=f"{slug}-agent-01",
        name="Agent CPK",
        site="CPK",
        token_hash=hash_agent_token("secret-token"),
    )
    employee = HREmployee(tenant_id=org.id, matricule="EMP001", nom="KIDIKALA", prenom="Christian", statut="actif")
    db.add_all([agent, employee])
    await db.flush()
    device = HRAttendanceDevice(tenant_id=org.id, agent_id=agent.id, code="CPK-HIK-001", name="Entrée", provider="hikvision")
    db.add(device)
    await db.flush()
    mapping = HRAttendanceDeviceEmployeeMapping(tenant_id=org.id, device_id=device.id, employee_id=employee.id, external_employee_id="0042")
    db.add(mapping)
    await db.commit()
    return org, agent, device, employee


async def _setup_admin(db, org: Organisation, email_suffix: str = "admin") -> User:
    user = User(
        organisation_id=org.id,
        email=f"{email_suffix}-{org.slug}@example.test",
        hashed_password=hash_password("Admin_Test_2026!"),
        nom="Admin",
        prenom="RH",
        role="admin",
        active=True,
        is_email_verified=True,
        is_first_login=False,
        must_change_password=False,
    )
    db.add(user)
    await db.commit()
    return user


def _headers(agent_id: str, token: str = "secret-token") -> dict[str, str]:
    return {"X-ONEC-Agent-ID": agent_id, "Authorization": f"Bearer {token}"}


def _user_headers(user: User, org: Organisation) -> dict[str, str]:
    token, _ = create_access_token(subject=str(user.id), role=user.role, org_id=org.id, org_slug=org.slug)
    return {"Authorization": f"Bearer {token}", "X-Tenant-ID": str(org.id)}


def _payload(agent_id: str, external_employee_id: str = "0042", reference: str = "evt-1") -> dict:
    return {
        "agent_id": agent_id,
        "device_id": "CPK-HIK-001",
        "events": [
            {
                "external_employee_id": external_employee_id,
                "punched_at": datetime(2026, 8, 16, 7, 48, tzinfo=timezone.utc).isoformat(),
                "event_type": "IN",
                "source": "DEVICE",
                "external_reference": reference,
            }
        ],
    }


@pytest.mark.asyncio
async def test_agent_event_creates_attendance_punch(app_client: AsyncClient, db_session):
    org, agent, _, _ = await _setup_agent(db_session, "agent-create")
    response = await app_client.post("/api/v1/hr/attendance-agent/punches", json=_payload(agent.agent_id), headers=_headers(agent.agent_id))
    assert response.status_code == 200, response.text
    assert response.json()["accepted"] == 1
    count = await db_session.scalar(
        select(func.count()).select_from(HRAttendancePunch).where(
            HRAttendancePunch.tenant_id == org.id,
            HRAttendancePunch.external_reference == "evt-1",
        )
    )
    assert count == 1


@pytest.mark.asyncio
async def test_agent_duplicate_is_idempotent(app_client: AsyncClient, db_session):
    org, agent, _, _ = await _setup_agent(db_session, "agent-duplicate")
    first = await app_client.post("/api/v1/hr/attendance-agent/punches", json=_payload(agent.agent_id), headers=_headers(agent.agent_id))
    second = await app_client.post("/api/v1/hr/attendance-agent/punches", json=_payload(agent.agent_id), headers=_headers(agent.agent_id))
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["duplicates"] == 1
    count = await db_session.scalar(
        select(func.count()).select_from(HRAttendancePunch).where(
            HRAttendancePunch.tenant_id == org.id,
            HRAttendancePunch.external_reference == "evt-1",
        )
    )
    assert count == 1


@pytest.mark.asyncio
async def test_agent_bad_auth_is_rejected(app_client: AsyncClient, db_session):
    _, agent, _, _ = await _setup_agent(db_session, "agent-bad-auth")
    response = await app_client.post("/api/v1/hr/attendance-agent/punches", json=_payload(agent.agent_id), headers=_headers(agent.agent_id, "bad"))
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_agent_id_mismatch_is_forbidden(app_client: AsyncClient, db_session):
    _, agent, _, _ = await _setup_agent(db_session, "agent-mismatch")
    payload = _payload("another-agent")
    response = await app_client.post("/api/v1/hr/attendance-agent/punches", json=payload, headers=_headers(agent.agent_id))
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_unmapped_employee_is_preserved(app_client: AsyncClient, db_session):
    _, agent, _, _ = await _setup_agent(db_session, "agent-unmapped")
    response = await app_client.post(
        "/api/v1/hr/attendance-agent/punches",
        json=_payload(agent.agent_id, external_employee_id="UNKNOWN", reference="evt-unmapped"),
        headers=_headers(agent.agent_id),
    )
    assert response.status_code == 200, response.text
    assert response.json()["unmapped"] == 1
    assert response.json()["results"][0]["status"] == "UNMAPPED_EMPLOYEE"


@pytest.mark.asyncio
async def test_unknown_device_is_registered_by_agent(app_client: AsyncClient, db_session):
    _, agent, _, _ = await _setup_agent(db_session, "agent-new-device")
    payload = _payload(agent.agent_id)
    payload["device_id"] = "CPK-HIK-NEW"
    response = await app_client.post("/api/v1/hr/attendance-agent/punches", json=payload, headers=_headers(agent.agent_id))
    assert response.status_code == 200
    assert response.json()["unmapped"] == 1


@pytest.mark.asyncio
async def test_agent_heartbeat_updates_status(app_client: AsyncClient, db_session):
    _, agent, _, _ = await _setup_agent(db_session, "agent-heartbeat")
    agent_pk = agent.id
    tenant_id = agent.tenant_id
    payload = {
        "agent_version": "0.1.0",
        "hostname": "cpk-mini-pc",
        "site": "CPK",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pending_queue_count": 3,
        "error_count": 1,
        "devices": [
            {
                "device_id": "CPK-HIK-001",
                "provider": "mock",
                "status": "ONLINE",
                "pending_count": 3,
                "error_count": 1,
                "last_sync_at": datetime(2026, 8, 16, 7, 50, tzinfo=timezone.utc).isoformat(),
            }
        ],
    }
    response = await app_client.post("/api/v1/hr/attendance-agent/heartbeat", json=payload, headers=_headers(agent.agent_id))
    assert response.status_code == 204, response.text
    db_session.expire_all()
    refreshed_agent = await db_session.scalar(select(HRAttendanceAgent).where(HRAttendanceAgent.id == agent_pk))
    refreshed_device = await db_session.scalar(select(HRAttendanceDevice).where(HRAttendanceDevice.tenant_id == tenant_id, HRAttendanceDevice.code == "CPK-HIK-001"))
    assert refreshed_agent is not None
    assert refreshed_agent.last_seen_at is not None
    assert refreshed_agent.pending_count == 3
    assert refreshed_device is not None
    assert refreshed_device.status == "ONLINE"
    assert refreshed_device.pending_count == 3


@pytest.mark.asyncio
async def test_ingested_punch_is_readable_from_hr_api(app_client: AsyncClient, db_session):
    org, agent, _, employee = await _setup_agent(db_session, "agent-rh-read")
    admin = await _setup_admin(db_session, org)
    ingest = await app_client.post("/api/v1/hr/attendance-agent/punches", json=_payload(agent.agent_id, reference="evt-rh-read"), headers=_headers(agent.agent_id))
    assert ingest.status_code == 200, ingest.text

    response = await app_client.get(
        "/api/v1/hr/attendance-punches",
        params={"date_from": "2026-08-16", "date_to": "2026-08-16", "search": "EMP001"},
        headers=_user_headers(admin, org),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["employee_id"] == employee.id
    assert body["items"][0]["external_reference"] == "evt-rh-read"


@pytest.mark.asyncio
async def test_unmapped_punch_can_be_reprocessed_after_mapping(app_client: AsyncClient, db_session):
    org, agent, device, employee = await _setup_agent(db_session, "agent-reprocess")
    admin = await _setup_admin(db_session, org)
    payload = _payload(agent.agent_id, external_employee_id="UNKNOWN-001", reference="evt-reprocess")
    response = await app_client.post("/api/v1/hr/attendance-agent/punches", json=payload, headers=_headers(agent.agent_id))
    assert response.status_code == 200, response.text
    assert response.json()["unmapped"] == 1
    unmapped = await db_session.scalar(select(HRAttendanceUnmappedPunch).where(HRAttendanceUnmappedPunch.external_reference == "evt-reprocess"))
    assert unmapped is not None
    assert unmapped.status == "UNMAPPED_EMPLOYEE"

    db_session.add(
        HRAttendanceDeviceEmployeeMapping(
            tenant_id=org.id,
            device_id=device.id,
            employee_id=employee.id,
            external_employee_id="UNKNOWN-001",
        )
    )
    await db_session.commit()
    reprocess = await app_client.post(f"/api/v1/hr/attendance-unmapped-punches/{unmapped.id}/reprocess", headers=_user_headers(admin, org))
    assert reprocess.status_code == 200, reprocess.text
    assert reprocess.json()["status"] == "CREATED"
    count = await db_session.scalar(select(func.count()).select_from(HRAttendancePunch).where(HRAttendancePunch.external_reference == "evt-reprocess"))
    assert count == 1


@pytest.mark.asyncio
async def test_agent_tenant_isolation(app_client: AsyncClient, db_session):
    org_a, agent_a, _, _ = await _setup_agent(db_session, "agent-tenant-a")
    org_b, _, _, _ = await _setup_agent(db_session, "agent-tenant-b")
    admin_a = await _setup_admin(db_session, org_a, "admin-a")

    response = await app_client.post("/api/v1/hr/attendance-agent/punches", json=_payload(agent_a.agent_id, reference="evt-tenant-a"), headers=_headers(agent_a.agent_id))
    assert response.status_code == 200, response.text
    tenant_b_count = await db_session.scalar(select(func.count()).select_from(HRAttendancePunch).where(HRAttendancePunch.tenant_id == org_b.id))
    assert tenant_b_count == 0

    forbidden = await app_client.get(
        "/api/v1/hr/attendance-devices/status",
        headers={**_user_headers(admin_a, org_a), "X-Tenant-ID": str(org_b.id)},
    )
    assert forbidden.status_code == 403


@pytest.mark.asyncio
async def test_agent_enrollment_returns_tenant_scoped_config_and_machine_token(app_client: AsyncClient, db_session):
    org = Organisation(nom="Tenant Enrollment", slug="agent-enrollment", is_active=True)
    db_session.add(org)
    await db_session.flush()
    admin = await _setup_admin(db_session, org, "admin-enroll")
    payload = {
        "agent_name": "Agent LAN CPK",
        "site": "CPK",
        "api_base_url": "http://192.168.1.20:8000",
        "device_code": "CPK-HIK-150",
        "device_name": "Entrée principale",
        "provider": "hikvision",
        "local_host": "192.168.1.150",
        "local_port": 80,
        "expires_in_minutes": 30,
    }

    created = await app_client.post("/api/v1/hr/attendance-agent/enrollments", json=payload, headers=_user_headers(admin, org))
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["agent_id"].startswith("att-")
    assert body["api_base_url"] == "http://192.168.1.20:8000/api/v1"
    assert body["enrollment_url"] == "http://192.168.1.20:8000/api/v1/hr/attendance-agent/enroll"
    assert "enrollment_token" in body

    enrolled = await app_client.post(
        "/api/v1/hr/attendance-agent/enroll",
        json={"enrollment_token": body["enrollment_token"], "hostname": "agent-pc-lan", "agent_version": "0.2.0"},
    )
    assert enrolled.status_code == 200, enrolled.text
    enrolled_body = enrolled.json()
    assert enrolled_body["agent_id"] == body["agent_id"]
    assert enrolled_body["api_base_url"] == "http://192.168.1.20:8000/api/v1"
    assert enrolled_body["devices"] == [{
        "id": "CPK-HIK-150",
        "provider": "hikvision",
        "host": "192.168.1.150",
        "port": 80,
        "configured_model": "DS-K1A8603MF-B",
    }]
    assert enrolled_body["agent_token"]

    agent = await db_session.scalar(select(HRAttendanceAgent).where(HRAttendanceAgent.agent_id == body["agent_id"]))
    enrollment = await db_session.scalar(select(HRAttendanceAgentEnrollment).where(HRAttendanceAgentEnrollment.agent_id == agent.id))
    device = await db_session.scalar(select(HRAttendanceDevice).where(HRAttendanceDevice.tenant_id == org.id, HRAttendanceDevice.code == "CPK-HIK-150"))
    assert agent is not None
    assert agent.tenant_id == org.id
    assert agent.is_active is True
    assert enrollment is not None
    assert enrollment.status == "USED"
    assert device is not None
    assert device.local_host == "192.168.1.150"


@pytest.mark.asyncio
async def test_agent_enrollment_token_is_single_use(app_client: AsyncClient, db_session):
    org = Organisation(nom="Tenant Enrollment Single Use", slug="agent-enrollment-single", is_active=True)
    db_session.add(org)
    await db_session.flush()
    admin = await _setup_admin(db_session, org, "admin-enroll-single")
    created = await app_client.post(
        "/api/v1/hr/attendance-agent/enrollments",
        json={
            "agent_name": "Agent LAN CPK",
            "api_base_url": "https://onec.example.com",
            "device_code": "CPK-HIK-151",
            "device_name": "Entrée secondaire",
            "local_host": "192.168.1.151",
        },
        headers=_user_headers(admin, org),
    )
    assert created.status_code == 201, created.text
    token = created.json()["enrollment_token"]
    first = await app_client.post("/api/v1/hr/attendance-agent/enroll", json={"enrollment_token": token})
    second = await app_client.post("/api/v1/hr/attendance-agent/enroll", json={"enrollment_token": token})
    assert first.status_code == 200, first.text
    assert second.status_code == 401


@pytest.mark.asyncio
async def test_agent_enrollment_rejects_localhost_api_base_url(app_client: AsyncClient, db_session):
    org = Organisation(nom="Tenant Enrollment Reject", slug="agent-enrollment-reject", is_active=True)
    db_session.add(org)
    await db_session.flush()
    admin = await _setup_admin(db_session, org, "admin-enroll-reject")
    response = await app_client.post(
        "/api/v1/hr/attendance-agent/enrollments",
        json={
            "agent_name": "Agent LAN CPK",
            "api_base_url": "http://localhost:8000",
            "device_code": "CPK-HIK-152",
            "device_name": "Entrée rejet",
            "local_host": "192.168.1.152",
        },
        headers=_user_headers(admin, org),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_agent_enrollment_expired_token_is_rejected(app_client: AsyncClient, db_session):
    org, agent, device, _ = await _setup_agent(db_session, "agent-expired-enrollment")
    token = "expired-token-" + "x" * 20
    enrollment = HRAttendanceAgentEnrollment(
        tenant_id=org.id,
        agent_id=agent.id,
        token_hash=hash_agent_token(token),
        status="PENDING",
        api_base_url="https://onec.example.com/api/v1",
        device_code=device.code,
        device_name=device.name,
        provider=device.provider,
        local_host="192.168.1.150",
        local_port=80,
        expires_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db_session.add(enrollment)
    await db_session.commit()
    response = await app_client.post("/api/v1/hr/attendance-agent/enroll", json={"enrollment_token": token})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_agent_revoke_refuses_heartbeat_and_sync(app_client: AsyncClient, db_session):
    org, agent, _, _ = await _setup_agent(db_session, "agent-revoke")
    admin = await _setup_admin(db_session, org, "admin-revoke")
    revoke = await app_client.post(f"/api/v1/hr/attendance-agents/{agent.id}/revoke", headers=_user_headers(admin, org))
    assert revoke.status_code == 200, revoke.text
    heartbeat = await app_client.post(
        "/api/v1/hr/attendance-agent/heartbeat",
        json={"timestamp": datetime.now(timezone.utc).isoformat(), "devices": []},
        headers=_headers(agent.agent_id),
    )
    sync = await app_client.post("/api/v1/hr/attendance-agent/punches", json=_payload(agent.agent_id), headers=_headers(agent.agent_id))
    assert heartbeat.status_code in {401, 403}
    assert sync.status_code in {401, 403}


@pytest.mark.asyncio
async def test_agent_reinstall_invalidates_old_credential_and_new_enrollment_works(app_client: AsyncClient, db_session):
    org, agent, device, _ = await _setup_agent(db_session, "agent-reinstall")
    device_pk = device.id
    agent_pk = agent.id
    admin = await _setup_admin(db_session, org, "admin-reinstall")
    response = await app_client.post(
        f"/api/v1/hr/attendance-agents/{agent_pk}/reinstall",
        json={"agent_id": agent_pk, "platform": "windows", "architecture": "x64", "api_base_url": "https://onec.example.com"},
        headers=_user_headers(admin, org),
    )
    assert response.status_code == 200, response.text
    old_heartbeat = await app_client.post(
        "/api/v1/hr/attendance-agent/heartbeat",
        json={"timestamp": datetime.now(timezone.utc).isoformat(), "devices": []},
        headers=_headers(agent.agent_id),
    )
    assert old_heartbeat.status_code == 401
    token = response.json()["enrollment"]["enrollment_token"]
    enrolled = await app_client.post("/api/v1/hr/attendance-agent/enroll", json={"enrollment_token": token})
    assert enrolled.status_code == 200, enrolled.text
    db_session.expire_all()
    refreshed_device = await db_session.scalar(select(HRAttendanceDevice).where(HRAttendanceDevice.id == device_pk))
    assert refreshed_device is not None
    assert refreshed_device.agent_id == agent_pk


async def _create_release_artifact(tmp_path: Path, db_session, version: str, platform_name: str, active: bool = True):
    artifact_dir = tmp_path / "releases"
    artifact_dir.mkdir(exist_ok=True)
    artifact = artifact_dir / f"onec-attendance-agent-{version}-{platform_name}-x64.bin"
    artifact.write_bytes(f"agent-{version}-{platform_name}".encode("utf-8"))
    db_session.add(
        HRAttendanceAgentRelease(
            version=version,
            platform=platform_name,
            architecture="x64",
            filename=artifact.name,
            storage_key=str(artifact),
            sha256=__import__("hashlib").sha256(artifact.read_bytes()).hexdigest(),
            file_size=artifact.stat().st_size,
            is_active=active,
        )
    )
    await db_session.commit()
    return artifact


@pytest.mark.asyncio
async def test_releases_list_only_existing_active_windows_and_linux(app_client: AsyncClient, db_session, tmp_path):
    org = Organisation(nom="Tenant Releases", slug="agent-releases", is_active=True)
    db_session.add(org)
    await db_session.flush()
    admin = await _setup_admin(db_session, org, "admin-releases")
    await _create_release_artifact(tmp_path, db_session, "0.2.0", "windows", True)
    await _create_release_artifact(tmp_path, db_session, "0.2.0", "linux", True)
    await _create_release_artifact(tmp_path, db_session, "0.1.2", "windows", False)

    response = await app_client.get("/api/v1/hr/attendance-agent/releases", headers=_user_headers(admin, org))
    assert response.status_code == 200, response.text
    body = response.json()
    assert {item["platform"] for item in body} == {"windows", "linux"}
    assert all(item["sha256"] and len(item["sha256"]) == 64 for item in body)


@pytest.mark.asyncio
async def test_inactive_release_download_is_refused(app_client: AsyncClient, db_session, tmp_path):
    org = Organisation(nom="Tenant Releases Inactive", slug="agent-releases-inactive", is_active=True)
    db_session.add(org)
    await db_session.flush()
    admin = await _setup_admin(db_session, org, "admin-releases-inactive")
    await _create_release_artifact(tmp_path, db_session, "0.1.1", "windows", False)
    release = await db_session.scalar(
        select(HRAttendanceAgentRelease).where(
            HRAttendanceAgentRelease.platform == "windows",
            HRAttendanceAgentRelease.version == "0.1.2",
        )
    )
    response = await app_client.get(f"/api/v1/hr/attendance-agent/releases/{release.id}/download", headers=_user_headers(admin, org))
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_agent_package_contains_enrollment_without_localhost(app_client: AsyncClient, db_session, tmp_path):
    org, agent, device, _ = await _setup_agent(db_session, "agent-package")
    admin = await _setup_admin(db_session, org, "admin-package")
    device.local_host = "192.168.1.150"
    device.local_port = 80
    await _create_release_artifact(tmp_path, db_session, "0.2.1", "windows", True)
    release = await db_session.scalar(select(HRAttendanceAgentRelease).where(HRAttendanceAgentRelease.platform == "windows"))
    await db_session.commit()
    response = await app_client.post(
        f"/api/v1/hr/attendance-agent/releases/{release.id}/package",
        json={"agent_id": agent.id, "platform": "windows", "architecture": "x64", "api_base_url": "http://192.168.1.20:8000"},
        headers=_user_headers(admin, org),
    )
    assert response.status_code == 200, response.text
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert {"onec-attendance-agent.exe", "enrollment.json", "README.txt"}.issubset(set(archive.namelist()))
    enrollment = json.loads(archive.read("enrollment.json"))
    raw = archive.read("enrollment.json").decode("utf-8")
    assert enrollment["enrollment_url"].startswith("http://192.168.1.20:8000/api/v1/")
    assert "localhost" not in raw
    assert "127.0.0.1" not in raw
    assert "backend:8000" not in raw
    assert "agent_token" not in raw


@pytest.mark.asyncio
async def test_test_device_command_claim_and_success_result(app_client: AsyncClient, db_session):
    org, agent, device, _ = await _setup_agent(db_session, "agent-command")
    device_pk = device.id
    admin = await _setup_admin(db_session, org, "admin-command")
    command = await app_client.post(f"/api/v1/hr/attendance-devices/{device_pk}/test-command", headers=_user_headers(admin, org))
    assert command.status_code == 200, command.text
    claimed = await app_client.get("/api/v1/hr/attendance-agent/commands", headers=_headers(agent.agent_id))
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()[0]["command_type"] == "TEST_DEVICE"
    command_id = claimed.json()[0]["id"]
    result = {
        "tcp_reachable": True,
        "tcp_latency_ms": 24,
        "http_ok": True,
        "status_code": 401,
        "status": "AUTH_REQUIRED",
    }
    completed = await app_client.post(
        f"/api/v1/hr/attendance-agent/commands/{command_id}/result",
        json={"status": "SUCCESS", "result": result},
        headers=_headers(agent.agent_id),
    )
    assert completed.status_code == 200, completed.text
    db_session.expire_all()
    refreshed = await db_session.scalar(select(HRAttendanceDevice).where(HRAttendanceDevice.id == device_pk))
    assert refreshed.last_test_latency_ms == 24
    assert refreshed.status in {"AUTH_REQUIRED", "DEVICE_ONLINE"}


@pytest.mark.asyncio
async def test_command_expires_when_agent_offline(app_client: AsyncClient, db_session):
    org, agent, device, _ = await _setup_agent(db_session, "agent-command-expire")
    command = HRAttendanceAgentCommand(
        tenant_id=org.id,
        agent_id=agent.id,
        device_id=device.id,
        command_type="TEST_DEVICE",
        payload_json={"device_id": device.code},
        status="PENDING",
        expires_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db_session.add(command)
    await db_session.commit()
    command_pk = command.id
    response = await app_client.get("/api/v1/hr/attendance-agent/commands", headers=_headers(agent.agent_id))
    assert response.status_code == 200
    db_session.expire_all()
    refreshed = await db_session.scalar(select(HRAttendanceAgentCommand).where(HRAttendanceAgentCommand.id == command_pk))
    assert refreshed.status == "EXPIRED"


@pytest.mark.asyncio
async def test_tenant_a_cannot_command_tenant_b_agent(app_client: AsyncClient, db_session):
    org_a, _, _, _ = await _setup_agent(db_session, "agent-command-tenant-a")
    org_b, _, device_b, _ = await _setup_agent(db_session, "agent-command-tenant-b")
    admin_a = await _setup_admin(db_session, org_a, "admin-command-tenant-a")
    response = await app_client.post(
        f"/api/v1/hr/attendance-devices/{device_b.id}/test-command",
        headers={**_user_headers(admin_a, org_a), "X-Tenant-ID": str(org_a.id)},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_mock_provider_worker_to_backend_to_hr_journal(app_client: AsyncClient, db_session, tmp_path):
    org, agent, _, employee = await _setup_agent(db_session, "agent-e2e-mock")
    admin = await _setup_admin(db_session, org)
    config = AgentConfig(
        agent_id=agent.agent_id,
        name="agent-e2e-mock",
        site="CPK",
        sync_interval_seconds=1,
        timezone="UTC",
        api_base_url="http://testserver/api/v1",
        token="secret-token",
        timeout_seconds=1,
        sqlite_path=str(tmp_path / "queue.sqlite3"),
        devices=[DeviceConfig(id="CPK-HIK-001", provider="mock", host="mock", port=0)],
    )
    worker = AttendanceSyncWorker(config)
    worker.collect_once()
    assert worker.queue.pending_count() > 0

    loop = asyncio.get_running_loop()

    class LocalApiClient:
        def send_events(self, rows):
            payload = {
                "agent_id": agent.agent_id,
                "device_id": "CPK-HIK-001",
                "events": [
                    {
                        **row["payload"],
                        "external_employee_id": "0042",
                        "external_reference": "evt-worker-e2e",
                        "punched_at": datetime(2026, 8, 16, 7, 48, tzinfo=timezone.utc).isoformat(),
                    }
                    for row in rows[:1]
                ],
            }
            future = asyncio.run_coroutine_threadsafe(
                app_client.post("/api/v1/hr/attendance-agent/punches", json=payload, headers=_headers(agent.agent_id)),
                loop,
            )
            response = future.result(timeout=10)
            assert response.status_code == 200, response.text
            return response.json()

    worker.client = LocalApiClient()
    await asyncio.to_thread(worker.sync_once)

    count = await db_session.scalar(select(func.count()).select_from(HRAttendancePunch).where(HRAttendancePunch.external_reference == "evt-worker-e2e"))
    assert count == 1
    journal = await app_client.get(
        "/api/v1/hr/attendance-punches",
        params={"date_from": "2026-08-16", "date_to": "2026-08-16", "search": "EMP001"},
        headers=_user_headers(admin, org),
    )
    assert journal.status_code == 200, journal.text
    assert journal.json()["items"][0]["employee_id"] == employee.id
