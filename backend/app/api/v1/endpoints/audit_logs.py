from __future__ import annotations

from datetime import datetime, timezone
import csv
import io
import json
import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, distinct, or_
from sqlalchemy.ext.asyncio import AsyncSession
from openpyxl import Workbook

from app.api.deps import get_current_user, has_permission
from app.db.session import get_db
from app.utils.excel_io import save_workbook
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.audit import AuditLogOut

router = APIRouter()


def _parse_datetime(value: str | None, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if end_of_day and len(value) <= 10:
        dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    return dt


def _apply_filters(
    stmt,
    *,
    user: User,
    action: str | None,
    user_id: str | None,
    target_table: str | None,
    target_id: str | None,
    date_debut: str | None,
    date_fin: str | None,
):
    if (user.role or "").lower() != "super_admin" and user.organisation_id is not None:
        stmt = stmt.where(
            or_(
                AuditLog.organisation_id == user.organisation_id,
                AuditLog.organisation_id.is_(None),
            )
        )
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if user_id:
        try:
            user_uid = uuid.UUID(user_id)
        except ValueError:
            return stmt.where(False)
        stmt = stmt.where(AuditLog.user_id == user_uid)
    if target_table:
        stmt = stmt.where(AuditLog.entity_type.ilike(f"%{target_table.strip()}%"))
    if target_id:
        stmt = stmt.where(AuditLog.entity_id.ilike(f"%{target_id.strip()}%"))

    start_dt = _parse_datetime(date_debut)
    end_dt = _parse_datetime(date_fin, end_of_day=True)
    if start_dt:
        stmt = stmt.where(AuditLog.created_at >= start_dt)
    if end_dt:
        stmt = stmt.where(AuditLog.created_at <= end_dt)
    return stmt


@router.get("", response_model=list[AuditLogOut], dependencies=[Depends(has_permission("audit_logs"))])
async def list_audit_logs(
    action: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    target_table: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
    date_debut: str | None = Query(default=None),
    date_fin: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AuditLogOut]:
    stmt = select(AuditLog)
    stmt = _apply_filters(
        stmt,
        user=user,
        action=action,
        user_id=user_id,
        target_table=target_table,
        target_id=target_id,
        date_debut=date_debut,
        date_fin=date_fin,
    )

    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    res = await db.execute(stmt)
    logs = res.scalars().all()
    return [
        AuditLogOut(
            id=str(log.id),
            user_id=str(log.user_id) if log.user_id else None,
            action=log.action,
            entity_type=log.entity_type,
            entity_id=log.entity_id,
            old_value=log.old_value,
            new_value=log.new_value,
            ip_address=log.ip_address,
            created_at=log.created_at,
        )
        for log in logs
    ]


@router.get("/actions", dependencies=[Depends(has_permission("audit_logs"))])
async def list_audit_actions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[str]:
    stmt = select(distinct(AuditLog.action))
    if (user.role or "").lower() != "super_admin" and user.organisation_id is not None:
        stmt = stmt.where(
            or_(
                AuditLog.organisation_id == user.organisation_id,
                AuditLog.organisation_id.is_(None),
            )
        )
    res = await db.execute(stmt.order_by(AuditLog.action.asc()))
    return [row[0] for row in res.all() if row[0]]


@router.get("/users", dependencies=[Depends(has_permission("audit_logs"))])
async def list_audit_users(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    stmt = select(User.id, User.email, User.nom, User.prenom).join(AuditLog, AuditLog.user_id == User.id)
    if (user.role or "").lower() != "super_admin":
        stmt = stmt.where(User.role != "super_admin")
        if user.organisation_id is not None:
            stmt = stmt.where(
                or_(
                    AuditLog.organisation_id == user.organisation_id,
                    AuditLog.organisation_id.is_(None),
                )
            )
    stmt = stmt.distinct().order_by(User.email.asc())
    res = await db.execute(stmt)
    users = []
    for uid, email, nom, prenom in res.all():
        label = " ".join(filter(None, [prenom, nom])) or email or str(uid)
        users.append({"id": str(uid), "label": label, "email": email})
    return users


@router.get("/export", dependencies=[Depends(has_permission("audit_logs"))])
async def export_audit_logs(
    action: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    target_table: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
    date_debut: str | None = Query(default=None),
    date_fin: str | None = Query(default=None),
    limit: int = Query(default=5000, ge=1, le=50000),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AuditLog)
    stmt = _apply_filters(
        stmt,
        user=user,
        action=action,
        user_id=user_id,
        target_table=target_table,
        target_id=target_id,
        date_debut=date_debut,
        date_fin=date_fin,
    )
    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)

    async def stream_csv():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "id",
                "created_at",
                "action",
                "target_table",
                "target_id",
                "user_id",
                "ip_address",
                "old_value",
                "new_value",
            ]
        )
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)

        result = await db.stream(stmt)
        async for log in result.scalars():
            writer.writerow(
                [
                    log.id,
                    log.created_at.isoformat() if log.created_at else "",
                    log.action,
                    log.entity_type or "",
                    log.entity_id or "",
                    str(log.user_id) if log.user_id else "",
                    log.ip_address or "",
                    json.dumps(log.old_value, ensure_ascii=False) if log.old_value is not None else "",
                    json.dumps(log.new_value, ensure_ascii=False) if log.new_value is not None else "",
                ]
            )
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    filename = f"audit_logs_{datetime.now(timezone.utc).date().isoformat()}.csv"
    return StreamingResponse(
        stream_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export-xlsx", dependencies=[Depends(has_permission("audit_logs"))])
async def export_audit_logs_xlsx(
    action: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    target_table: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
    date_debut: str | None = Query(default=None),
    date_fin: str | None = Query(default=None),
    limit: int = Query(default=5000, ge=1, le=50000),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(AuditLog)
    stmt = _apply_filters(
        stmt,
        user=user,
        action=action,
        user_id=user_id,
        target_table=target_table,
        target_id=target_id,
        date_debut=date_debut,
        date_fin=date_fin,
    )
    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    res = await db.execute(stmt)
    logs = res.scalars().all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Audit Logs"
    ws.append(
        [
            "id",
            "created_at",
            "action",
            "target_table",
            "target_id",
            "user_id",
            "ip_address",
            "old_value",
            "new_value",
        ]
    )
    for log in logs:
        ws.append(
            [
                log.id,
                log.created_at.isoformat() if log.created_at else "",
                log.action,
                log.entity_type or "",
                log.entity_id or "",
                str(log.user_id) if log.user_id else "",
                log.ip_address or "",
                json.dumps(log.old_value, ensure_ascii=False) if log.old_value is not None else "",
                json.dumps(log.new_value, ensure_ascii=False) if log.new_value is not None else "",
            ]
        )
    # Sérialisation en thread : elle domine le coût CPU de l'export et figerait
    # sinon la boucle d'événements pour toutes les requêtes en cours.
    output = await save_workbook(wb)

    filename = f"audit_logs_{datetime.now(timezone.utc).date().isoformat()}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
