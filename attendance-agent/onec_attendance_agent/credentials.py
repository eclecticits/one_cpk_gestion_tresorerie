from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import getpass
import json
import os
import platform
from dataclasses import dataclass
from pathlib import Path


APP_DIR = "ONEC/AttendanceAgent"


@dataclass(frozen=True)
class DeviceCredentials:
    username: str
    password: str


class CredentialStoreError(RuntimeError):
    pass


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _default_store_dir() -> Path:
    if platform.system().lower() == "windows":
        root = os.getenv("ProgramData") or r"C:\ProgramData"
        return Path(root) / "ONEC" / "AttendanceAgent" / "credentials"
    if os.geteuid() == 0:
        return Path("/etc/onec-attendance-agent/credentials")
    return Path.home() / ".config" / "onec-attendance-agent" / "credentials"


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value)


def _credential_path(device_id: str, base_dir: Path | None = None) -> Path:
    suffix = ".dpapi" if platform.system().lower() == "windows" else ".json"
    return (base_dir or _default_store_dir()) / f"{_safe_name(device_id)}{suffix}"


def _protect_windows(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_blob = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    out_blob = DATA_BLOB()
    if not crypt32.CryptProtectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
        raise CredentialStoreError("DPAPI CryptProtectData failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _unprotect_windows(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_blob = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    out_blob = DATA_BLOB()
    if not crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)):
        raise CredentialStoreError("DPAPI CryptUnprotectData failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _check_posix_secret_permissions(path: Path) -> None:
    if platform.system().lower() == "windows":
        return
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise CredentialStoreError(f"Credential file must not be group/world readable: {path}")


def save_local_credentials(device_id: str, username: str, password: str, base_dir: Path | None = None) -> Path:
    path = _credential_path(device_id, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"username": username, "password": password}, separators=(",", ":")).encode("utf-8")
    if platform.system().lower() == "windows":
        data = base64.b64encode(_protect_windows(payload)).decode("ascii")
        path.write_text(json.dumps({"format": "dpapi-v1", "data": data}), encoding="utf-8")
    else:
        # Linux relies on root ownership plus 0600 permissions; do not relax this for service use.
        old_umask = os.umask(0o177)
        try:
            path.write_text(json.dumps({"format": "posix-0600-v1", "username": username, "password": password}), encoding="utf-8")
        finally:
            os.umask(old_umask)
        path.chmod(0o600)
    return path


def load_local_credentials(device_id: str, base_dir: Path | None = None) -> DeviceCredentials:
    path = _credential_path(device_id, base_dir)
    if not path.is_file():
        raise CredentialStoreError(f"Credential file not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("format") == "dpapi-v1":
        payload = json.loads(_unprotect_windows(base64.b64decode(raw["data"])).decode("utf-8"))
    else:
        _check_posix_secret_permissions(path)
        payload = raw
    return DeviceCredentials(username=payload["username"], password=payload["password"])


def load_credentials_ref(ref: str) -> DeviceCredentials:
    if ref.startswith("local:"):
        return load_local_credentials(ref.split(":", 1)[1])
    raise CredentialStoreError(f"Unsupported credential_ref: {ref}")


def prompt_and_store_credentials(device_id: str, username: str | None = None) -> Path:
    resolved_username = username or input("Hikvision username: ").strip()
    password = getpass.getpass("Hikvision password: ")
    if not resolved_username or not password:
        raise CredentialStoreError("Username and password are required")
    return save_local_credentials(device_id, resolved_username, password)
