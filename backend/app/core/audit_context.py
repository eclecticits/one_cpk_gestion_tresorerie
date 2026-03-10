from __future__ import annotations

from contextvars import ContextVar
from typing import Optional
import uuid

_audit_user_id: ContextVar[Optional[uuid.UUID]] = ContextVar("audit_user_id", default=None)
_audit_org_id: ContextVar[Optional[int]] = ContextVar("audit_org_id", default=None)


def set_audit_user_id(user_id: uuid.UUID | None) -> None:
    _audit_user_id.set(user_id)


def get_audit_user_id() -> uuid.UUID | None:
    return _audit_user_id.get()


def set_audit_org_id(org_id: int | None) -> None:
    _audit_org_id.set(org_id)


def get_audit_org_id() -> int | None:
    return _audit_org_id.get()
