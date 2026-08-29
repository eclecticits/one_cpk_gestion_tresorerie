import os
import sys
import importlib
import pkgutil
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Constantes utilisées par les fixtures E2E
E2E_ADMIN_EMAIL = "admin-e2e@example.com"
E2E_ADMIN_PASSWORD = "Admin_E2E_2026!"
E2E_ORG_SLUG = "org-e2e-test"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
ATTENDANCE_AGENT_ROOT = PROJECT_ROOT / "attendance-agent"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(ATTENDANCE_AGENT_ROOT) not in sys.path:
    # Composant local distinct : ce chemin concerne uniquement la collecte pytest.
    sys.path.insert(0, str(ATTENDANCE_AGENT_ROOT))

from app.db.base import Base  # noqa: E402
import app.models as _models_pkg  # noqa: E402
for module_info in pkgutil.iter_modules(_models_pkg.__path__, _models_pkg.__name__ + "."):
    importlib.import_module(module_info.name)
from app.modules.secretariat import models as _secretariat_models  # noqa: F401,E402


@pytest.fixture(autouse=True)
def reset_test_rate_limit_state():
    """Isole le rate-limit mémoire entre tests sans désactiver la protection en prod."""
    yield
    from app.core.limiter import limiter
    limiter._storage.reset()
    from app.api.v1.endpoints import auth
    auth._login_failure_fallback.clear()
    auth._login_lock_fallback.clear()


@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    return url


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def async_engine(test_database_url: str) -> AsyncEngine:
    engine = create_async_engine(test_database_url, pool_pre_ping=True, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def async_session(async_engine: AsyncEngine):
    return async_sessionmaker(bind=async_engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture(loop_scope="session")
async def db_session(async_session):
    session: AsyncSession = async_session()
    try:
        yield session
    finally:
        await session.rollback()
        await session.close()


# ---------------------------------------------------------------------------
# E2E HTTP client fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def app_client(async_engine: AsyncEngine) -> AsyncGenerator[AsyncClient, None]:
    """Full-stack httpx client against the FastAPI app, using the test DB.

    Redis is mocked out so E2E tests run without a Redis server.
    """
    from app.main import app
    from app.db.session import SessionLocal, get_db

    test_session_factory = async_sessionmaker(
        bind=async_engine, expire_on_commit=False, class_=AsyncSession
    )

    async def override_get_db():
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    # Stub Redis so health/ready doesn't fail due to missing Redis in CI
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.delete = AsyncMock(return_value=1)
    mock_redis.keys = AsyncMock(return_value=[])
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock(return_value=True)
    mock_redis.ttl = AsyncMock(return_value=None)
    mock_redis.scan = AsyncMock(return_value=(0, []))

    with patch("app.core.cache._redis_client", mock_redis):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield client

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Fixtures de données : organisation + utilisateur admin pour les tests E2E
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_organisation(async_engine: AsyncEngine):
    """Crée (ou réutilise) une organisation de test pour la session."""
    from app.models.organisation import Organisation

    async with AsyncSession(async_engine) as session:
        # Vérifier si elle existe déjà (re-run de tests)
        from sqlalchemy import select
        res = await session.execute(select(Organisation).where(Organisation.slug == E2E_ORG_SLUG))
        org = res.scalar_one_or_none()
        if org is None:
            org = Organisation(
                nom="Organisation E2E Test",
                slug=E2E_ORG_SLUG,
                is_active=True,
                plan_type="STANDARD",
                status_abonnement="ACTIVE",
            )
            session.add(org)
            await session.commit()
            await session.refresh(org)
        return org


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_admin_user(async_engine: AsyncEngine, test_organisation):
    """Crée (ou réutilise) un utilisateur admin de test pour la session."""
    from app.models.user import User
    from app.core.security import hash_password
    from sqlalchemy import select

    async with AsyncSession(async_engine) as session:
        res = await session.execute(
            select(User).where(User.email == E2E_ADMIN_EMAIL, User.organisation_id == test_organisation.id)
        )
        user = res.scalar_one_or_none()
        if user is None:
            user = User(
                email=E2E_ADMIN_EMAIL,
                hashed_password=hash_password(E2E_ADMIN_PASSWORD),
                nom="Admin",
                prenom="E2E",
                role="admin",
                organisation_id=test_organisation.id,
                active=True,
                is_email_verified=True,
                is_first_login=False,
                must_change_password=False,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        return user


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def admin_access_token(app_client: AsyncClient, test_admin_user) -> str:
    """Connecte l'admin et retourne l'access token (session-scoped, lecture seule)."""
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": E2E_ADMIN_EMAIL, "password": E2E_ADMIN_PASSWORD},
        headers={"X-Tenant-ID": str(test_admin_user.organisation_id)},
    )
    assert resp.status_code == 200, f"Login admin échoué : {resp.text}"
    token = resp.json().get("access_token")
    assert token, "access_token absent de la réponse login"
    return token
