from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

_tenant_id: ContextVar[Optional[int]] = ContextVar("tenant_id", default=None)


def set_current_tenant_id(tenant_id: int | None) -> None:
    _tenant_id.set(tenant_id)


def get_current_tenant_id() -> int | None:
    return _tenant_id.get()
