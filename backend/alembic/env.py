from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import logging
import os

from app.core.config import settings
from app.db.base import Base

# Import models so metadata is registered
from app.models.audit_log import AuditLog  # noqa: F401
from app.models.cloture_caisse import ClotureCaisse  # noqa: F401
from app.models.denomination import Denomination  # noqa: F401
from app.models.commission_member import CommissionMember  # noqa: F401
from app.models.service_member_function import ServiceMemberFunction  # noqa: F401
from app.models.budget import BudgetExercice, BudgetPoste  # noqa: F401
from app.models.budget_audit_log import BudgetAuditLog  # noqa: F401
from app.models.print_settings import PrintSettings  # noqa: F401
from app.models.refresh_token import RefreshToken  # noqa: F401
from app.models.rbac import Role, Permission  # noqa: F401
from app.models.system_settings import SystemSettings  # noqa: F401
from app.models.platform_settings import PlatformSettings  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.organisation import Organisation  # noqa: F401
from app.models.service import Service  # noqa: F401
from app.models.document_sequence import DocumentSequence  # noqa: F401
from app.models.requisition import Requisition  # noqa: F401
from app.models.remboursement_transport import RemboursementTransport  # noqa: F401
from app.models.encaissement import Encaissement  # noqa: F401
from app.models.expert_comptable import ExpertComptable  # noqa: F401
from app.models.banque import Banque  # noqa: F401
from app.models.compte_bancaire import CompteBancaire  # noqa: F401
from app.models.rubrique import Rubrique  # noqa: F401
from app.models.service_rubrique import ServiceRubrique  # noqa: F401
from app.models.sortie_fonds import SortieFonds  # noqa: F401
from app.models.transfert_interne import TransfertInterne  # noqa: F401
from app.models.caisse_centrale import CaisseCentrale  # noqa: F401
from app.models.category_changes_history import CategoryChangesHistory  # noqa: F401
from app.models.imports_history import ImportsHistory  # noqa: F401
from app.models.ligne_requisition import LigneRequisition  # noqa: F401
from app.models.organisation_settings import OrganisationSettings  # noqa: F401
from app.models.payment_history import PaymentHistory  # noqa: F401
from app.models.payment_transaction import PaymentTransaction  # noqa: F401
from app.models.plan import Plan  # noqa: F401
from app.models.requisition_annexe import RequisitionAnnexe  # noqa: F401
from app.models.requisition_approver import RequisitionApprover  # noqa: F401
from app.models.saas_invoice import SaaSInvoice  # noqa: F401
from app.models.subscription import Subscription  # noqa: F401
from app.models.system_event import SystemEvent  # noqa: F401
from app.models.tenant_signup import TenantSignup  # noqa: F401
from app.models.user_role import UserRole  # noqa: F401
from app.models.user_service import user_services  # noqa: F401
from app.models.requisition_status_history import RequisitionStatusHistory  # noqa: F401
from app.models.dossier_requisition import DossierRequisition  # noqa: F401
from app.models.standard_classification import StandardClassification  # noqa: F401
from app.models.payment_log import PaymentLog  # noqa: F401
from app.models.saas_transaction import Transaction  # noqa: F401
from app.models.hr import HRContract, HRDocument, HREmployee, HRFunction, HRLeave, HRReference, HRService  # noqa: F401
from app.modules.secretariat.models import (  # noqa: F401
    OAuthConnection,
    SecretariatAgent,
    SecretariatAgendaItem,
    SecretariatAgendaReminder,
    SecretariatApproval,
    SecretariatAuditLog,
    SecretariatConversation,
    SecretariatMailDraft,
    SecretariatMeeting,
    SecretariatMeetingActionItem,
    SecretariatMeetingDecision,
    SecretariatMeetingParticipant,
    SecretariatMessage,
    SecretariatTask,
)

config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Use env var / settings for DB URL
def _masked_url(url: str) -> str:
    if "://" not in url or "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    creds, host = rest.split("@", 1)
    if ":" in creds:
        user, _ = creds.split(":", 1)
        return f"{scheme}://{user}:***@{host}"
    return url


database_url = os.getenv("DATABASE_URL", settings.database_url)
config.set_main_option("sqlalchemy.url", database_url)
logging.getLogger("alembic.runtime.migration").info("Using DATABASE_URL=%s", _masked_url(database_url))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
