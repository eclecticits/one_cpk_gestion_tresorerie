from __future__ import annotations

import sys
import io
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "attendance-agent"))

from app.api.v1.endpoints.hr_attendance_agent import _sanitize_command_result
from onec_attendance_agent.config import AgentConfig, DeviceConfig, load_config, normalize_api_base_url
from onec_attendance_agent.credentials import DeviceCredentials, load_local_credentials, save_local_credentials
from onec_attendance_agent.providers.hikvision import HikvisionProvider, _mask_serial
from onec_attendance_agent.sync.worker import AttendanceSyncWorker


def _config(path: Path) -> AgentConfig:
    return AgentConfig(
        agent_id="agent-test",
        name="agent-test",
        site="CPK",
        sync_interval_seconds=1,
        timezone="UTC",
        api_base_url="https://onec.example/api/v1",
        token="token",
        timeout_seconds=1,
        sqlite_path=str(path),
        devices=[DeviceConfig(id="MOCK-1", provider="mock", host="mock", port=0)],
    )


def test_queue_persists_when_internet_unavailable(tmp_path):
    worker = AttendanceSyncWorker(_config(tmp_path / "queue.sqlite3"))
    worker.collect_once()
    assert worker.queue.pending_count() > 0

    class DownClient:
        def send_events(self, rows):
            raise OSError("network down")

    worker.client = DownClient()
    worker.sync_once()
    assert worker.queue.pending_count() > 0


def test_pending_events_are_marked_synced_when_network_returns(tmp_path):
    worker = AttendanceSyncWorker(_config(tmp_path / "queue.sqlite3"))
    worker.collect_once()
    assert worker.queue.pending_count() > 0

    class OkClient:
        def send_events(self, rows):
            return {"accepted": len(rows), "duplicates": 0, "unmapped": 0, "rejected": 0, "results": []}

    worker.client = OkClient()
    worker.sync_once()
    assert worker.queue.pending_count() == 0


def test_attendance_agent_api_base_url_is_normalized_for_lan_or_prod():
    assert normalize_api_base_url("http://192.168.1.20:8000") == "http://192.168.1.20:8000/api/v1"
    assert normalize_api_base_url("https://onec.example.com") == "https://onec.example.com/api/v1"
    assert normalize_api_base_url("https://onec.example.com/api/v1") == "https://onec.example.com/api/v1"


@pytest.mark.parametrize("bad_url", ["http://localhost:8000", "http://127.0.0.1:8000", "http://backend:8000"])
def test_attendance_agent_rejects_local_or_docker_api_urls(bad_url):
    with pytest.raises(RuntimeError):
        normalize_api_base_url(bad_url)


def test_load_config_prefers_attendance_agent_api_base_url_env(tmp_path, monkeypatch):
    config_path = tmp_path / "agent.json"
    config_path.write_text(
        """
        {
          "agent": {"id": "agent-test", "name": "agent-test", "site": "CPK"},
          "onec_smart": {"api_base_url": "https://wrong.example", "token_env": "ONEC_AGENT_TOKEN"},
          "storage": {"sqlite_path": "queue.sqlite3"},
          "devices": [{"id": "MOCK-1", "provider": "mock", "host": "mock", "port": 0}]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("ONEC_AGENT_TOKEN", "secret")
    monkeypatch.setenv("ATTENDANCE_AGENT_API_BASE_URL", "http://192.168.1.20:8000")

    config = load_config(config_path)

    assert config.api_base_url == "http://192.168.1.20:8000/api/v1"


def test_load_config_resolves_credential_ref_without_plaintext_config(tmp_path, monkeypatch):
    config_path = tmp_path / "agent.json"
    config_path.write_text(
        """
        {
          "agent": {"id": "agent-test", "name": "agent-test", "site": "CPK"},
          "onec_smart": {"api_base_url": "https://onec.example", "token_env": "ONEC_AGENT_TOKEN"},
          "storage": {"sqlite_path": "queue.sqlite3"},
          "devices": [{"id": "CPK-HIK-001", "provider": "hikvision", "host": "192.168.1.150", "port": 80, "credential_ref": "local:CPK-HIK-001"}]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("ONEC_AGENT_TOKEN", "secret")
    monkeypatch.setattr("onec_attendance_agent.config.load_credentials_ref", lambda ref: DeviceCredentials("admin", "secret-password"))

    config = load_config(config_path)

    assert config.devices[0].username == "admin"
    assert config.devices[0].password == "secret-password"
    assert "secret-password" not in config_path.read_text(encoding="utf-8")


def test_local_credentials_are_restricted_on_posix(tmp_path):
    path = save_local_credentials("CPK-HIK-001", "admin", "secret-password", base_dir=tmp_path)
    loaded = load_local_credentials("CPK-HIK-001", base_dir=tmp_path)

    assert path.stat().st_mode & 0o077 == 0
    assert loaded.username == "admin"
    assert loaded.password == "secret-password"


class _FakeResponse:
    def __init__(self, status: int, body: bytes = b"", headers: dict | None = None) -> None:
        self.status = status
        self._body = body
        self.headers = headers or {}

    def read(self, _size: int = -1) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def _hikvision_config(**overrides) -> DeviceConfig:
    values = {
        "id": "CPK-HIK-001",
        "provider": "hikvision",
        "host": "192.168.1.150",
        "port": 80,
        "configured_model": "DS-K1A8603MF-B",
    }
    values.update(overrides)
    return DeviceConfig(**values)


def test_hikvision_401_is_auth_required_not_offline(monkeypatch):
    monkeypatch.setattr("socket.create_connection", lambda *args, **kwargs: _FakeResponse(200))

    class Opener:
        def open(self, request, timeout):
            raise urllib.error.HTTPError(
                request.full_url,
                401,
                "Unauthorized",
                {"WWW-Authenticate": "Digest realm=\"Hikvision\""},
                io.BytesIO(b""),
            )

    monkeypatch.setattr("urllib.request.build_opener", lambda *args: Opener())
    result = HikvisionProvider(_hikvision_config()).test_connection()

    assert result["tcp_reachable"] is True
    assert result["http_reachable"] is True
    assert result["http_status"] == 401
    assert result["authentication_required"] is True
    assert result["authentication_method"] == "Digest"
    assert result["status"] == "AUTH_REQUIRED"


def test_hikvision_tcp_failure_is_device_offline(monkeypatch):
    def fail_connect(*_args, **_kwargs):
        raise OSError("no route")

    monkeypatch.setattr("socket.create_connection", fail_connect)
    result = HikvisionProvider(_hikvision_config()).test_connection()

    assert result["tcp_reachable"] is False
    assert result["http_reachable"] is False
    assert result["status"] == "DEVICE_OFFLINE"


def test_hikvision_unknown_capabilities_remain_null_and_no_port_scan(monkeypatch):
    calls = []

    def connect(address, timeout):
        calls.append(address)
        return _FakeResponse(200)

    monkeypatch.setattr("socket.create_connection", connect)
    result = HikvisionProvider(_hikvision_config(port=8080)).probe_capabilities()

    assert calls == [("192.168.1.150", 8080)]
    assert result["isapi_supported"] is None
    assert result["access_control_supported"] is None
    assert result["event_query_supported"] is None
    assert result["status"] == "DEVICE_REACHABLE"


def test_hikvision_credentials_are_not_returned(monkeypatch):
    monkeypatch.setattr("socket.create_connection", lambda *args, **kwargs: _FakeResponse(200))
    monkeypatch.setattr("urllib.request.build_opener", lambda *args: type("Opener", (), {"open": lambda self, request, timeout: _FakeResponse(200)})())

    result = HikvisionProvider(_hikvision_config(username="admin", password="super-secret")).test_connection()

    assert "super-secret" not in str(result)
    assert "admin" not in str(result)


def test_hikvision_serial_is_masked():
    assert _mask_serial("GE075123456748") == "GE075****48"


def test_backend_command_result_sanitizes_secrets_and_serials():
    result = _sanitize_command_result(
        {
            "password": "secret-password",
            "nested": {"agent_token": "secret-token", "serialNumber": "GE075123456748"},
            "ok": True,
        }
    )

    assert result["password"] == "[REDACTED]"
    assert result["nested"]["agent_token"] == "[REDACTED]"
    assert result["nested"]["serialNumber"] == "GE075****48"
    assert result["ok"] is True
