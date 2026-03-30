from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel
from uuid import UUID


class AuditLogOut(BaseModel):
    id: int
    user_id: UUID | None = None
    action: str
    entity_type: str | None = None
    entity_id: str | None = None
    old_value: Any | None = None
    new_value: Any | None = None
    ip_address: str | None = None
    created_at: datetime
