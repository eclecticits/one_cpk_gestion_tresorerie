import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.base import Base  # noqa: E402
from app.models import budget as _budget  # noqa: F401,E402
from app.models import caisse_centrale as _caisse_centrale  # noqa: F401,E402
from app.models import dossier_requisition as _dossier_requisition  # noqa: F401,E402
from app.models import encaissement as _encaissement  # noqa: F401,E402
from app.models import expert_comptable as _expert_comptable  # noqa: F401,E402
from app.models import ligne_requisition as _ligne_requisition  # noqa: F401,E402
from app.models import organisation as _organisation  # noqa: F401,E402
from app.models import organisation_settings as _organisation_settings  # noqa: F401,E402
from app.models import payment_history as _payment_history  # noqa: F401,E402
from app.models import print_settings as _print_settings  # noqa: F401,E402
from app.models import rbac as _rbac  # noqa: F401,E402
from app.models import remboursement_transport as _remboursement_transport  # noqa: F401,E402
from app.models import requisition as _requisition  # noqa: F401,E402
from app.models import requisition_annexe as _requisition_annexe  # noqa: F401,E402
from app.models import requisition_approver as _requisition_approver  # noqa: F401,E402
from app.models import requisition_status_history as _requisition_status_history  # noqa: F401,E402
from app.models import service as _service  # noqa: F401,E402
from app.models import service_member_function as _service_member_function  # noqa: F401,E402
from app.models import subscription as _subscription  # noqa: F401,E402
from app.models import system_settings as _system_settings  # noqa: F401,E402
from app.models import transfert_interne as _transfert_interne  # noqa: F401,E402
from app.models import user as _user  # noqa: F401,E402
from app.models import user_service as _user_service  # noqa: F401,E402


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
