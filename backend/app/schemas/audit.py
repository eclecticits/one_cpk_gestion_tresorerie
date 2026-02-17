from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AuditLogOut(BaseModel):
    id: str
    user_id: str | None = None
    action: str
    entity_type: str | None = None
    entity_id: str | None = None
    old_value: dict | str | None = None
    new_value: dict | str | None = None
    ip_address: str | None = None
    created_at: datetime
