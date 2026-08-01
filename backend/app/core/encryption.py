"""
Chiffrement symétrique des données sensibles (clés API, tokens).
Utilise Fernet (AES-128-CBC + HMAC-SHA256).
La clé maître est lue depuis AI_PROVIDER_ENCRYPTION_KEY en env.
Si absente, une clé éphémère est générée (dev uniquement — les clés DB seront illisibles après redémarrage).
"""
from __future__ import annotations

import base64
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet

    # Priorité : settings (Pydantic) > variable d'environnement directe
    is_production = False
    try:
        from app.core.config import settings as _settings
        raw = (_settings.ai_provider_encryption_key or "").strip()
        is_production = (getattr(_settings, "env", "dev") or "").lower() in {"prod", "production"}
    except Exception:
        raw = os.environ.get("AI_PROVIDER_ENCRYPTION_KEY", "").strip()
        is_production = os.environ.get("ENV", "dev").lower() in {"prod", "production"}
    if raw:
        try:
            key = base64.urlsafe_b64decode(raw + "==")
            if len(key) != 32:
                raise ValueError("La clé doit être 32 octets (base64url).")
            _fernet = Fernet(base64.urlsafe_b64encode(key))
            return _fernet
        except Exception as exc:
            if is_production:
                raise RuntimeError(
                    "AI_PROVIDER_ENCRYPTION_KEY invalide en production : "
                    "démarrage refusé pour ne pas rendre les secrets illisibles."
                ) from exc
            logger.warning("encryption.key_invalid reason=%s — clé éphémère générée (dev)", exc)

    # Fail-closed en production : jamais de clé éphémère (les secrets deviendraient
    # illisibles après redémarrage et le secret-at-rest ne serait pas maîtrisé).
    if is_production:
        raise RuntimeError(
            "AI_PROVIDER_ENCRYPTION_KEY absent en production : démarrage refusé. "
            "Générez une clé via backend/scripts/generate_jwt_secret.py (32 octets base64url)."
        )

    ephemeral = Fernet.generate_key()
    logger.warning(
        "encryption.ephemeral_key — AI_PROVIDER_ENCRYPTION_KEY absent (dev). "
        "Les clés chiffrées seront illisibles après redémarrage du processus."
    )
    _fernet = Fernet(ephemeral)
    return _fernet


def encrypt_secret(plaintext: str) -> str:
    """Chiffre une chaîne et retourne le token base64 (stockable en DB)."""
    if not plaintext:
        return ""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str) -> str:
    """Déchiffre un token produit par encrypt_secret(). Lève ValueError si invalide."""
    if not token:
        return ""
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError(
            "Impossible de déchiffrer la clé API. "
            "La clé de chiffrement a peut-être changé."
        ) from exc


def generate_encryption_key() -> str:
    """Génère une nouvelle clé maître prête à être mise dans AI_PROVIDER_ENCRYPTION_KEY."""
    return base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
