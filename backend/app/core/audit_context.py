from __future__ import annotations

from contextvars import ContextVar
from typing import Optional
import uuid

_audit_user_id: ContextVar[Optional[uuid.UUID]] = ContextVar("audit_user_id", default=None)


def set_audit_user_id(user_id: uuid.UUID | None) -> None:
    _audit_user_id.set(user_id)


def get_audit_user_id() -> uuid.UUID | None:
    return _audit_user_id.get()
