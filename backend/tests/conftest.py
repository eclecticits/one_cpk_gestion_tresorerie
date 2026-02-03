import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.base import Base  # noqa: E402
from app.models import encaissement as _encaissement  # noqa: F401,E402
from app.models import expert_comptable as _expert_comptable  # noqa: F401,E402
from app.models import payment_history as _payment_history  # noqa: F401,E402
from app.models import user as _user  # noqa: F401,E402


@pytest.fixture(scope="session")
def test_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    return url


@pytest_asyncio.fixture(scope="session")
async def async_engine(test_database_url: str) -> AsyncEngine:
    engine = create_async_engine(test_database_url, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def async_session(async_engine: AsyncEngine):
    return async_sessionmaker(bind=async_engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture
async def db_session(async_session):
    session: AsyncSession = async_session()
    try:
        yield session
    finally:
        await session.close()
