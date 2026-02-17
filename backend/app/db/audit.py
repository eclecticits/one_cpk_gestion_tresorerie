from __future__ import annotations

from decimal import Decimal
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.core.audit_context import get_audit_user_id
from app.models.audit_log import AuditLog
from app.models.requisition import Requisition
from app.models.encaissement import Encaissement
from app.models.budget import BudgetPoste


def _to_jsonable(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    return value


def _add_log(session: Session, *, entity_type: str, entity_id: str, action: str, field_name: str | None, old, new) -> None:
    user_id = get_audit_user_id()
    session.add(
        AuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            field_name=field_name,
            old_value=_to_jsonable(old),
            new_value=_to_jsonable(new),
            user_id=None if user_id is None else user_id,
        )
    )


@event.listens_for(Session, "after_flush")
def audit_after_flush(session: Session, _flush_context) -> None:
    user_id = get_audit_user_id()
    if not user_id:
        return

    for obj in session.dirty:
        if isinstance(obj, Requisition):
            insp = inspect(obj)
            if insp.attrs.status.history.has_changes():
                hist = insp.attrs.status.history
                _add_log(
                    session,
                    entity_type="requisition",
                    entity_id=str(obj.id),
                    action="status_change",
                    field_name="status",
                    old=hist.deleted[0] if hist.deleted else None,
                    new=hist.added[0] if hist.added else None,
                )
            if getattr(obj, "is_deleted", False) and insp.attrs.is_deleted.history.has_changes():
                _add_log(
                    session,
                    entity_type="requisition",
                    entity_id=str(obj.id),
                    action="soft_delete",
                    field_name="is_deleted",
                    old=False,
                    new=True,
                )
        elif isinstance(obj, Encaissement):
            insp = inspect(obj)
            if insp.attrs.statut_paiement.history.has_changes():
                hist = insp.attrs.statut_paiement.history
                _add_log(
                    session,
                    entity_type="encaissement",
                    entity_id=str(obj.id),
                    action="status_change",
                    field_name="statut_paiement",
                    old=hist.deleted[0] if hist.deleted else None,
                    new=hist.added[0] if hist.added else None,
                )
            if getattr(obj, "is_deleted", False) and insp.attrs.is_deleted.history.has_changes():
                _add_log(
                    session,
                    entity_type="encaissement",
                    entity_id=str(obj.id),
                    action="soft_delete",
                    field_name="is_deleted",
                    old=False,
                    new=True,
                )
        elif isinstance(obj, BudgetPoste):
            insp = inspect(obj)
            if insp.attrs.montant_prevu.history.has_changes():
                hist = insp.attrs.montant_prevu.history
                _add_log(
                    session,
                    entity_type="budget_ligne",
                    entity_id=str(obj.id),
                    action="update",
                    field_name="montant_prevu",
                    old=hist.deleted[0] if hist.deleted else None,
                    new=hist.added[0] if hist.added else None,
                )
            if getattr(obj, "is_deleted", False) and insp.attrs.is_deleted.history.has_changes():
                _add_log(
                    session,
                    entity_type="budget_ligne",
                    entity_id=str(obj.id),
                    action="soft_delete",
                    field_name="is_deleted",
                    old=False,
                    new=True,
                )
