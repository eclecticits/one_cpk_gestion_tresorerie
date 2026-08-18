from __future__ import annotations

from datetime import datetime
from typing import Protocol

from onec_attendance_agent.models.events import NormalizedPunch


class AttendanceDeviceProvider(Protocol):
    device_id: str

    def test_connection(self) -> bool:
        ...

    def probe_capabilities(self) -> dict:
        ...

    def fetch_events(self, since: datetime | None = None) -> list[NormalizedPunch]:
        ...

    def get_device_info(self) -> dict:
        ...
