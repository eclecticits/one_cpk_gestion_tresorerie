from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, has_any_permission, has_permission
from app.db.session import get_db
from app.models.user import User
from app.modules.secretariat.models import OAuthConnection
from app.modules.secretariat.schemas import GoogleConnectOut, OAuthStatusOut
from app.modules.secretariat.services.audit import record_secretariat_audit
from app.modules.secretariat.services.oauth_service import (
    build_google_authorization_url,
    disconnect_google_connection,
    exchange_code_for_tokens,
    fetch_google_email,
    get_oauth_connection,
    upsert_google_connection,
    validate_google_state,
)

router = APIRouter()


def _google_callback_html(
    success: bool,
    message: str,
    error_code: str | None = None,
    return_to: str | None = None,
) -> HTMLResponse:
    import json as _json
    import urllib.parse
    params: dict[str, str] = {"google": "connected" if success else "error"}
    if error_code:
        params["google_error"] = error_code

    # Origine autorisée pour postMessage (extraite de return_to pour la sécurité)
    if return_to:
        _parsed = urllib.parse.urlparse(return_to)
        allowed_origin = f"{_parsed.scheme}://{_parsed.netloc}"
    else:
        allowed_origin = "*"

    qs = urllib.parse.urlencode(params)
    base = (return_to or "/secretariat/courrier").rstrip("?")
    fallback_target = f"{base}?{qs}"
    msg_data = _json.dumps({"type": "google_oauth", **params})

    return HTMLResponse(
        content=f"""<!doctype html>
<html lang="fr">
  <head><meta charset="utf-8"><title>Connexion Google</title></head>
  <body style="font-family:Arial,sans-serif;padding:32px;text-align:center">
    <p style="font-size:18px">{"✅ " if success else "❌ "}{message}</p>
    <p style="color:#6b7280;font-size:14px">Cette fenêtre va se fermer automatiquement…</p>
    <script>
      (function() {{
        var data = {msg_data};
        if (window.opener && !window.opener.closed) {{
          window.opener.postMessage(data, "{allowed_origin}");
          setTimeout(function() {{ window.close(); }}, 800);
        }} else {{
          window.location.replace("{fallback_target}");
        }}
      }})();
    </script>
  </body>
</html>""",
        status_code=200,
    )


@router.get("/oauth/status", response_model=OAuthStatusOut, dependencies=[Depends(has_permission("secretariat.manage_oauth"))])
async def oauth_status(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> OAuthStatusOut:
    res = await db.execute(
        select(OAuthConnection).where(
            OAuthConnection.organisation_id == tenant_id,
            OAuthConnection.user_id == user.id,
            OAuthConnection.provider == "google",
        )
    )
    connection = res.scalar_one_or_none()
    if connection is None:
        return OAuthStatusOut()
    return OAuthStatusOut(
        configured=connection.status == "connected",
        connected=connection.status == "connected",
        status=connection.status,
        email=connection.email,
        scopes=list(connection.scopes or []),
        expires_at=connection.expires_at,
    )


@router.get("/google/connect", response_model=GoogleConnectOut, dependencies=[Depends(has_permission("secretariat.manage_oauth"))])
async def google_connect(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> GoogleConnectOut:
    # L'origin du navigateur (frontend) est embarqué dans le state JWT pour que le
    # callback puisse rediriger vers la bonne URL quel que soit l'environnement.
    # Extraire l'origin du navigateur (scheme+host+port uniquement, sans path)
    import urllib.parse as _up
    _origin = request.headers.get("origin", "").strip()
    if not _origin:
        _ref = request.headers.get("referer", "").strip()
        if _ref:
            _p = _up.urlparse(_ref)
            _origin = f"{_p.scheme}://{_p.netloc}" if _p.scheme and _p.netloc else ""
    frontend_origin = _origin or None
    authorization_url = await build_google_authorization_url(
        db=db, user=user, organisation_id=tenant_id, frontend_origin=frontend_origin
    )
    await record_secretariat_audit(
        db,
        organisation_id=tenant_id,
        user_id=user.id,
        action="google_oauth_connect_started",
        agent_type="courrier",
        target_type="oauth_connection",
        target_id="google",
        metadata_json={"provider": "google", "scopes": ["gmail.readonly"]},
    )
    await db.commit()
    return GoogleConnectOut(authorization_url=authorization_url)


@router.get("/google/callback", response_class=HTMLResponse)
async def google_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    # Tenter d'extraire return_to depuis le state même en cas d'erreur
    _return_to: str | None = None
    if state:
        try:
            _, _, _return_to = validate_google_state(state)
        except Exception:
            pass

    if error:
        msgs = {
            "access_denied": "Accès refusé par Google. Assurez-vous d'être dans la liste des utilisateurs test de l'application OAuth.",
            "redirect_uri_mismatch": "URI de redirection non autorisée dans Google Cloud Console.",
        }
        human_msg = msgs.get(error, f"Erreur Google OAuth : {error}")
        return _google_callback_html(False, human_msg, error_code=error, return_to=_return_to)
    if not code or not state:
        return _google_callback_html(False, "Callback Google incomplet.", return_to=_return_to)
    try:
        user_id, tenant_id, _return_to = validate_google_state(state)
        res = await db.execute(
            select(User).where(
                User.id == user_id,
                User.organisation_id == tenant_id,
                User.active.is_(True),
            )
        )
        user = res.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Utilisateur OAuth invalide.")
        tokens = await exchange_code_for_tokens(code, db)
        access_token = tokens.get("access_token")
        email = await fetch_google_email(access_token) if access_token else None
        connection = await upsert_google_connection(
            db,
            user_id=user.id,
            organisation_id=tenant_id,
            tokens=tokens,
            email=email,
        )
        await db.flush()
        await record_secretariat_audit(
            db,
            organisation_id=tenant_id,
            user_id=user.id,
            action="google_oauth_connected",
            agent_type="courrier",
            target_type="oauth_connection",
            target_id=connection.id,
            metadata_json={"provider": "google", "email": email, "scopes": connection.scopes or []},
        )
        await db.commit()
    except HTTPException:
        await db.rollback()
        return _google_callback_html(False, "Connexion Google impossible.", return_to=_return_to)
    return _google_callback_html(True, "Connexion Google effectuée.", return_to=_return_to)


@router.get(
    "/google/status",
    response_model=OAuthStatusOut,
    dependencies=[Depends(has_any_permission(["secretariat.manage_oauth", "secretariat.use_agent_courrier"]))],
)
async def google_status(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> OAuthStatusOut:
    connection = await get_oauth_connection(db, user_id=user.id, organisation_id=tenant_id)
    if connection is None:
        return OAuthStatusOut()
    connected = connection.status == "connected"
    return OAuthStatusOut(
        configured=connected,
        connected=connected,
        status=connection.status,
        email=connection.email,
        scopes=list(connection.scopes or []),
        expires_at=connection.expires_at,
        message="Connexion Google active." if connected else "Connexion Google non configurée.",
    )


@router.delete("/google/disconnect", response_model=OAuthStatusOut, dependencies=[Depends(has_permission("secretariat.manage_oauth"))])
async def google_disconnect(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> OAuthStatusOut:
    connection = await get_oauth_connection(db, user_id=user.id, organisation_id=tenant_id)
    if connection is None:
        return OAuthStatusOut()
    await disconnect_google_connection(db, connection)
    await record_secretariat_audit(
        db,
        organisation_id=tenant_id,
        user_id=user.id,
        action="google_oauth_disconnected",
        agent_type="courrier",
        target_type="oauth_connection",
        target_id=connection.id,
        metadata_json={"provider": "google", "email": connection.email},
    )
    await db.commit()
    return OAuthStatusOut(status="disconnected", email=connection.email, message="Connexion Google désactivée.")
