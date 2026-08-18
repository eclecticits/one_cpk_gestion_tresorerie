from __future__ import annotations

import secrets
import hashlib
import json
import zipfile
from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, get_db, has_permission
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
from app.core.config import settings
from app.models.user import User
from app.schemas.hr import (
    HRAttendanceAgentDeviceConfigOut,
    HRAttendanceAgentCommandCreate,
    HRAttendanceAgentCommandOut,
    HRAttendanceAgentCommandResultIn,
    HRAttendanceAgentEnrollIn,
    HRAttendanceAgentEnrollmentCreate,
    HRAttendanceAgentEnrollmentOut,
    HRAttendanceAgentEnrollOut,
    HRAttendanceAgentOut,
    HRAttendanceAgentPackageCreate,
    HRAttendanceAgentReinstallOut,
    HRAttendanceAgentReleaseCreate,
    HRAttendanceAgentReleaseOut,
    HRAttendanceAgentHeartbeatIn,
    HRAttendanceAgentPunchBatchIn,
    HRAttendanceAgentPunchBatchOut,
    HRAttendanceAgentEventResult,
    HRAttendanceDeviceOut,
    HRAttendanceDeviceStatusOut,
    HRAttendanceMappingCreate,
    HRAttendanceMappingOut,
    HRAttendanceUnmappedPunchOut,
)
from app.services.hr_attendance_agent_auth import AttendanceAgentIdentity, authenticate_attendance_agent, hash_agent_token

router = APIRouter()

BLOCKED_REMOTE_HOSTS = {"localhost", "127.0.0.1", "backend", "backend:8000"}
RELEASE_PLATFORMS = {"windows", "linux"}
COMMAND_PENDING = {"PENDING", "RUNNING"}
SENSITIVE_RESULT_KEYS = {"password", "passwd", "secret", "token", "agent_token", "authorization", "credential", "credentials"}


def _normalize_agent_api_base_url(raw_url: str) -> str:
    value = raw_url.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=422, detail="URL ONEC Smart invalide")
    hostname = (parsed.hostname or "").lower()
    if hostname in BLOCKED_REMOTE_HOSTS or hostname.startswith("127."):
        raise HTTPException(
            status_code=422,
            detail="Utiliser l'adresse IP LAN ou le domaine public de ONEC Smart, pas localhost, 127.0.0.1 ni un nom Docker",
        )
    if value.endswith("/api/v1"):
        return value
    if value.endswith("/api"):
        return f"{value}/v1"
    return f"{value}/api/v1"


def _validate_device_host(host: str) -> str:
    value = host.strip()
    parsed = urlparse(f"//{value}")
    hostname = (parsed.hostname or value).lower()
    if hostname in BLOCKED_REMOTE_HOSTS or hostname.startswith("127."):
        raise HTTPException(status_code=422, detail="Adresse locale de pointeuse invalide pour un agent distant")
    return value


def _mask_serial_number(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:5]}****{value[-2:]}"


def _sanitize_command_result(value):
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in SENSITIVE_RESULT_KEYS or any(marker in lowered for marker in ("password", "secret", "token")):
                cleaned[key] = "[REDACTED]"
            elif lowered in {"serial_number", "serialnumber", "serial_no", "serialno"}:
                cleaned[key] = _mask_serial_number(str(item) if item is not None else None)
            else:
                cleaned[key] = _sanitize_command_result(item)
        return cleaned
    if isinstance(value, list):
        return [_sanitize_command_result(item) for item in value]
    return value


def _release_root() -> Path:
    base = Path(settings.upload_dir or "uploads").resolve()
    return base / "attendance-agent" / "releases"


def _release_path(storage_key: str) -> Path:
    candidate = Path(storage_key)
    if candidate.is_absolute():
        return candidate
    return (_release_root() / storage_key).resolve()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _platform_binary_name(release: HRAttendanceAgentRelease) -> str:
    if release.platform == "windows":
        return "onec-attendance-agent.exe"
    return "onec-attendance-agent"


async def _agent_identity(
    db: AsyncSession = Depends(get_db),
    x_onec_agent_id: str | None = Header(default=None, alias="X-ONEC-Agent-ID"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> AttendanceAgentIdentity:
    return await authenticate_attendance_agent(db=db, x_onec_agent_id=x_onec_agent_id, authorization=authorization)


async def _get_or_create_device(
    db: AsyncSession,
    identity: AttendanceAgentIdentity,
    device_code: str,
    *,
    provider: str = "hikvision",
    site: str | None = None,
) -> HRAttendanceDevice:
    res = await db.execute(
        select(HRAttendanceDevice).where(
            HRAttendanceDevice.tenant_id == identity.tenant_id,
            HRAttendanceDevice.code == device_code,
        )
    )
    device = res.scalar_one_or_none()
    if device is not None:
        if device.agent_id is None:
            device.agent_id = identity.agent.id
        return device
    device = HRAttendanceDevice(
        tenant_id=identity.tenant_id,
        agent_id=identity.agent.id,
        code=device_code,
        name=device_code,
        provider=provider,
        site=site or identity.agent.site,
        status="UNKNOWN",
    )
    db.add(device)
    await db.flush()
    return device


async def _create_enrollment_for_agent_device(
    *,
    db: AsyncSession,
    user: User | None,
    tenant_id: int,
    agent: HRAttendanceAgent,
    device: HRAttendanceDevice,
    api_base_url: str,
    expires_in_minutes: int,
) -> tuple[HRAttendanceAgentEnrollment, str]:
    enrollment_token = secrets.token_urlsafe(32)
    enrollment = HRAttendanceAgentEnrollment(
        tenant_id=tenant_id,
        agent_id=agent.id,
        token_hash=hash_agent_token(enrollment_token),
        status="PENDING",
        api_base_url=api_base_url,
        device_code=device.code,
        device_name=device.name,
        provider=device.provider,
        site=device.site or agent.site,
        local_host=device.local_host or "",
        local_port=device.local_port or 80,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes),
        created_by=user.id if user else None,
    )
    db.add(enrollment)
    await db.flush()
    return enrollment, enrollment_token


@router.post(
    "/attendance-agent/enrollments",
    response_model=HRAttendanceAgentEnrollmentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_permission("rh.attendance.correct"))],
)
async def create_attendance_agent_enrollment(
    payload: HRAttendanceAgentEnrollmentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> HRAttendanceAgentEnrollmentOut:
    api_base_url = _normalize_agent_api_base_url(payload.api_base_url)
    local_host = _validate_device_host(payload.local_host)
    now = datetime.now(timezone.utc)
    if payload.agent_id:
        agent = await db.scalar(select(HRAttendanceAgent).where(HRAttendanceAgent.tenant_id == tenant_id, HRAttendanceAgent.id == payload.agent_id))
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent introuvable")
        agent.name = payload.agent_name
        agent.site = payload.site
        agent.token_hash = hash_agent_token(secrets.token_urlsafe(32))
        agent.is_active = False
        agent.revoked_at = None
        agent.revoked_by = None
    else:
        agent = HRAttendanceAgent(
            tenant_id=tenant_id,
            agent_id=f"att-{secrets.token_hex(8)}",
            name=payload.agent_name,
            site=payload.site,
            token_hash=hash_agent_token(secrets.token_urlsafe(32)),
            is_active=False,
        )
        db.add(agent)
        await db.flush()

    existing_device = await db.scalar(
        select(HRAttendanceDevice).where(
            HRAttendanceDevice.tenant_id == tenant_id,
            HRAttendanceDevice.code == payload.device_code,
        )
    )
    if existing_device is None:
        device = HRAttendanceDevice(
            tenant_id=tenant_id,
            agent_id=agent.id,
            code=payload.device_code,
            name=payload.device_name,
            provider=payload.provider,
            site=payload.site,
            local_host=local_host,
            local_port=payload.local_port,
            model=payload.model or "DS-K1A8603MF-B",
            status="UNKNOWN",
        )
        db.add(device)
    else:
        existing_device.agent_id = agent.id
        existing_device.name = payload.device_name
        existing_device.provider = payload.provider
        existing_device.site = payload.site
        existing_device.local_host = local_host
        existing_device.local_port = payload.local_port
        existing_device.model = payload.model or existing_device.model or "DS-K1A8603MF-B"
        device = existing_device

    enrollment, enrollment_token = await _create_enrollment_for_agent_device(
        db=db,
        user=user,
        tenant_id=tenant_id,
        agent=agent,
        device=device,
        api_base_url=api_base_url,
        expires_in_minutes=payload.expires_in_minutes,
    )
    enrollment.expires_at = now + timedelta(minutes=payload.expires_in_minutes)
    await db.commit()
    await db.refresh(enrollment)
    return HRAttendanceAgentEnrollmentOut(
        id=enrollment.id,
        agent_id=agent.agent_id,
        agent_name=agent.name,
        enrollment_token=enrollment_token,
        enrollment_url=f"{api_base_url}/hr/attendance-agent/enroll",
        api_base_url=api_base_url,
        device_code=enrollment.device_code,
        device_name=enrollment.device_name,
        provider=enrollment.provider,
        local_host=enrollment.local_host,
        local_port=enrollment.local_port,
        expires_at=enrollment.expires_at,
    )


@router.post("/attendance-agent/enroll", response_model=HRAttendanceAgentEnrollOut)
async def enroll_attendance_agent(
    payload: HRAttendanceAgentEnrollIn,
    db: AsyncSession = Depends(get_db),
) -> HRAttendanceAgentEnrollOut:
    token_hash = hash_agent_token(payload.enrollment_token)
    now = datetime.now(timezone.utc)
    enrollment = await db.scalar(
        select(HRAttendanceAgentEnrollment).where(
            HRAttendanceAgentEnrollment.token_hash == token_hash,
            HRAttendanceAgentEnrollment.status == "PENDING",
            HRAttendanceAgentEnrollment.used_at.is_(None),
            HRAttendanceAgentEnrollment.expires_at > now,
        )
    )
    if enrollment is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Enrollment invalide ou expiré")
    agent = await db.scalar(select(HRAttendanceAgent).where(HRAttendanceAgent.id == enrollment.agent_id))
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent introuvable")
    if agent.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent révoqué")

    agent_token = secrets.token_urlsafe(32)
    agent.token_hash = hash_agent_token(agent_token)
    agent.is_active = True
    agent.hostname = payload.hostname
    agent.version = payload.agent_version
    agent.last_seen_at = now
    enrollment.status = "USED"
    enrollment.used_at = now

    device = await db.scalar(
        select(HRAttendanceDevice).where(
            HRAttendanceDevice.tenant_id == enrollment.tenant_id,
            HRAttendanceDevice.code == enrollment.device_code,
        )
    )
    if device is not None:
        device.agent_id = agent.id
        device.local_host = enrollment.local_host
        device.local_port = enrollment.local_port
    await db.commit()
    return HRAttendanceAgentEnrollOut(
        agent_id=agent.agent_id,
        agent_token=agent_token,
        api_base_url=enrollment.api_base_url,
        site=agent.site,
        devices=[
            HRAttendanceAgentDeviceConfigOut(
                id=enrollment.device_code,
                provider=enrollment.provider,
                host=enrollment.local_host,
                port=enrollment.local_port,
                configured_model=device.model,
            )
        ],
    )


@router.get("/attendance-agent/releases", response_model=list[HRAttendanceAgentReleaseOut], dependencies=[Depends(has_permission("rh.attendance.view"))])
async def list_attendance_agent_releases(
    platform: str | None = Query(default=None),
    architecture: str | None = Query(default=None),
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
) -> list[HRAttendanceAgentRelease]:
    stmt = select(HRAttendanceAgentRelease)
    if active_only:
        stmt = stmt.where(HRAttendanceAgentRelease.is_active.is_(True))
    if platform:
        stmt = stmt.where(HRAttendanceAgentRelease.platform == platform)
    if architecture:
        stmt = stmt.where(HRAttendanceAgentRelease.architecture == architecture)
    rows = (await db.execute(stmt.order_by(HRAttendanceAgentRelease.published_at.desc()))).scalars().all()
    existing = []
    for release in rows:
        if _release_path(release.storage_key).is_file():
            existing.append(release)
    return existing


@router.post("/attendance-agent/releases", response_model=HRAttendanceAgentReleaseOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(has_permission("rh.attendance.correct"))])
async def create_attendance_agent_release(payload: HRAttendanceAgentReleaseCreate, db: AsyncSession = Depends(get_db)) -> HRAttendanceAgentRelease:
    if payload.platform not in RELEASE_PLATFORMS:
        raise HTTPException(status_code=422, detail="Plateforme agent non supportée")
    path = _release_path(payload.storage_key)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Artefact release introuvable")
    release = HRAttendanceAgentRelease(
        version=payload.version,
        platform=payload.platform,
        architecture=payload.architecture,
        filename=payload.filename,
        storage_key=payload.storage_key,
        sha256=_sha256_file(path),
        file_size=path.stat().st_size,
        is_active=payload.is_active,
        minimum_backend_version=payload.minimum_backend_version,
    )
    db.add(release)
    await db.commit()
    await db.refresh(release)
    return release


@router.get("/attendance-agent/releases/{release_id}/download", dependencies=[Depends(has_permission("rh.attendance.view"))])
async def download_attendance_agent_release(release_id: int, db: AsyncSession = Depends(get_db)) -> FileResponse:
    release = await db.scalar(select(HRAttendanceAgentRelease).where(HRAttendanceAgentRelease.id == release_id))
    if release is None or not release.is_active:
        raise HTTPException(status_code=404, detail="Release agent indisponible")
    path = _release_path(release.storage_key)
    if not path.is_file() or _sha256_file(path) != release.sha256:
        raise HTTPException(status_code=409, detail="Artefact release absent ou checksum invalide")
    return FileResponse(path, filename=release.filename, media_type="application/octet-stream")


@router.post("/attendance-agent/releases/{release_id}/package", dependencies=[Depends(has_permission("rh.attendance.correct"))])
async def download_attendance_agent_tenant_package(
    release_id: int,
    payload: HRAttendanceAgentPackageCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> StreamingResponse:
    release = await db.scalar(
        select(HRAttendanceAgentRelease).where(
            HRAttendanceAgentRelease.id == release_id,
            HRAttendanceAgentRelease.is_active.is_(True),
            HRAttendanceAgentRelease.platform == payload.platform,
            HRAttendanceAgentRelease.architecture == payload.architecture,
        )
    )
    if release is None:
        raise HTTPException(status_code=404, detail="Release agent indisponible")
    release_path = _release_path(release.storage_key)
    if not release_path.is_file() or _sha256_file(release_path) != release.sha256:
        raise HTTPException(status_code=409, detail="Artefact release absent ou checksum invalide")
    agent = await db.scalar(select(HRAttendanceAgent).where(HRAttendanceAgent.tenant_id == tenant_id, HRAttendanceAgent.id == payload.agent_id))
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent introuvable")
    device = await db.scalar(select(HRAttendanceDevice).where(HRAttendanceDevice.tenant_id == tenant_id, HRAttendanceDevice.agent_id == agent.id))
    if device is None:
        raise HTTPException(status_code=404, detail="Pointeuse associée introuvable")
    if not device.local_host:
        raise HTTPException(status_code=409, detail="Adresse locale de pointeuse manquante")
    api_base_url = _normalize_agent_api_base_url(payload.api_base_url)
    enrollment, token = await _create_enrollment_for_agent_device(
        db=db,
        user=user,
        tenant_id=tenant_id,
        agent=agent,
        device=device,
        api_base_url=api_base_url,
        expires_in_minutes=payload.expires_in_minutes,
    )
    await db.commit()
    enrollment_doc = {
        "agent_id": agent.agent_id,
        "enrollment_url": f"{api_base_url}/hr/attendance-agent/enroll",
        "enrollment_token": token,
        "api_base_url": api_base_url,
        "release": {
            "version": release.version,
            "platform": release.platform,
            "architecture": release.architecture,
            "filename": release.filename,
            "sha256": release.sha256,
            "file_size": release.file_size,
        },
        "device": {
            "id": device.code,
            "provider": device.provider,
            "host": device.local_host,
            "port": device.local_port or 80,
        },
        "expires_at": enrollment.expires_at.isoformat(),
    }
    raw = json.dumps(enrollment_doc, ensure_ascii=False)
    blocked_markers = ("localhost", "127.0.0.1", "backend:8000")
    if any(marker in raw for marker in blocked_markers):
        raise HTTPException(status_code=409, detail="Package enrollment contient une URL locale interdite")
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(release_path, _platform_binary_name(release))
        archive.writestr("enrollment.json", raw)
        archive.writestr(
            "README.txt",
            "ONEC Attendance Agent\n\n"
            "1. Installer le binaire fourni.\n"
            "2. Lancer la commande enroll avec enrollment.json.\n"
            "3. Ne partager aucun token. Le token d'enrollment est temporaire et usage unique.\n",
        )
    buffer.seek(0)
    safe_agent = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in agent.agent_id)
    filename = f"ONEC-Agent-{safe_agent}-{release.platform}-{release.architecture}.zip"
    return StreamingResponse(buffer, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/attendance-agent/heartbeat", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def attendance_agent_heartbeat(
    payload: HRAttendanceAgentHeartbeatIn,
    db: AsyncSession = Depends(get_db),
    identity: AttendanceAgentIdentity = Depends(_agent_identity),
) -> Response:
    now = datetime.now(timezone.utc)
    agent = identity.agent
    agent.version = payload.agent_version
    agent.hostname = payload.hostname
    agent.site = payload.site or agent.site
    agent.last_seen_at = now
    agent.last_sync_at = payload.last_sync_at or agent.last_sync_at
    agent.pending_count = payload.pending_queue_count
    agent.error_count = payload.error_count
    agent.last_error = None

    for item in payload.devices:
        device = await _get_or_create_device(db, identity, item.device_id, provider=item.provider or "hikvision", site=payload.site)
        device.status = item.status.upper()
        device.last_seen_at = now
        device.last_sync_at = item.last_sync_at or device.last_sync_at
        device.pending_count = item.pending_count
        device.error_count = item.error_count
        device.last_error = item.last_error
        device.model = item.model or device.model
        device.firmware = item.firmware or device.firmware
        device.serial_number = _mask_serial_number(item.serial_number) or device.serial_number
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/attendance-agent/punches", response_model=HRAttendanceAgentPunchBatchOut)
async def ingest_attendance_agent_punches(
    payload: HRAttendanceAgentPunchBatchIn,
    db: AsyncSession = Depends(get_db),
    identity: AttendanceAgentIdentity = Depends(_agent_identity),
) -> HRAttendanceAgentPunchBatchOut:
    if payload.agent_id != identity.agent.agent_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent incohérent")
    device = await _get_or_create_device(db, identity, payload.device_id)
    results: list[HRAttendanceAgentEventResult] = []
    accepted = duplicates = unmapped = rejected = 0

    for event in payload.events:
        event_type = (event.event_type or "IN").upper()
        if event_type not in {"IN", "OUT"}:
            rejected += 1
            results.append(HRAttendanceAgentEventResult(external_reference=event.external_reference, status="REJECTED", detail="event_type invalide"))
            continue
        mapping_res = await db.execute(
            select(HRAttendanceDeviceEmployeeMapping).where(
                HRAttendanceDeviceEmployeeMapping.tenant_id == identity.tenant_id,
                HRAttendanceDeviceEmployeeMapping.device_id == device.id,
                HRAttendanceDeviceEmployeeMapping.external_employee_id == event.external_employee_id,
            )
        )
        mapping = mapping_res.scalar_one_or_none()
        if mapping is None:
            existing_unmapped = await db.scalar(
                select(HRAttendanceUnmappedPunch.id).where(
                    HRAttendanceUnmappedPunch.tenant_id == identity.tenant_id,
                    HRAttendanceUnmappedPunch.device_id == device.id,
                    HRAttendanceUnmappedPunch.external_reference == event.external_reference,
                )
            )
            if existing_unmapped:
                duplicates += 1
                results.append(HRAttendanceAgentEventResult(external_reference=event.external_reference, status="DUPLICATE_UNMAPPED", unmapped_id=existing_unmapped))
                continue
            row = HRAttendanceUnmappedPunch(
                tenant_id=identity.tenant_id,
                device_id=device.id,
                external_employee_id=event.external_employee_id,
                punched_at=event.punched_at,
                event_type=event_type,
                source=event.source.upper(),
                external_reference=event.external_reference,
                raw_event_type=event.raw_event_type,
                payload_json=event.payload,
            )
            db.add(row)
            await db.flush()
            unmapped += 1
            results.append(HRAttendanceAgentEventResult(external_reference=event.external_reference, status="UNMAPPED_EMPLOYEE", unmapped_id=row.id))
            continue

        existing_punch = await db.scalar(
            select(HRAttendancePunch.id).where(
                HRAttendancePunch.tenant_id == identity.tenant_id,
                HRAttendancePunch.device_id == device.code,
                HRAttendancePunch.external_reference == event.external_reference,
            )
        )
        if existing_punch:
            duplicates += 1
            results.append(HRAttendanceAgentEventResult(external_reference=event.external_reference, status="DUPLICATE", punch_id=existing_punch))
            continue
        punch = HRAttendancePunch(
            tenant_id=identity.tenant_id,
            employee_id=mapping.employee_id,
            punched_at=event.punched_at,
            event_type=event_type,
            source=event.source.upper(),
            device_id=device.code,
            external_reference=event.external_reference,
            notes=f"Agent {identity.agent.agent_id}",
        )
        db.add(punch)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            duplicates += 1
            results.append(HRAttendanceAgentEventResult(external_reference=event.external_reference, status="DUPLICATE"))
            continue
        accepted += 1
        results.append(HRAttendanceAgentEventResult(external_reference=event.external_reference, status="CREATED", punch_id=punch.id))

    device.last_sync_at = datetime.now(timezone.utc)
    identity.agent.last_sync_at = device.last_sync_at
    device.today_punch_count = int(await db.scalar(select(func.count()).select_from(HRAttendancePunch).where(
        HRAttendancePunch.tenant_id == identity.tenant_id,
        HRAttendancePunch.device_id == device.code,
        HRAttendancePunch.punched_at >= datetime.now(timezone.utc).date(),
    )) or 0)
    await db.commit()
    return HRAttendanceAgentPunchBatchOut(accepted=accepted, duplicates=duplicates, unmapped=unmapped, rejected=rejected, results=results)


@router.get("/attendance-agent/commands", response_model=list[HRAttendanceAgentCommandOut])
async def claim_attendance_agent_commands(
    db: AsyncSession = Depends(get_db),
    identity: AttendanceAgentIdentity = Depends(_agent_identity),
) -> list[HRAttendanceAgentCommand]:
    now = datetime.now(timezone.utc)
    expired_rows = (
        await db.execute(
            select(HRAttendanceAgentCommand).where(
                HRAttendanceAgentCommand.agent_id == identity.agent.id,
                HRAttendanceAgentCommand.status.in_(list(COMMAND_PENDING)),
                HRAttendanceAgentCommand.expires_at.is_not(None),
                HRAttendanceAgentCommand.expires_at <= now,
            )
        )
    ).scalars().all()
    for command in expired_rows:
        command.status = "EXPIRED"
        command.completed_at = now
        command.error = "Commande expirée avant exécution"
    rows = (
        await db.execute(
            select(HRAttendanceAgentCommand)
            .where(
                HRAttendanceAgentCommand.agent_id == identity.agent.id,
                HRAttendanceAgentCommand.tenant_id == identity.tenant_id,
                HRAttendanceAgentCommand.status == "PENDING",
            )
            .order_by(HRAttendanceAgentCommand.created_at)
            .limit(10)
        )
    ).scalars().all()
    for command in rows:
        command.status = "RUNNING"
        command.claimed_at = now
    await db.commit()
    return list(rows)


@router.post("/attendance-agent/commands/{command_id}/result", response_model=HRAttendanceAgentCommandOut)
async def complete_attendance_agent_command(
    command_id: int,
    payload: HRAttendanceAgentCommandResultIn,
    db: AsyncSession = Depends(get_db),
    identity: AttendanceAgentIdentity = Depends(_agent_identity),
) -> HRAttendanceAgentCommand:
    command = await db.scalar(
        select(HRAttendanceAgentCommand).where(
            HRAttendanceAgentCommand.id == command_id,
            HRAttendanceAgentCommand.agent_id == identity.agent.id,
            HRAttendanceAgentCommand.tenant_id == identity.tenant_id,
        )
    )
    if command is None:
        raise HTTPException(status_code=404, detail="Commande introuvable")
    if command.status not in {"PENDING", "RUNNING"}:
        raise HTTPException(status_code=409, detail="Commande déjà terminée")
    now = datetime.now(timezone.utc)
    sanitized_result = _sanitize_command_result(payload.result)
    command.status = payload.status
    command.completed_at = now
    command.result_json = sanitized_result
    command.error = payload.error
    if command.command_type in {"TEST_DEVICE", "PROBE_DEVICE"} and command.device_id is not None:
        device = await db.scalar(
            select(HRAttendanceDevice).where(
                HRAttendanceDevice.tenant_id == identity.tenant_id,
                HRAttendanceDevice.id == command.device_id,
            )
        )
        if device is not None:
            device.last_test_at = now
            device.last_test_result_json = sanitized_result
            latency = sanitized_result.get("tcp_latency_ms") if sanitized_result else None
            device.last_test_latency_ms = int(latency) if isinstance(latency, int | float) else None
            if sanitized_result:
                if sanitized_result.get("detected_model"):
                    device.model = str(sanitized_result["detected_model"])
                if sanitized_result.get("firmware_version"):
                    device.firmware = str(sanitized_result["firmware_version"])
            if payload.status == "SUCCESS" and sanitized_result:
                result_status = sanitized_result.get("status")
                if result_status in {
                    "AGENT_OFFLINE",
                    "DEVICE_OFFLINE",
                    "DEVICE_REACHABLE",
                    "AUTH_REQUIRED",
                    "AUTH_FAILED",
                    "DEVICE_ONLINE",
                    "ISAPI_AVAILABLE",
                    "ISAPI_UNAVAILABLE",
                    "TEST_FAILED",
                    "UNKNOWN",
                }:
                    device.status = str(result_status)
                elif sanitized_result.get("tcp_reachable"):
                    device.status = "DEVICE_REACHABLE"
                else:
                    device.status = "DEVICE_OFFLINE"
            else:
                device.status = "TEST_FAILED"
                device.last_error = payload.error
    await db.commit()
    await db.refresh(command)
    return command


async def _create_device_command(
    device_pk: int,
    command_type: str,
    expires_in_seconds: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> HRAttendanceAgentCommand:
    device = await db.scalar(select(HRAttendanceDevice).where(HRAttendanceDevice.tenant_id == tenant_id, HRAttendanceDevice.id == device_pk))
    if device is None:
        raise HTTPException(status_code=404, detail="Pointeuse introuvable")
    if device.agent_id is None:
        raise HTTPException(status_code=409, detail="Aucun agent associé à cette pointeuse")
    agent = await db.scalar(select(HRAttendanceAgent).where(HRAttendanceAgent.tenant_id == tenant_id, HRAttendanceAgent.id == device.agent_id))
    if agent is None or agent.revoked_at is not None:
        raise HTTPException(status_code=409, detail="Agent indisponible")
    # Le cloud ne contacte jamais l'IP privée : il dépose seulement une commande pour l'agent local.
    command = HRAttendanceAgentCommand(
        tenant_id=tenant_id,
        agent_id=agent.id,
        device_id=device.id,
        command_type=command_type,
        payload_json={
            "device_id": device.code,
            "host": device.local_host,
            "port": device.local_port or 80,
            "provider": device.provider,
            "configured_model": device.model or "DS-K1A8603MF-B",
        },
        status="PENDING",
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds),
        created_by=user.id,
    )
    db.add(command)
    await db.commit()
    await db.refresh(command)
    return command


@router.post("/attendance-devices/{device_pk}/test-command", response_model=HRAttendanceAgentCommandOut, dependencies=[Depends(has_permission("rh.attendance.correct"))])
async def create_test_device_command(
    device_pk: int,
    payload: HRAttendanceAgentCommandCreate | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> HRAttendanceAgentCommand:
    expires = payload.expires_in_seconds if payload else 120
    return await _create_device_command(device_pk, "TEST_DEVICE", expires, db, user, tenant_id)


@router.post("/attendance-devices/{device_pk}/probe-command", response_model=HRAttendanceAgentCommandOut, dependencies=[Depends(has_permission("rh.attendance.correct"))])
async def create_probe_device_command(
    device_pk: int,
    payload: HRAttendanceAgentCommandCreate | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> HRAttendanceAgentCommand:
    expires = payload.expires_in_seconds if payload else 180
    return await _create_device_command(device_pk, "PROBE_DEVICE", expires, db, user, tenant_id)


@router.post("/attendance-agents/{agent_pk}/revoke", response_model=HRAttendanceAgentOut, dependencies=[Depends(has_permission("rh.attendance.correct"))])
async def revoke_attendance_agent(
    agent_pk: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> HRAttendanceAgent:
    agent = await db.scalar(select(HRAttendanceAgent).where(HRAttendanceAgent.tenant_id == tenant_id, HRAttendanceAgent.id == agent_pk))
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent introuvable")
    agent.is_active = False
    agent.token_hash = hash_agent_token(secrets.token_urlsafe(32))
    agent.revoked_at = datetime.now(timezone.utc)
    agent.revoked_by = user.id
    await db.commit()
    await db.refresh(agent)
    return agent


@router.post("/attendance-agents/{agent_pk}/reinstall", response_model=HRAttendanceAgentReinstallOut, dependencies=[Depends(has_permission("rh.attendance.correct"))])
async def reinstall_attendance_agent(
    agent_pk: int,
    payload: HRAttendanceAgentPackageCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> HRAttendanceAgentReinstallOut:
    if payload.agent_id != agent_pk:
        raise HTTPException(status_code=422, detail="Agent incohérent")
    agent = await db.scalar(select(HRAttendanceAgent).where(HRAttendanceAgent.tenant_id == tenant_id, HRAttendanceAgent.id == agent_pk))
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent introuvable")
    device = await db.scalar(select(HRAttendanceDevice).where(HRAttendanceDevice.tenant_id == tenant_id, HRAttendanceDevice.agent_id == agent.id))
    if device is None:
        raise HTTPException(status_code=404, detail="Pointeuse associée introuvable")
    api_base_url = _normalize_agent_api_base_url(payload.api_base_url)
    agent.is_active = False
    agent.token_hash = hash_agent_token(secrets.token_urlsafe(32))
    agent.revoked_at = None
    agent.revoked_by = None
    enrollment, token = await _create_enrollment_for_agent_device(
        db=db,
        user=user,
        tenant_id=tenant_id,
        agent=agent,
        device=device,
        api_base_url=api_base_url,
        expires_in_minutes=payload.expires_in_minutes,
    )
    await db.commit()
    await db.refresh(agent)
    return HRAttendanceAgentReinstallOut(
        agent=HRAttendanceAgentOut.model_validate(agent),
        enrollment=HRAttendanceAgentEnrollmentOut(
            id=enrollment.id,
            agent_id=agent.agent_id,
            agent_name=agent.name,
            enrollment_token=token,
            enrollment_url=f"{api_base_url}/hr/attendance-agent/enroll",
            api_base_url=api_base_url,
            device_code=enrollment.device_code,
            device_name=enrollment.device_name,
            provider=enrollment.provider,
            local_host=enrollment.local_host,
            local_port=enrollment.local_port,
            expires_at=enrollment.expires_at,
        ),
    )


@router.get("/attendance-devices/status", response_model=list[HRAttendanceDeviceStatusOut], dependencies=[Depends(has_permission("rh.attendance.view"))])
async def attendance_devices_status(
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[HRAttendanceDeviceStatusOut]:
    rows = (await db.execute(select(HRAttendanceDevice).where(HRAttendanceDevice.tenant_id == tenant_id).order_by(HRAttendanceDevice.name))).scalars().all()
    now = datetime.now(timezone.utc)
    out = []
    for device in rows:
        agent_online = bool(device.last_seen_at and now - device.last_seen_at < timedelta(minutes=10))
        out.append(HRAttendanceDeviceStatusOut(
            id=device.id,
            agent_id=device.agent_id,
            device_id=device.code,
            name=device.name,
            provider=device.provider,
            site=device.site,
            device_online=device.status in {"DEVICE_ONLINE", "DEVICE_REACHABLE", "AUTH_REQUIRED", "ISAPI_AVAILABLE", "ISAPI_UNAVAILABLE"},
            agent_online=agent_online,
            status=device.status,
            last_seen_at=device.last_seen_at,
            last_sync_at=device.last_sync_at,
            last_test_at=device.last_test_at,
            last_test_latency_ms=device.last_test_latency_ms,
            last_test_result=device.last_test_result_json,
            pending_count=device.pending_count,
            error_count=device.error_count,
            today_punch_count=device.today_punch_count,
            last_error=device.last_error,
        ))
    return out


@router.get("/attendance-devices", response_model=list[HRAttendanceDeviceOut], dependencies=[Depends(has_permission("rh.attendance.view"))])
async def list_attendance_devices(db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)) -> list[HRAttendanceDevice]:
    return list((await db.execute(select(HRAttendanceDevice).where(HRAttendanceDevice.tenant_id == tenant_id).order_by(HRAttendanceDevice.name))).scalars().all())


@router.post("/attendance-device-mappings", response_model=HRAttendanceMappingOut, dependencies=[Depends(has_permission("rh.attendance.correct"))])
async def create_device_mapping(payload: HRAttendanceMappingCreate, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)) -> HRAttendanceDeviceEmployeeMapping:
    employee = await db.scalar(select(HREmployee).where(HREmployee.tenant_id == tenant_id, HREmployee.id == payload.employee_id))
    device = await db.scalar(select(HRAttendanceDevice).where(HRAttendanceDevice.tenant_id == tenant_id, HRAttendanceDevice.id == payload.device_id))
    if employee is None or device is None:
        raise HTTPException(status_code=404, detail="Employé ou pointeuse introuvable")
    row = HRAttendanceDeviceEmployeeMapping(tenant_id=tenant_id, device_id=payload.device_id, employee_id=payload.employee_id, external_employee_id=payload.external_employee_id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.get("/attendance-unmapped-punches", response_model=list[HRAttendanceUnmappedPunchOut], dependencies=[Depends(has_permission("rh.attendance.view"))])
async def list_unmapped_punches(db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)) -> list[HRAttendanceUnmappedPunch]:
    return list((await db.execute(select(HRAttendanceUnmappedPunch).where(HRAttendanceUnmappedPunch.tenant_id == tenant_id, HRAttendanceUnmappedPunch.status == "UNMAPPED_EMPLOYEE").order_by(HRAttendanceUnmappedPunch.punched_at.desc()).limit(200))).scalars().all())


@router.post("/attendance-unmapped-punches/{unmapped_id}/reprocess", response_model=HRAttendanceAgentEventResult, dependencies=[Depends(has_permission("rh.attendance.correct"))])
async def reprocess_unmapped_punch(unmapped_id: int, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)) -> HRAttendanceAgentEventResult:
    unmapped = await db.scalar(
        select(HRAttendanceUnmappedPunch).where(
            HRAttendanceUnmappedPunch.tenant_id == tenant_id,
            HRAttendanceUnmappedPunch.id == unmapped_id,
        )
    )
    if unmapped is None:
        raise HTTPException(status_code=404, detail="Pointage non associé introuvable")
    mapping = await db.scalar(
        select(HRAttendanceDeviceEmployeeMapping).where(
            HRAttendanceDeviceEmployeeMapping.tenant_id == tenant_id,
            HRAttendanceDeviceEmployeeMapping.device_id == unmapped.device_id,
            HRAttendanceDeviceEmployeeMapping.external_employee_id == unmapped.external_employee_id,
        )
    )
    if mapping is None:
        raise HTTPException(status_code=409, detail="Aucun mapping employé n'existe encore pour ce pointage")
    device = await db.scalar(select(HRAttendanceDevice).where(HRAttendanceDevice.tenant_id == tenant_id, HRAttendanceDevice.id == unmapped.device_id))
    if device is None:
        raise HTTPException(status_code=404, detail="Pointeuse introuvable")
    existing_punch = await db.scalar(
        select(HRAttendancePunch.id).where(
            HRAttendancePunch.tenant_id == tenant_id,
            HRAttendancePunch.device_id == device.code,
            HRAttendancePunch.external_reference == unmapped.external_reference,
        )
    )
    if existing_punch:
        unmapped.status = "RESOLVED"
        unmapped.resolved_at = datetime.now(timezone.utc)
        await db.commit()
        return HRAttendanceAgentEventResult(external_reference=unmapped.external_reference, status="DUPLICATE", punch_id=existing_punch, unmapped_id=unmapped.id)
    punch = HRAttendancePunch(
        tenant_id=tenant_id,
        employee_id=mapping.employee_id,
        punched_at=unmapped.punched_at,
        event_type=(unmapped.event_type or "IN").upper(),
        source=unmapped.source,
        device_id=device.code,
        external_reference=unmapped.external_reference,
        notes="Retraitement pointage non associé",
    )
    db.add(punch)
    await db.flush()
    unmapped.status = "RESOLVED"
    unmapped.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    return HRAttendanceAgentEventResult(external_reference=unmapped.external_reference, status="CREATED", punch_id=punch.id, unmapped_id=unmapped.id)
