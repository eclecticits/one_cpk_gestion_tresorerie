from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from fastapi import Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr import HRAttendanceAgent


def hash_agent_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AttendanceAgentIdentity:
    agent: HRAttendanceAgent
    tenant_id: int


async def authenticate_attendance_agent(
    *,
    db: AsyncSession,
    x_onec_agent_id: str | None = Header(default=None, alias="X-ONEC-Agent-ID"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> AttendanceAgentIdentity:
    if not x_onec_agent_id or not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Agent non authentifié")
    raw_token = authorization.split(" ", 1)[1].strip()
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Agent non authentifié")
    res = await db.execute(
        select(HRAttendanceAgent).where(
            HRAttendanceAgent.agent_id == x_onec_agent_id,
            HRAttendanceAgent.is_active.is_(True),
        )
    )
    agent = res.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Agent inconnu")
    if agent.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent révoqué")
    if not hmac.compare_digest(agent.token_hash, hash_agent_token(raw_token)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token agent invalide")
    return AttendanceAgentIdentity(agent=agent, tenant_id=agent.tenant_id)
