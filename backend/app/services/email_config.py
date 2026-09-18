from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class SMTPConfig:
    host: str
    port: int
    user: str
    password: str
    sender: str


def normalize_smtp_password(value: str | None, *, host: str | None = None) -> str:
    """Normalise un secret SMTP sans altérer les mots de passe ordinaires.

    Google affiche les mots de passe d'application de 16 caractères par
    groupes de quatre. Un copier-coller depuis cet écran conserve souvent les
    trois espaces, que Gmail refuse ensuite lors de l'authentification SMTP.
    On compacte uniquement cette forme bien précise et uniquement pour les
    serveurs Gmail ; un mot de passe d'un autre fournisseur peut légitimement
    contenir des espaces.
    """
    password = (value or "").strip()
    smtp_host = (host or "").strip().lower()
    if smtp_host in {"smtp.gmail.com", "smtp.googlemail.com"}:
        compact = re.sub(r"\s+", "", password)
        if len(compact) == 16:
            return compact
    return password


def resolve_smtp_config(ns: object | None) -> SMTPConfig | None:
    host = (settings.smtp_host or getattr(ns, "smtp_host", None) or "smtp.gmail.com").strip()
    port = int(settings.smtp_port or getattr(ns, "smtp_port", None) or 465)
    user = (settings.smtp_user or getattr(ns, "email_expediteur", None) or "").strip()
    password = normalize_smtp_password(
        settings.smtp_password or getattr(ns, "smtp_password", None),
        host=host,
    )
    if not user or not password:
        return None
    return SMTPConfig(host=host, port=port, user=user, password=password, sender=user)
