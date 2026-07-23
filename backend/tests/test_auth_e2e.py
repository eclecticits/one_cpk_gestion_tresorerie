"""E2E tests for authentication endpoints — cas d'erreur."""
import pytest
from httpx import ASGITransport, AsyncClient


AUTH_PREFIX = "/api/v1/auth"


@pytest.mark.asyncio
async def test_login_missing_fields(app_client: AsyncClient) -> None:
    resp = await app_client.post(f"{AUTH_PREFIX}/login", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_login_invalid_credentials(app_client: AsyncClient) -> None:
    resp = await app_client.post(
        f"{AUTH_PREFIX}/login",
        json={"email": "nobody@example.com", "password": "wrong"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_invalid_email_format(app_client: AsyncClient) -> None:
    resp = await app_client.post(
        f"{AUTH_PREFIX}/login",
        json={"email": "not-an-email", "password": "password123"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_refresh_without_cookie() -> None:
    """Sans cookie refresh_token, /refresh doit retourner 401.
    Utilise un client frais pour éviter de hériter du cookie de session.
    """
    from app.main import app
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as fresh_client:
        resp = await fresh_client.post(f"{AUTH_PREFIX}/refresh")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_logout_unauthenticated(app_client: AsyncClient) -> None:
    resp = await app_client.post(f"{AUTH_PREFIX}/logout")
    # logout without a token should return 401 or 200 (clears cookie either way)
    assert resp.status_code in (200, 401)


@pytest.mark.asyncio
async def test_audit_sortie_requires_authentication(app_client: AsyncClient) -> None:
    resp = await app_client.get("/api/v1/audit/sortie", params={"ref": "PAY-TEST"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_discover_tenants_unknown_email(app_client: AsyncClient) -> None:
    resp = await app_client.get(
        f"{AUTH_PREFIX}/discover-tenants", params={"email": "nobody@example.com"}
    )
    # 404 when no user found for that email
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_bootstrap_admin_no_password_configured(app_client: AsyncClient) -> None:
    """Without BOOTSTRAP_ADMIN_PASSWORD configured the endpoint rejects the call."""
    resp = await app_client.post(
        f"{AUTH_PREFIX}/bootstrap-admin",
        json={
            "email": "admin@example.com",
            "password": "Admin1234!",
            "nom": "Admin",
            "prenom": "Test",
            "bootstrap_password": "wrong-bootstrap-key",
        },
    )
    # 501 (not configured), 403 (wrong password), or 409 (admin exists)
    assert resp.status_code in (400, 403, 501)
