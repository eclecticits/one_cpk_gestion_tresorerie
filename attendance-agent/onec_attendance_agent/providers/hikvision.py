from __future__ import annotations

import socket
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime
from xml.etree import ElementTree

from onec_attendance_agent.config import DeviceConfig
from onec_attendance_agent.models.events import NormalizedPunch


READ_ONLY_ISAPI_PATHS = (
    "/ISAPI/System/deviceInfo",
    "/ISAPI/System/capabilities",
    "/ISAPI/AccessControl/capabilities",
    "/ISAPI/Event/capabilities",
)


def _default_probe_result(config: DeviceConfig) -> dict:
    return {
        "manufacturer": "Hikvision",
        "configured_model": config.configured_model or "DS-K1A8603MF-B",
        "detected_model": None,
        "firmware_version": None,
        "device_name": None,
        "serial_number_masked": None,
        "host": config.host,
        "port": config.port,
        "tcp_reachable": False,
        "tcp_latency_ms": None,
        "http_reachable": False,
        "http_status": None,
        "https_reachable": False,
        "https_status": None,
        "authentication_required": False,
        "authentication_ok": False,
        "authentication_method": None,
        "isapi_supported": None,
        "access_control_supported": None,
        "attendance_supported": None,
        "event_query_supported": None,
        "device_info_ok": None,
        "status": "UNKNOWN",
    }


def _mask_serial(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:5]}****{value[-2:]}"


def _xml_text(root: ElementTree.Element, names: tuple[str, ...]) -> str | None:
    for element in root.iter():
        local_name = element.tag.rsplit("}", 1)[-1]
        if local_name in names and element.text:
            return element.text.strip()
    return None


class HikvisionProvider:
    """Provider DS-K1A8603MF-B non destructif.

    Les probes restent strictement en lecture seule et ne supposent pas qu'ISAPI
    est disponible avant une reponse reelle de l'appareil.
    """

    def __init__(self, config: DeviceConfig) -> None:
        self.config = config
        self.device_id = config.id

    def test_connection(self) -> dict:
        return self._probe(include_isapi=False)

    def probe_capabilities(self) -> dict:
        return self._probe(include_isapi=True)

    def _probe(self, include_isapi: bool) -> dict:
        started = time.perf_counter()
        result = _default_probe_result(self.config)
        try:
            with socket.create_connection((self.config.host, self.config.port), timeout=3):
                result["tcp_reachable"] = True
        except OSError as exc:
            result["tcp_latency_ms"] = int((time.perf_counter() - started) * 1000)
            result["error"] = str(exc)
            result["status"] = "DEVICE_OFFLINE"
            return result

        result["tcp_latency_ms"] = int((time.perf_counter() - started) * 1000)
        scheme = self._scheme()
        if scheme is None:
            result["status"] = "DEVICE_REACHABLE"
            return result

        root_probe = self._request("/", scheme=scheme)
        self._merge_http_result(result, root_probe, scheme)
        if root_probe.get("auth_header"):
            result["authentication_required"] = True
            result["authentication_method"] = self._auth_method(root_probe["auth_header"])
        if root_probe.get("status") == 401:
            result["status"] = "AUTH_REQUIRED"
        elif root_probe.get("network_error"):
            result["status"] = "DEVICE_REACHABLE"
        elif root_probe.get("status") is not None:
            result["status"] = "DEVICE_REACHABLE"

        if include_isapi:
            self._probe_isapi(result, scheme)
        return result

    def _scheme(self) -> str | None:
        if self.config.protocol in {"http", "https"}:
            return self.config.protocol
        if self.config.port == 443:
            return "https"
        if self.config.port == 80:
            return "http"
        return None

    def _request(self, path: str, scheme: str, authenticated: bool = False) -> dict:
        url = f"{scheme}://{self.config.host}:{self.config.port}{path}"
        request = urllib.request.Request(url, method="GET")
        handlers = []
        if scheme == "https":
            handlers.append(urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
        if authenticated and self.config.username and self.config.password:
            password_mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
            password_mgr.add_password(None, url, self.config.username, self.config.password)
            handlers.extend([
                urllib.request.HTTPDigestAuthHandler(password_mgr),
                urllib.request.HTTPBasicAuthHandler(password_mgr),
            ])
        opener = urllib.request.build_opener(*handlers)
        try:
            with opener.open(request, timeout=3) as response:
                return {"status": response.status, "body": response.read(256 * 1024), "headers": dict(response.headers)}
        except urllib.error.HTTPError as exc:
            return {"status": exc.code, "body": exc.read(64 * 1024), "headers": dict(exc.headers), "auth_header": exc.headers.get("WWW-Authenticate")}
        except Exception as exc:
            return {"network_error": str(exc)}

    def _merge_http_result(self, result: dict, probe: dict, scheme: str) -> None:
        status = probe.get("status")
        if scheme == "https":
            result["https_reachable"] = status is not None
            result["https_status"] = status
        else:
            result["http_reachable"] = status is not None
            result["http_status"] = status

    def _auth_method(self, header: str) -> str | None:
        lower = header.lower()
        if "digest" in lower:
            return "Digest"
        if "basic" in lower:
            return "Basic"
        return "Unknown"

    def _probe_isapi(self, result: dict, scheme: str) -> None:
        device_info = self._request("/ISAPI/System/deviceInfo", scheme=scheme, authenticated=False)
        self._merge_http_result(result, device_info, scheme)
        if device_info.get("status") == 401:
            result["authentication_required"] = True
            if device_info.get("auth_header"):
                result["authentication_method"] = self._auth_method(device_info["auth_header"])
            if self.config.username and self.config.password:
                device_info = self._request("/ISAPI/System/deviceInfo", scheme=scheme, authenticated=True)
                self._merge_http_result(result, device_info, scheme)
                result["authentication_ok"] = 200 <= int(device_info.get("status") or 0) < 300
            else:
                result["status"] = "AUTH_REQUIRED"
                return

        status = device_info.get("status")
        if status and 200 <= int(status) < 300 and device_info.get("body"):
            result["isapi_supported"] = True
            result["device_info_ok"] = True
            result["status"] = "ISAPI_AVAILABLE"
            self._extract_device_info(result, device_info["body"])
        elif status in {404, 405}:
            result["isapi_supported"] = False
            result["device_info_ok"] = False
            result["status"] = "ISAPI_UNAVAILABLE"
        elif status == 401:
            result["status"] = "AUTH_FAILED" if self.config.username and self.config.password else "AUTH_REQUIRED"

        if result["isapi_supported"] is True and result["authentication_required"] and not result["authentication_ok"]:
            return
        for path in READ_ONLY_ISAPI_PATHS[1:]:
            probe = self._request(path, scheme=scheme, authenticated=bool(self.config.username and self.config.password))
            if path.endswith("/AccessControl/capabilities") and probe.get("status"):
                result["access_control_supported"] = 200 <= int(probe["status"]) < 300
            if path.endswith("/Event/capabilities") and probe.get("status"):
                result["event_query_supported"] = 200 <= int(probe["status"]) < 300

    def _extract_device_info(self, result: dict, body: bytes) -> None:
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError:
            return
        result["detected_model"] = _xml_text(root, ("model", "deviceModel"))
        result["firmware_version"] = _xml_text(root, ("firmwareVersion", "firmwareReleasedDate"))
        result["device_name"] = _xml_text(root, ("deviceName", "hostName"))
        result["serial_number_masked"] = _mask_serial(_xml_text(root, ("serialNumber", "serialNo")))

    def fetch_events(self, since: datetime | None = None) -> list[NormalizedPunch]:
        raise NotImplementedError("fetch_events Hikvision bloque jusqu'a validation des capacites reelles DS-K1A8603MF-B")

    def get_device_info(self) -> dict:
        return {"provider": "hikvision", "status": "UNKNOWN", "configured_model": self.config.configured_model or "DS-K1A8603MF-B"}
