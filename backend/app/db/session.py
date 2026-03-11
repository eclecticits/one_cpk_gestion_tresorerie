from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from app.core.config import settings
from app.core.tenant_context import get_current_tenant_id
from app.db import audit  # noqa: F401
from app.models.user import User
from app.models.requisition import Requisition
from app.models.encaissement import Encaissement
from app.models.sortie_fonds import SortieFonds
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.print_settings import PrintSettings
from app.models.system_settings import SystemSettings
from app.models.cloture_caisse import ClotureCaisse
from app.models.audit_log import AuditLog
from app.models.system_event import SystemEvent
from app.models.organisation import Organisation

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@event.listens_for(Session, "do_orm_execute")
def _apply_tenant_criteria(execute_state) -> None:
    if not execute_state.is_select:
        return
    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        return
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(User, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(Requisition, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(Encaissement, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(SortieFonds, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(CaisseCentrale, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(CompteBancaire, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(PrintSettings, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(SystemSettings, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(ClotureCaisse, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(AuditLog, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(SystemEvent, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(Organisation, lambda cls: cls.id == tenant_id, include_aliases=True),
    )


async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
