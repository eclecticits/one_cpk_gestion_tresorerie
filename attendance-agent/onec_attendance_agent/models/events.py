from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class NormalizedPunch:
    device_id: str
    external_employee_id: str
    punched_at: datetime
    event_type: str | None
    external_reference: str
    source: str = "DEVICE"
    raw_event_type: str | None = None
    payload: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["punched_at"] = self.punched_at.isoformat()
        return data
