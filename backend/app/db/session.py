from __future__ import annotations

import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import event, select
from sqlalchemy.orm import Session, with_loader_criteria

from app.core.config import settings
from app.core.db_perf import record_db_connection_usage, record_db_query
from app.core.tenant_context import get_current_tenant_id
from app.db import audit  # noqa: F401
from app.models.user import User
from app.models.requisition import Requisition
from app.models.dossier_requisition import DossierRequisition
from app.models.ligne_requisition import LigneRequisition
from app.models.requisition_annexe import RequisitionAnnexe
from app.models.requisition_approver import RequisitionApprover
from app.models.requisition_status_history import RequisitionStatusHistory
from app.models.encaissement import Encaissement, EncaissementArticle
from app.models.sortie_fonds import SortieFonds
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.banque import Banque
from app.models.print_settings import PrintSettings
from app.models.system_settings import SystemSettings
from app.models.cloture_caisse import ClotureCaisse
from app.models.regularisation_caisse import RegularisationCaisse
from app.models.audit_log import AuditLog
from app.models.system_event import SystemEvent
from app.models.notification_log import NotificationLog
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
from app.models.document_sequence import DocumentSequence
from app.models.payment_log import PaymentLog
from app.models.standard_classification import StandardClassification
from app.models.remboursement_transport import RemboursementTransport, ParticipantTransport
from app.models.transfert_interne import TransfertInterne
from app.models.hr import HRAttendance, HRAttendanceAgent, HRAttendanceAgentCommand, HRAttendanceAgentEnrollment, HRAttendanceAgentRelease, HRAttendanceDevice, HRAttendanceDeviceEmployeeMapping, HRAttendancePunch, HRAttendanceUnmappedPunch, HRContract, HRDocument, HREmployee, HRFunction, HRLeave, HRReference, HRService
from app.modules.secretariat.models import (
    OAuthConnection,
    SecretariatAgent,
    SecretariatAgendaItem,
    SecretariatAgendaReminder,
    SecretariatApproval,
    SecretariatAuditLog,
    SecretariatConversation,
    SecretariatMailDraft,
    SecretariatDocument,
    SecretariatDocumentVersion,
    SecretariatMeeting,
    SecretariatMeetingActionItem,
    SecretariatMeetingDecision,
    SecretariatMeetingParticipant,
    SecretariatMessage,
    SecretariatTask,
)
from app.modules.comptabilite.models import (
    ComptaCompte,
    ComptaEcriture,
    ComptaEtablissement,
    ComptaExercice,
    ComptaJournal,
    ComptaLigneEcriture,
    ComptaPeriode,
    ComptaReferentiel,
    ComptaMappingCompteBancaire,
    ComptaMappingPosteBudgetaire,
    ComptaMappingRubrique,
    ComptaPosteEtat,
    ComptaPosteEtatCompte,
    ComptaSequence,
    ComptaSociete,
    ComptaTauxChange,
)

logger = logging.getLogger("onec_cpk_db_pool")

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=settings.db_pool_pre_ping,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _pool_snapshot() -> dict[str, int | None]:
    pool = engine.sync_engine.pool
    snapshot: dict[str, int | None] = {}
    for key, attr in {
        "size": "size",
        "checked_in": "checkedin",
        "checked_out": "checkedout",
        "overflow": "overflow",
    }.items():
        fn = getattr(pool, attr, None)
        snapshot[key] = int(fn()) if callable(fn) else None
    return snapshot


def log_pool_configuration() -> None:
    max_potential_connections = settings.backend_workers * (settings.db_pool_size + settings.db_max_overflow)
    logger.warning(
        "DB_POOL_CONFIG pool_size=%s max_overflow=%s pool_timeout=%s pool_recycle=%s pool_pre_ping=%s "
        "workers=%s max_potential_connections=%s",
        settings.db_pool_size,
        settings.db_max_overflow,
        settings.db_pool_timeout,
        settings.db_pool_recycle,
        settings.db_pool_pre_ping,
        settings.backend_workers,
        max_potential_connections,
    )


@event.listens_for(engine.sync_engine, "connect")
def _on_connect(_dbapi_connection, connection_record) -> None:
    connection_record.info["created_at"] = time.perf_counter()
    logger.debug("DB_POOL_CONNECT snapshot=%s", _pool_snapshot())


@event.listens_for(engine.sync_engine, "checkout")
def _on_checkout(_dbapi_connection, connection_record, _connection_proxy) -> None:
    connection_record.info["checked_out_at"] = time.perf_counter()
    snapshot = _pool_snapshot()
    if snapshot.get("checked_out") == settings.db_pool_size + settings.db_max_overflow:
        logger.warning("DB_POOL_AT_CAPACITY snapshot=%s", snapshot)


@event.listens_for(engine.sync_engine, "checkin")
def _on_checkin(_dbapi_connection, connection_record) -> None:
    started = connection_record.info.pop("checked_out_at", None)
    if started is None:
        return
    duration = time.perf_counter() - started
    record_db_connection_usage(duration * 1000)
    if duration >= settings.db_pool_slow_checkout_seconds:
        logger.warning(
            "DB_POOL_SLOW_USAGE duration_ms=%s snapshot=%s",
            round(duration * 1000, 2),
            _pool_snapshot(),
        )


@event.listens_for(engine.sync_engine, "before_cursor_execute")
def _before_cursor_execute(_conn, _cursor, _statement, _parameters, context, _executemany) -> None:
    context._onec_query_started_at = time.perf_counter()


@event.listens_for(engine.sync_engine, "after_cursor_execute")
def _after_cursor_execute(_conn, _cursor, statement, _parameters, context, _executemany) -> None:
    started = getattr(context, "_onec_query_started_at", None)
    if started is None:
        return
    duration_ms = (time.perf_counter() - started) * 1000
    record_db_query(duration_ms, statement)
    if duration_ms >= settings.db_slow_query_ms:
        logger.warning(
            "DB_SLOW_QUERY duration_ms=%s statement=%s",
            round(duration_ms, 2),
            " ".join(statement.split())[:500],
        )


def _find_pending_or_persistent(session: Session, model: type, pk_value, *, pk_attr: str = "id"):
    if pk_value is None:
        return None
    for candidate in session.new:
        if isinstance(candidate, model) and getattr(candidate, pk_attr, None) == pk_value:
            return candidate
    for candidate in session.identity_map.values():
        if isinstance(candidate, model) and getattr(candidate, pk_attr, None) == pk_value:
            return candidate
    return None


def _lookup_value(session: Session, model: type, pk_value, *, value_attr: str = "organisation_id", pk_attr: str = "id"):
    if pk_value is None:
        return None
    cached = _find_pending_or_persistent(session, model, pk_value, pk_attr=pk_attr)
    if cached is not None:
        return getattr(cached, value_attr, None)
    stmt = select(getattr(model, value_attr)).where(getattr(model, pk_attr) == pk_value)
    return session.execute(stmt).scalar_one_or_none()


def _lookup_org_id(session: Session, model: type, pk_value, *, pk_attr: str = "id"):
    return _lookup_value(session, model, pk_value, value_attr="organisation_id", pk_attr=pk_attr)


def _assert_org(label: str, actual_org_id: int | None, expected_org_id: int | None) -> int:
    if actual_org_id is None:
        raise ValueError(f"Tenant mismatch: {label} introuvable ou hors périmètre du tenant courant.")
    if expected_org_id is not None and actual_org_id != expected_org_id:
        raise ValueError(f"Tenant mismatch: {label} appartient à une autre organisation.")
    return actual_org_id


def _validate_tenant_relationships(session: Session, obj, tenant_id: int | None) -> None:
    expected_org_id = getattr(obj, "organisation_id", None) if hasattr(obj, "organisation_id") else None
    if expected_org_id is None and tenant_id is not None and hasattr(obj, "organisation_id"):
        setattr(obj, "organisation_id", tenant_id)
        expected_org_id = tenant_id
    if expected_org_id is None:
        expected_org_id = tenant_id

    if isinstance(obj, User):
        if obj.service_id is not None:
            _assert_org("service", _lookup_org_id(session, Service, obj.service_id), expected_org_id)
        return

    if isinstance(obj, BudgetExercice):
        return

    if isinstance(obj, BudgetPoste):
        _assert_org("exercice budgétaire", _lookup_org_id(session, BudgetExercice, obj.exercice_id), expected_org_id)
        if obj.parent_id is not None:
            _assert_org("poste budgétaire parent", _lookup_org_id(session, BudgetPoste, obj.parent_id), expected_org_id)
        return

    if isinstance(obj, DossierRequisition):
        return

    if isinstance(obj, Requisition):
        if obj.service_id is not None:
            _assert_org("service", _lookup_org_id(session, Service, obj.service_id), expected_org_id)
        if obj.dossier_id is not None:
            _assert_org("dossier de réquisition", _lookup_org_id(session, DossierRequisition, obj.dossier_id), expected_org_id)
        return

    if isinstance(obj, LigneRequisition):
        req_org_id = _assert_org("réquisition", _lookup_org_id(session, Requisition, obj.requisition_id), expected_org_id)
        if getattr(obj, "organisation_id", None) is None:
            obj.organisation_id = req_org_id
            expected_org_id = req_org_id
        if obj.budget_poste_id is not None:
            _assert_org("poste budgétaire", _lookup_org_id(session, BudgetPoste, obj.budget_poste_id), expected_org_id)
        return

    if isinstance(obj, RequisitionAnnexe):
        req_org_id = _assert_org("réquisition", _lookup_org_id(session, Requisition, obj.requisition_id), expected_org_id)
        if getattr(obj, "organisation_id", None) is None:
            obj.organisation_id = req_org_id
        return

    if isinstance(obj, RequisitionApprover):
        user_org_id = _assert_org("utilisateur approbateur", _lookup_org_id(session, User, obj.user_id), expected_org_id)
        if getattr(obj, "organisation_id", None) is None:
            obj.organisation_id = user_org_id
            expected_org_id = user_org_id
        if obj.added_by is not None:
            _assert_org("créateur de l'approbateur", _lookup_org_id(session, User, obj.added_by), expected_org_id)
        return

    if isinstance(obj, RequisitionStatusHistory):
        req_org_id = _assert_org("réquisition", _lookup_org_id(session, Requisition, obj.requisition_id), expected_org_id)
        if getattr(obj, "organisation_id", None) is None:
            obj.organisation_id = req_org_id
            expected_org_id = req_org_id
        if obj.changed_by is not None:
            _assert_org("auteur du changement de statut", _lookup_org_id(session, User, obj.changed_by), expected_org_id)
        return

    if isinstance(obj, Encaissement):
        if obj.source_proforma_id is not None:
            _assert_org("proforma source", _lookup_org_id(session, Encaissement, obj.source_proforma_id), expected_org_id)
        if obj.budget_poste_id is not None:
            _assert_org("poste budgétaire", _lookup_org_id(session, BudgetPoste, obj.budget_poste_id), expected_org_id)
        if obj.service_id is not None:
            _assert_org("service", _lookup_org_id(session, Service, obj.service_id), expected_org_id)
        if obj.compte_bancaire_id is not None:
            _assert_org("compte bancaire", _lookup_org_id(session, CompteBancaire, obj.compte_bancaire_id), expected_org_id)
        return

    if isinstance(obj, EncaissementArticle):
        enc_org_id = _assert_org("encaissement", _lookup_org_id(session, Encaissement, obj.encaissement_id), expected_org_id)
        if getattr(obj, "organisation_id", None) is None:
            obj.organisation_id = enc_org_id
        return

    if isinstance(obj, SortieFonds):
        if obj.requisition_id is not None:
            _assert_org("réquisition", _lookup_org_id(session, Requisition, obj.requisition_id), expected_org_id)
        if obj.budget_poste_id is not None:
            _assert_org("poste budgétaire", _lookup_org_id(session, BudgetPoste, obj.budget_poste_id), expected_org_id)
        if obj.service_id is not None:
            _assert_org("service", _lookup_org_id(session, Service, obj.service_id), expected_org_id)
        if obj.compte_bancaire_id is not None:
            _assert_org("compte bancaire", _lookup_org_id(session, CompteBancaire, obj.compte_bancaire_id), expected_org_id)
        return

    if isinstance(obj, CaisseCentrale | CompteBancaire | Banque | PrintSettings | SystemSettings | AuditLog | SystemEvent):
        return

    if isinstance(obj, BudgetAuditLog | PaymentHistory | PaymentTransaction | SaaSInvoice | Subscription | OrganisationSettings):
        return

    if isinstance(obj, Service):
        return

    if isinstance(obj, ServiceRubrique):
        service_org_id = _assert_org("service", _lookup_org_id(session, Service, obj.service_id), expected_org_id)
        _assert_org("poste budgétaire", _lookup_org_id(session, BudgetPoste, obj.budget_poste_id), service_org_id)
        return

    if isinstance(obj, CommissionMember):
        service_org_id = _assert_org("service", _lookup_org_id(session, Service, obj.service_id), expected_org_id)
        if obj.user_id is not None:
            _assert_org("utilisateur membre", _lookup_org_id(session, User, obj.user_id), service_org_id)
        if obj.function_id is not None:
            _assert_org("fonction de membre", _lookup_org_id(session, ServiceMemberFunction, obj.function_id), service_org_id)
        return

    if isinstance(obj, ServiceMemberFunction):
        _assert_org("service", _lookup_org_id(session, Service, obj.service_id), expected_org_id)
        return

    if isinstance(obj, DocumentSequence):
        if obj.service_id is not None:
            _assert_org("service", _lookup_org_id(session, Service, obj.service_id), obj.tenant_id)
        if tenant_id is not None and obj.tenant_id != tenant_id:
            raise ValueError("Tenant mismatch: la séquence documentaire appartient à une autre organisation.")
        return

    if isinstance(obj, PaymentLog | StandardClassification):
        return

    if isinstance(obj, RemboursementTransport):
        if obj.requisition_id is not None:
            req_org_id = _assert_org("réquisition", _lookup_org_id(session, Requisition, obj.requisition_id), expected_org_id)
            if getattr(obj, "organisation_id", None) is None:
                obj.organisation_id = req_org_id
                expected_org_id = req_org_id
        if obj.created_by is not None:
            _assert_org("créateur du remboursement", _lookup_org_id(session, User, obj.created_by), expected_org_id)
        return

    if isinstance(obj, ParticipantTransport):
        remb_org_id = _assert_org("remboursement transport", _lookup_org_id(session, RemboursementTransport, obj.remboursement_id), expected_org_id)
        if getattr(obj, "organisation_id", None) is None:
            obj.organisation_id = remb_org_id
        return

    if isinstance(obj, TransfertInterne):
        if obj.source_type == "BANQUE" and obj.source_id is not None:
            source_org_id = _assert_org("compte source", _lookup_org_id(session, CompteBancaire, obj.source_id), expected_org_id)
            if getattr(obj, "organisation_id", None) is None:
                obj.organisation_id = source_org_id
                expected_org_id = source_org_id
        if obj.destination_type == "BANQUE" and obj.destination_id is not None:
            destination_org_id = _assert_org("compte destination", _lookup_org_id(session, CompteBancaire, obj.destination_id), expected_org_id)
            if getattr(obj, "organisation_id", None) is None:
                obj.organisation_id = destination_org_id
                expected_org_id = destination_org_id
        if obj.execute_par is not None:
            _assert_org("utilisateur exécutant", _lookup_org_id(session, User, obj.execute_par), expected_org_id)
        return

    if isinstance(obj, HREmployee):
        if obj.service_id is not None:
            _assert_org("service RH", _lookup_value(session, HRService, obj.service_id, value_attr="tenant_id"), obj.tenant_id)
        if obj.fonction_id is not None:
            _assert_org("fonction RH", _lookup_value(session, HRFunction, obj.fonction_id, value_attr="tenant_id"), obj.tenant_id)
        return

    if isinstance(obj, HRContract | HRLeave | HRDocument | HRAttendance | HRAttendancePunch):
        employee_tenant_id = _assert_org("agent RH", _lookup_value(session, HREmployee, obj.employee_id, value_attr="tenant_id"), obj.tenant_id)
        if getattr(obj, "tenant_id", None) is None:
            obj.tenant_id = employee_tenant_id
        return

    if isinstance(obj, HRService | HRFunction | HRReference):
        return

    if isinstance(obj, HRAttendanceAgent | HRAttendanceAgentEnrollment | HRAttendanceAgentRelease | HRAttendanceDevice | HRAttendanceUnmappedPunch):
        return

    if isinstance(obj, HRAttendanceAgentCommand):
        _assert_org("agent de pointage RH", _lookup_value(session, HRAttendanceAgent, obj.agent_id, value_attr="tenant_id"), obj.tenant_id)
        if obj.device_id is not None:
            _assert_org("pointeuse RH", _lookup_value(session, HRAttendanceDevice, obj.device_id, value_attr="tenant_id"), obj.tenant_id)
        return

    if isinstance(obj, HRAttendanceDeviceEmployeeMapping):
        _assert_org("pointeuse RH", _lookup_value(session, HRAttendanceDevice, obj.device_id, value_attr="tenant_id"), obj.tenant_id)
        _assert_org("agent RH", _lookup_value(session, HREmployee, obj.employee_id, value_attr="tenant_id"), obj.tenant_id)
        return

    if isinstance(obj, SecretariatConversation):
        _assert_org("agent secrétariat", _lookup_org_id(session, SecretariatAgent, obj.agent_id), expected_org_id)
        if obj.user_id is not None:
            _assert_org("utilisateur secrétariat", _lookup_org_id(session, User, obj.user_id), expected_org_id)
        return

    if isinstance(obj, SecretariatMessage):
        conv_org_id = _assert_org(
            "conversation secrétariat",
            _lookup_org_id(session, SecretariatConversation, obj.conversation_id),
            expected_org_id,
        )
        if getattr(obj, "organisation_id", None) is None:
            obj.organisation_id = conv_org_id
        return

    if isinstance(obj, SecretariatTask):
        _assert_org("agent secrétariat", _lookup_org_id(session, SecretariatAgent, obj.agent_id), expected_org_id)
        if obj.user_id is not None:
            _assert_org("utilisateur secrétariat", _lookup_org_id(session, User, obj.user_id), expected_org_id)
        return

    if isinstance(obj, SecretariatMailDraft):
        if obj.user_id is not None:
            _assert_org("utilisateur brouillon secrétariat", _lookup_org_id(session, User, obj.user_id), expected_org_id)
        return

    if isinstance(obj, SecretariatDocument):
        _assert_org("créateur document secrétariat", _lookup_org_id(session, User, obj.created_by_user_id), expected_org_id)
        return

    if isinstance(obj, SecretariatDocumentVersion):
        _assert_org("document secrétariat", _lookup_org_id(session, SecretariatDocument, obj.document_id), expected_org_id)
        _assert_org("créateur version document", _lookup_org_id(session, User, obj.created_by_user_id), expected_org_id)
        if getattr(obj, "organisation_id", None) is None:
            doc_org = _lookup_org_id(session, SecretariatDocument, obj.document_id)
            if doc_org is not None:
                obj.organisation_id = doc_org
        return

    if isinstance(obj, SecretariatApproval):
        _assert_org("demandeur approbation secrétariat", _lookup_org_id(session, User, obj.requested_by_user_id), expected_org_id)
        if obj.approved_by_user_id is not None:
            _assert_org("approbateur secrétariat", _lookup_org_id(session, User, obj.approved_by_user_id), expected_org_id)
        return

    if isinstance(obj, SecretariatMeeting):
        _assert_org("créateur réunion secrétariat", _lookup_org_id(session, User, obj.created_by_user_id), expected_org_id)
        return

    if isinstance(obj, SecretariatAgendaItem):
        _assert_org("créateur agenda secrétariat", _lookup_org_id(session, User, obj.created_by_user_id), expected_org_id)
        if obj.assigned_to_user_id is not None:
            _assert_org("responsable agenda secrétariat", _lookup_org_id(session, User, obj.assigned_to_user_id), expected_org_id)
        return

    if isinstance(obj, SecretariatAgendaReminder):
        item_org_id = _assert_org("échéance agenda secrétariat", _lookup_org_id(session, SecretariatAgendaItem, obj.agenda_item_id), expected_org_id)
        if getattr(obj, "organisation_id", None) is None:
            obj.organisation_id = item_org_id
        return

    if isinstance(obj, SecretariatMeetingParticipant | SecretariatMeetingDecision | SecretariatMeetingActionItem):
        meeting_org_id = _assert_org("réunion secrétariat", _lookup_org_id(session, SecretariatMeeting, obj.meeting_id), expected_org_id)
        if getattr(obj, "organisation_id", None) is None:
            obj.organisation_id = meeting_org_id
        return

    if isinstance(obj, OAuthConnection | SecretariatAgent | SecretariatAuditLog):
        if getattr(obj, "user_id", None) is not None:
            _assert_org("utilisateur secrétariat", _lookup_org_id(session, User, obj.user_id), expected_org_id)
        return


@event.listens_for(Session, "do_orm_execute")
def _apply_tenant_criteria(execute_state) -> None:
    if execute_state.session.info.get("skip_tenant_scope"):
        return
    if not execute_state.is_select:
        return
    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        return
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(User, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(Requisition, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(DossierRequisition, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(LigneRequisition, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(RequisitionAnnexe, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(RequisitionApprover, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(RequisitionStatusHistory, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(Encaissement, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(EncaissementArticle, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(SortieFonds, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(CaisseCentrale, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(CompteBancaire, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(Banque, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(PrintSettings, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(SystemSettings, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(ClotureCaisse, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(RegularisationCaisse, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(AuditLog, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(SystemEvent, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(NotificationLog, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
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
        with_loader_criteria(ServiceRubrique, lambda cls: cls.service.has(Service.organisation_id == tenant_id), include_aliases=True),
        with_loader_criteria(CommissionMember, lambda cls: cls.service.has(Service.organisation_id == tenant_id), include_aliases=True),
        with_loader_criteria(ServiceMemberFunction, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(DocumentSequence, lambda cls: cls.tenant_id == tenant_id, include_aliases=True),
        with_loader_criteria(PaymentLog, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(StandardClassification, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(RemboursementTransport, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(ParticipantTransport, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(TransfertInterne, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(HRService, lambda cls: cls.tenant_id == tenant_id, include_aliases=True),
        with_loader_criteria(HRFunction, lambda cls: cls.tenant_id == tenant_id, include_aliases=True),
        with_loader_criteria(HRReference, lambda cls: cls.tenant_id == tenant_id, include_aliases=True),
        with_loader_criteria(HREmployee, lambda cls: cls.tenant_id == tenant_id, include_aliases=True),
        with_loader_criteria(HRContract, lambda cls: cls.tenant_id == tenant_id, include_aliases=True),
        with_loader_criteria(HRLeave, lambda cls: cls.tenant_id == tenant_id, include_aliases=True),
        with_loader_criteria(HRDocument, lambda cls: cls.tenant_id == tenant_id, include_aliases=True),
        with_loader_criteria(SecretariatAgent, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(SecretariatConversation, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(SecretariatMessage, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(SecretariatTask, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(OAuthConnection, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(SecretariatAuditLog, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(SecretariatMailDraft, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(SecretariatDocument, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(SecretariatDocumentVersion, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(SecretariatApproval, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(SecretariatAgendaItem, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(SecretariatAgendaReminder, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(SecretariatMeeting, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(SecretariatMeetingParticipant, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(SecretariatMeetingDecision, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(SecretariatMeetingActionItem, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        # ── Module Comptabilité ──────────────────────────────────────────────
        # ⚠️ Toute nouvelle table compta_* DOIT être ajoutée ici, sinon ses
        # SELECT ne sont pas filtrés par organisation (fuite inter-tenant).
        with_loader_criteria(ComptaSociete, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(ComptaEtablissement, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(ComptaReferentiel, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(ComptaCompte, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(ComptaJournal, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(ComptaExercice, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(ComptaPeriode, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(ComptaTauxChange, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(ComptaSequence, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(ComptaMappingPosteBudgetaire, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(ComptaMappingCompteBancaire, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(ComptaMappingRubrique, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(ComptaPosteEtat, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(ComptaPosteEtatCompte, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(ComptaEcriture, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(ComptaLigneEcriture, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
    )


@event.listens_for(Session, "before_flush")
def _apply_tenant_to_new_objects(session, flush_context, instances) -> None:
    if session.info.get("skip_tenant_scope"):
        return
    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        objects = list(session.new) + list(session.dirty)
        for obj in objects:
            _validate_tenant_relationships(session, obj, tenant_id)
        return
    objects = list(session.new) + list(session.dirty)
    for obj in objects:
        if hasattr(obj, "organisation_id"):
            current_org = getattr(obj, "organisation_id", None)
            if current_org is None:
                setattr(obj, "organisation_id", tenant_id)
            elif current_org != tenant_id:
                raise ValueError("Tenant mismatch: organisation_id ne correspond pas au contexte courant.")
        if hasattr(obj, "tenant_id"):
            current_tenant = getattr(obj, "tenant_id", None)
            if current_tenant is None:
                setattr(obj, "tenant_id", tenant_id)
            elif current_tenant != tenant_id:
                raise ValueError("Tenant mismatch: tenant_id ne correspond pas au contexte courant.")
        _validate_tenant_relationships(session, obj, tenant_id)


async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
