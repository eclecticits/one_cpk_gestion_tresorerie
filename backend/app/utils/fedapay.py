from __future__ import annotations

import hmac
import hashlib
import time


def _extract_signatures(signature_header: str) -> tuple[str | None, list[str]]:
    if not signature_header:
        return None, []
    if "=" not in signature_header:
        return None, [signature_header.strip()]

    timestamp = None
    signatures: list[str] = []
    parts = [part.strip() for part in signature_header.split(",") if part.strip()]
    for part in parts:
        if "=" not in part:
            signatures.append(part)
            continue
        key, value = part.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if key in {"t", "ts", "timestamp"}:
            timestamp = value
        elif key in {"v1", "sig", "signature"}:
            signatures.append(value)
    return timestamp, signatures


def verify_fedapay_signature(
    *,
    payload: bytes,
    signature_header: str | None,
    secret: str | None,
    tolerance: int = 300,
) -> bool:
    if not signature_header or not secret:
        return False

    timestamp, signatures = _extract_signatures(signature_header)
    if not signatures:
        return False

    if timestamp:
        try:
            ts = int(timestamp)
        except ValueError:
            return False
        now = int(time.time())
        if abs(now - ts) > tolerance:
            return False
        signed_payload = f"{timestamp}.{payload.decode('utf-8')}".encode("utf-8")
    else:
        signed_payload = payload

    digest = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(digest, sig) for sig in signatures)
