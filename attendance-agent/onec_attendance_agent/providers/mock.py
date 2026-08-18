from __future__ import annotations

from datetime import datetime, timezone

from onec_attendance_agent.config import DeviceConfig
from onec_attendance_agent.models.events import NormalizedPunch


class MockAttendanceProvider:
    def __init__(self, config: DeviceConfig) -> None:
        self.config = config
        self.device_id = config.id

    def test_connection(self) -> bool:
        return self.probe_capabilities()

    def probe_capabilities(self) -> dict:
        return {
            "manufacturer": "Mock",
            "configured_model": self.config.configured_model,
            "detected_model": "Mock Device",
            "firmware_version": "0.1",
            "device_name": self.device_id,
            "host": self.config.host,
            "port": self.config.port,
            "tcp_reachable": True,
            "tcp_latency_ms": 1,
            "http_reachable": True,
            "http_status": 200,
            "https_reachable": False,
            "authentication_required": False,
            "authentication_ok": True,
            "isapi_supported": None,
            "access_control_supported": None,
            "attendance_supported": None,
            "event_query_supported": None,
            "status": "DEVICE_ONLINE",
        }

    def fetch_events(self, since: datetime | None = None) -> list[NormalizedPunch]:
        now = datetime.now(timezone.utc)
        base = now.replace(hour=7, minute=55, second=0, microsecond=0)
        events = [
            ("EMP001", base, "IN"),
            ("EMP002", base.replace(hour=8, minute=5), "IN"),
            ("EMP001", base.replace(hour=12, minute=1), "OUT"),
        ]
        return [
            NormalizedPunch(
                device_id=self.device_id,
                external_employee_id=emp,
                punched_at=ts,
                event_type=event_type,
                external_reference=f"mock-{self.device_id}-{emp}-{ts.isoformat()}-{event_type}",
                raw_event_type=event_type,
                payload={"provider": "mock"},
            )
            for emp, ts, event_type in events
            if since is None or ts > since
        ]

    def get_device_info(self) -> dict:
        return {"provider": "mock", "status": "ONLINE", "model": "Mock Device", "firmware": "0.1"}
