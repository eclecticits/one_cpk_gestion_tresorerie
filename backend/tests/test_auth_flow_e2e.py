"""Tests E2E Phase 1 — flux d'authentification complet.

Couvre :
  - Login utilisateur valide
  - /auth/me après connexion
  - Route protégée /dashboard/stats
  - Refresh token
  - Accès non authentifié → 401
"""
import pytest
from httpx import AsyncClient

from tests.conftest import E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD  # noqa: E402

AUTH = "/api/v1/auth"
DASHBOARD = "/api/v1/dashboard"


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_login_valide_retourne_access_token(
    app_client: AsyncClient, test_admin_user
) -> None:
    """Un login correct retourne un access_token et un cookie refresh_token."""
    resp = await app_client.post(
        f"{AUTH}/login",
        json={"email": E2E_ADMIN_EMAIL, "password": E2E_ADMIN_PASSWORD},
        headers={"X-Tenant-ID": str(test_admin_user.organisation_id)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("access_token"), "access_token absent"
    assert body.get("role") == "admin"
    assert body.get("organisation_id") == test_admin_user.organisation_id
    # Cookie refresh_token doit être posé
    assert "refresh_token" in resp.cookies or "refresh_token" in {
        c.name for c in resp.cookies.jar
    }


@pytest.mark.asyncio
async def test_login_mauvais_mot_de_passe(app_client: AsyncClient, test_admin_user) -> None:
    resp = await app_client.post(
        f"{AUTH}/login",
        json={"email": E2E_ADMIN_EMAIL, "password": "mauvais_mdp"},
        headers={"X-Tenant-ID": str(test_admin_user.organisation_id)},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /auth/me
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_me_retourne_profil_utilisateur(
    app_client: AsyncClient, admin_access_token: str, test_admin_user
) -> None:
    """/auth/me doit retourner les informations de l'utilisateur connecté."""
    resp = await app_client.get(
        f"{AUTH}/me",
        headers={"Authorization": f"Bearer {admin_access_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == E2E_ADMIN_EMAIL
    assert body["role"] == "admin"
    assert body["active"] is True
    assert body["organisation_id"] == test_admin_user.organisation_id


@pytest.mark.asyncio
async def test_me_sans_token_retourne_401(app_client: AsyncClient) -> None:
    resp = await app_client.get(f"{AUTH}/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_token_invalide_retourne_401(app_client: AsyncClient) -> None:
    resp = await app_client.get(
        f"{AUTH}/me",
        headers={"Authorization": "Bearer token.invalide.ici"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Route protégée : /dashboard/stats
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dashboard_stats_accessible_admin(
    app_client: AsyncClient, admin_access_token: str
) -> None:
    """Un admin authentifié peut accéder aux stats du dashboard."""
    resp = await app_client.get(
        f"{DASHBOARD}/stats",
        headers={"Authorization": f"Bearer {admin_access_token}"},
    )
    # 200 = accès OK ; 422 = paramètres manquants mais route accessible
    assert resp.status_code in (200, 422), f"Inattendu : {resp.status_code} — {resp.text}"


@pytest.mark.asyncio
async def test_dashboard_stats_sans_token_retourne_401(app_client: AsyncClient) -> None:
    resp = await app_client.get(f"{DASHBOARD}/stats")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Refresh token
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_token_retourne_nouveau_access_token(
    app_client: AsyncClient, test_admin_user
) -> None:
    """Le refresh token (cookie) permet d'obtenir un nouveau access_token."""
    # Login dédié pour ce test (ne pas partager le cookie de session)
    login_resp = await app_client.post(
        f"{AUTH}/login",
        json={"email": E2E_ADMIN_EMAIL, "password": E2E_ADMIN_PASSWORD},
        headers={"X-Tenant-ID": str(test_admin_user.organisation_id)},
    )
    assert login_resp.status_code == 200
    original_token = login_resp.json().get("access_token")
    assert original_token

    # Le cookie refresh_token est automatiquement transmis par le client httpx
    refresh_resp = await app_client.post(f"{AUTH}/refresh")
    assert refresh_resp.status_code == 200, f"Refresh échoué : {refresh_resp.text}"
    refresh_body = refresh_resp.json()
    new_token = refresh_body.get("access_token")
    assert new_token, "Pas d'access_token dans la réponse refresh"
    # Le token est un JWT bien formé (3 segments base64 séparés par des points)
    assert len(new_token.split(".")) == 3, "Le token retourné n'est pas un JWT valide"


@pytest.mark.asyncio
async def test_refresh_sans_cookie_retourne_401(app_client: AsyncClient) -> None:
    """Sans cookie refresh_token, le refresh doit retourner 401."""
    # Client sans cookie
    from httpx import ASGITransport, AsyncClient as FreshClient
    from app.main import app
    async with FreshClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as fresh:
        resp = await fresh.post(f"{AUTH}/refresh")
    assert resp.status_code == 401
