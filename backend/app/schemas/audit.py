from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AuditLogOut(BaseModel):
    id: int
    user_id: str | None = None
    action: str
    target_table: str | None = None
    target_id: str | None = None
    old_value: dict | None = None
    new_value: dict | None = None
    ip_address: str | None = None
    created_at: datetime
