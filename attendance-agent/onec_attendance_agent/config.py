from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from onec_attendance_agent.credentials import load_credentials_ref


BLOCKED_API_HOSTS = {"localhost", "127.0.0.1", "backend", "backend:8000"}
API_BASE_URL_ENV = "ATTENDANCE_AGENT_API_BASE_URL"


def _env(value: str | None) -> str | None:
    if not isinstance(value, str):
        return value
    if value.startswith("${") and value.endswith("}"):
        return os.getenv(value[2:-1])
    return value


@dataclass(frozen=True)
class DeviceConfig:
    id: str
    provider: str
    host: str
    port: int = 80
    configured_model: str | None = None
    protocol: str | None = None
    credential_ref: str | None = None
    username: str | None = None
    password: str | None = None


@dataclass(frozen=True)
class AgentConfig:
    agent_id: str
    name: str
    site: str
    sync_interval_seconds: int
    timezone: str
    api_base_url: str
    token: str
    timeout_seconds: int
    sqlite_path: str
    devices: list[DeviceConfig]


def normalize_api_base_url(raw_url: str) -> str:
    value = raw_url.strip().rstrip("/")
    if not value:
        raise RuntimeError(f"{API_BASE_URL_ENV} is required")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(f"{API_BASE_URL_ENV} must be an absolute http(s) URL")
    hostname = (parsed.hostname or "").lower()
    if hostname in BLOCKED_API_HOSTS or hostname.startswith("127."):
        raise RuntimeError(
            f"{API_BASE_URL_ENV} must target the ONEC Smart LAN IP or production domain, not {parsed.netloc}"
        )
    if value.endswith("/api/v1"):
        return value
    if value.endswith("/api"):
        return f"{value}/v1"
    return f"{value}/api/v1"


def load_config(path: str | Path) -> AgentConfig:
    raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    onec = raw["onec_smart"]
    token = os.getenv(onec.get("token_env", "ONEC_AGENT_TOKEN")) or _env(onec.get("token"))
    if not token:
        raise RuntimeError("ONEC agent token missing")
    raw_api_base_url = os.getenv(API_BASE_URL_ENV) or _env(onec.get("api_base_url")) or _env(onec.get("api_url"))
    if not raw_api_base_url:
        raise RuntimeError(f"{API_BASE_URL_ENV} missing")
    devices = []
    for item in raw.get("devices", []):
        credential_ref = _env(item.get("credential_ref"))
        username = _env(item.get("username"))
        password = _env(item.get("password"))
        if credential_ref:
            credentials = load_credentials_ref(credential_ref)
            username = username or credentials.username
            password = password or credentials.password
        devices.append(DeviceConfig(
            id=item["id"],
            provider=item["provider"],
            host=item["host"],
            port=int(item.get("port") or 80),
            configured_model=item.get("configured_model") or item.get("model"),
            protocol=_env(item.get("protocol")),
            credential_ref=credential_ref,
            username=username,
            password=password,
        ))
    agent = raw["agent"]
    storage = raw.get("storage", {})
    return AgentConfig(
        agent_id=agent["id"],
        name=agent.get("name") or agent["id"],
        site=agent.get("site") or "",
        sync_interval_seconds=int(agent.get("sync_interval_seconds") or 10),
        timezone=agent.get("timezone") or "UTC",
        api_base_url=normalize_api_base_url(raw_api_base_url),
        token=token,
        timeout_seconds=int(onec.get("timeout_seconds") or 15),
        sqlite_path=storage.get("sqlite_path") or "./onec_attendance_agent.sqlite3",
        devices=devices,
    )
