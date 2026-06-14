from __future__ import annotations

import asyncio
import logging
import smtplib
import traceback
from email.message import EmailMessage

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.cache import get_redis
from app.core.config import settings

logger = logging.getLogger("onec_cpk_alerts")

# Durée minimale entre deux alertes du même type (secondes)
_ALERT_RATE_LIMIT_TTL = 300  # 5 minutes


async def _should_send_alert(error_key: str) -> bool:
    """Retourne True si aucune alerte du même type n'a été envoyée récemment.

    Utilise Redis SET NX (set-if-not-exists) comme verrou TTL.
    Si Redis est indisponible, laisse passer l'alerte (fail-open).
    """
    client = get_redis()
    if client is None:
        return True
    try:
        redis_key = f"alert:rate:{error_key}"
        acquired = await client.set(redis_key, "1", ex=_ALERT_RATE_LIMIT_TTL, nx=True)
        return bool(acquired)
    except Exception:
        return True


def _send_alert_email_sync(subject: str, body: str) -> None:
    """Envoi synchrone de l'email d'alerte — exécuté dans un thread."""
    smtp_host = settings.smtp_host
    smtp_port = settings.smtp_port
    smtp_user = settings.smtp_user
    smtp_password = settings.smtp_password

    if not all([smtp_host, smtp_port, smtp_user, smtp_password]):
        logger.debug("Alerte email ignorée : SMTP non configuré")
        return

    msg = EmailMessage()
    msg["Subject"] = f"[ONEC-CPK ALERTE] {subject}"
    msg["From"] = smtp_user
    msg["To"] = smtp_user
    msg.set_content(body)

    try:
        port = int(smtp_port)
        factory = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
        with factory(smtp_host, port, timeout=10) as smtp:
            if port != 465:
                smtp.ehlo()
                if smtp.has_extn("starttls"):
                    smtp.starttls()
                    smtp.ehlo()
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(msg)
        logger.info("Alerte email envoyée : %s", subject)
    except Exception as exc:
        logger.warning("Échec envoi alerte email : %s", exc)


async def _send_telegram_alert(subject: str, body: str) -> None:
    """Envoie une alerte Telegram via Bot API.

    Silencieux si TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID sont absents.
    Timeout 5 s — non-bloquant (appelé en fire-and-forget via create_task).
    """
    token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id
    if not token or not chat_id:
        return

    # Tronquer pour respecter la limite Telegram (4096 caractères)
    text = f"🚨 *ONEC-CPK — {subject}*\n\n{body}"
    if len(text) > 4000:
        text = text[:3990] + "\n...[tronqué]"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                logger.warning("Telegram alert HTTP %s : %s", resp.status_code, resp.text[:200])
            else:
                logger.info("Alerte Telegram envoyée : %s", subject)
    except Exception as exc:
        logger.warning("Échec envoi alerte Telegram : %s", exc)


async def _fire_alert(error_key: str, subject: str, body: str) -> None:
    if not await _should_send_alert(error_key):
        logger.debug("Alerte rate-limitée : %s", error_key)
        return
    loop = asyncio.get_event_loop()
    # Email (synchrone dans thread) + Telegram (async) en parallèle
    await asyncio.gather(
        loop.run_in_executor(None, _send_alert_email_sync, subject, body),
        _send_telegram_alert(subject, body),
        return_exceptions=True,
    )


async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handler global pour les exceptions non interceptées (HTTP 500).

    - Logue en CRITICAL avec stacktrace complète.
    - Envoie email + Telegram (rate-limité à 1 par 5 min par type d'erreur).
    - Retourne une réponse 500 générique sans exposer l'erreur interne.
    """
    tb = traceback.format_exc()
    error_type = type(exc).__name__

    logger.critical(
        "UNHANDLED_EXCEPTION type=%s path=%s method=%s\n%s",
        error_type,
        request.url.path,
        request.method,
        tb,
    )

    body = (
        f"Erreur non gérée sur l'API ONEC-CPK\n\n"
        f"Route  : {request.method} {request.url.path}\n"
        f"Type   : {error_type}\n\n"
        f"Traceback:\n{tb}"
    )
    asyncio.create_task(
        _fire_alert(
            error_key=error_type,
            subject=f"Erreur 500 — {error_type}",
            body=body,
        )
    )

    return JSONResponse(
        status_code=500,
        content={"detail": "Erreur interne du serveur"},
    )


class ErrorTrackingMiddleware(BaseHTTPMiddleware):
    """Attrape les exceptions non gérées et les réponses 5xx.

    - Exception non interceptée → log CRITICAL + alerte email+Telegram → 500 générique
    - Réponse 5xx connue → log ERROR
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        try:
            response = await call_next(request)
        except Exception as exc:
            try:
                return await internal_error_handler(request, exc)
            except Exception:
                logger.critical("internal_error_handler raised — falling back to bare 500")
                return JSONResponse(
                    status_code=500, content={"detail": "Erreur interne du serveur"}
                )

        if response.status_code >= 500:
            logger.error(
                "HTTP_5XX method=%s path=%s status=%s",
                request.method,
                request.url.path,
                response.status_code,
            )
        return response
