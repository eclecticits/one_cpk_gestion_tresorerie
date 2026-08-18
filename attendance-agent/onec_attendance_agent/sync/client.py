from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from onec_attendance_agent.config import AgentConfig


class OnecSmartClient:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    def _request(self, path: str, payload: dict[str, Any] | None = None, method: str = "POST") -> dict[str, Any] | list[dict] | None:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{self.config.api_base_url}{path}",
            data=body,
            headers={
                "Authorization": f"Bearer {self.config.token}",
                "X-ONEC-Agent-ID": self.config.agent_id,
                "Content-Type": "application/json",
            },
            method=method,
        )
        with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else None

    def heartbeat(self, devices: list[dict], pending_count: int, error_count: int = 0) -> None:
        self._request(
            "/hr/attendance-agent/heartbeat",
            {
                "agent_version": "0.1.0",
                "hostname": self.config.name,
                "site": self.config.site,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "pending_queue_count": pending_count,
                "error_count": error_count,
                "devices": devices,
            },
        )

    def send_events(self, rows: list[dict]) -> dict[str, Any]:
        grouped: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            grouped[row["device_id"]].append(row["payload"])
        last_response: dict[str, Any] = {"accepted": 0, "duplicates": 0, "unmapped": 0, "rejected": 0, "results": []}
        for device_id, events in grouped.items():
            payload = {"agent_id": self.config.agent_id, "device_id": device_id, "events": events}
            response = self._request("/hr/attendance-agent/punches", payload) or {}
            last_response["accepted"] += int(response.get("accepted") or 0)
            last_response["duplicates"] += int(response.get("duplicates") or 0)
            last_response["unmapped"] += int(response.get("unmapped") or 0)
            last_response["rejected"] += int(response.get("rejected") or 0)
            last_response["results"].extend(response.get("results") or [])
        return last_response

    def claim_commands(self) -> list[dict]:
        response = self._request("/hr/attendance-agent/commands", None, method="GET")
        return response if isinstance(response, list) else []

    def send_command_result(self, command_id: int, status: str, result: dict | None = None, error: str | None = None) -> None:
        self._request(
            f"/hr/attendance-agent/commands/{command_id}/result",
            {"status": status, "result": result, "error": error},
        )


def is_network_error(exc: Exception) -> bool:
    return isinstance(exc, (urllib.error.URLError, TimeoutError, OSError))
