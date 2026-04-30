from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from app.core.config import settings
from app.core.tenant_context import get_current_tenant_id
from app.db import audit  # noqa: F401
from app.models.user import User
from app.models.requisition import Requisition
from app.models.dossier_requisition import DossierRequisition
from app.models.encaissement import Encaissement, EncaissementArticle
from app.models.sortie_fonds import SortieFonds
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.banque import Banque
from app.models.print_settings import PrintSettings
from app.models.system_settings import SystemSettings
from app.models.cloture_caisse import ClotureCaisse
from app.models.audit_log import AuditLog
from app.models.system_event import SystemEvent
from app.models.organisation import Organisation
from app.models.budget import BudgetExercice, BudgetPoste
from app.models.budget_audit_log import BudgetAuditLog
from app.models.payment_history import PaymentHistory
from app.models.payment_transaction import PaymentTransaction
from app.models.saas_invoice import SaaSInvoice
from app.models.subscription import Subscription
from app.models.organisation_settings import OrganisationSettings
from app.models.service import Service
from app.models.service_rubrique import ServiceRubrique
from app.models.commission_member import CommissionMember
from app.models.service_member_function import ServiceMemberFunction

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
)
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
        with_loader_criteria(EncaissementArticle, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(SortieFonds, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(CaisseCentrale, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(CompteBancaire, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(Banque, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(PrintSettings, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(SystemSettings, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(ClotureCaisse, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(AuditLog, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(SystemEvent, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(Organisation, lambda cls: cls.id == tenant_id, include_aliases=True),
        with_loader_criteria(BudgetExercice, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(BudgetPoste, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(BudgetAuditLog, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(PaymentHistory, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(PaymentTransaction, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(SaaSInvoice, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(Subscription, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(OrganisationSettings, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(Service, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(ServiceMemberFunction, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
    )


@event.listens_for(Session, "before_flush")
def _apply_tenant_to_new_objects(session, flush_context, instances) -> None:
    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        return
    for obj in session.new:
        if hasattr(obj, "organisation_id"):
            setattr(obj, "organisation_id", tenant_id)
    for obj in session.dirty:
        if hasattr(obj, "organisation_id"):
            current_org = getattr(obj, "organisation_id", None)
            if current_org is not None and current_org != tenant_id:
                raise ValueError("Tenant mismatch: organisation_id ne correspond pas au contexte courant.")


async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
