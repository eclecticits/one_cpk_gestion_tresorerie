from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class SMTPConfig:
    host: str
    port: int
    user: str
    password: str
    sender: str


def resolve_smtp_config(ns: object | None) -> SMTPConfig | None:
    host = (settings.smtp_host or getattr(ns, "smtp_host", None) or "smtp.gmail.com").strip()
    port = int(settings.smtp_port or getattr(ns, "smtp_port", None) or 465)
    user = (settings.smtp_user or getattr(ns, "email_expediteur", None) or "").strip()
    password = (settings.smtp_password or getattr(ns, "smtp_password", None) or "").strip()
    if not user or not password:
        return None
    return SMTPConfig(host=host, port=port, user=user, password=password, sender=user)
