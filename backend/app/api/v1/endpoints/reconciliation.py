from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user
from app.models.encaissement import Encaissement
from app.models.sortie_fonds import SortieFonds
from app.models.user import User
from app.schemas.reconciliation import (
    ReconcileBatchRequest,
    ReconcileBatchResponse,
    ReconcilePatch,
    ReconcileResult,
)
from app.services.audit_service import log_action
from app.db.session import get_db


router = APIRouter()


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="transaction_id invalide") from exc


async def _load_transaction(
    *,
    db: AsyncSession,
    transaction_type: str,
    transaction_id: uuid.UUID,
    tenant_id: int,
):
    transaction_type = transaction_type.lower()
    if transaction_type == "encaissement":
        stmt = select(Encaissement).where(
            Encaissement.id == transaction_id,
            Encaissement.organisation_id == tenant_id,
            Encaissement.is_deleted.is_(False),
        )
        res = await db.execute(stmt)
        return transaction_type, res.scalar_one_or_none()
    if transaction_type == "sortie":
        stmt = select(SortieFonds).where(
            SortieFonds.id == transaction_id,
            SortieFonds.organisation_id == tenant_id,
        )
        res = await db.execute(stmt)
        return transaction_type, res.scalar_one_or_none()
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="transaction_type invalide")


def _apply_reconcile(
    *,
    transaction: Encaissement | SortieFonds,
    is_reconciled: bool,
    bank_statement_ref: str | None,
    user_id: uuid.UUID | None,
):
    if is_reconciled:
        transaction.is_reconciled = True
        transaction.reconciled_at = datetime.now(timezone.utc)
        transaction.reconciled_by_id = user_id
        transaction.bank_statement_ref = bank_statement_ref
    else:
        transaction.is_reconciled = False
        transaction.reconciled_at = None
        transaction.reconciled_by_id = None
        transaction.bank_statement_ref = None


@router.patch("/{transaction_type}/{transaction_id}", response_model=ReconcileResult)
async def reconcile_transaction(
    transaction_type: str,
    transaction_id: str,
    payload: ReconcilePatch,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
) -> ReconcileResult:
    txn_uuid = _parse_uuid(transaction_id)
    tx_type, transaction = await _load_transaction(
        db=db,
        transaction_type=transaction_type,
        transaction_id=txn_uuid,
        tenant_id=tenant_id,
    )
    if transaction is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction non trouvée")

    _apply_reconcile(
        transaction=transaction,
        is_reconciled=payload.is_reconciled,
        bank_statement_ref=payload.bank_statement_ref,
        user_id=user.id if user else None,
    )

    await log_action(
        db,
        user_id=user.id if user else None,
        action=("RECONCILE" if payload.is_reconciled else "UNRECONCILE"),
        target_table="encaissements" if tx_type == "encaissement" else "sorties_fonds",
        target_id=str(transaction.id),
        old_value=None,
        new_value={"is_reconciled": payload.is_reconciled, "bank_statement_ref": payload.bank_statement_ref},
    )
    await db.commit()

    return ReconcileResult(
        transaction_type=tx_type,
        transaction_id=str(transaction.id),
        is_reconciled=transaction.is_reconciled,
        reconciled_at=transaction.reconciled_at,
        reconciled_by_id=str(transaction.reconciled_by_id) if transaction.reconciled_by_id else None,
        bank_statement_ref=transaction.bank_statement_ref,
    )


@router.post("/batch", response_model=ReconcileBatchResponse)
async def reconcile_batch(
    payload: ReconcileBatchRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
) -> ReconcileBatchResponse:
    results: list[ReconcileResult] = []

    for item in payload.items:
        txn_uuid = _parse_uuid(item.transaction_id)
        tx_type, transaction = await _load_transaction(
            db=db,
            transaction_type=item.transaction_type,
            transaction_id=txn_uuid,
            tenant_id=tenant_id,
        )
        if transaction is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction non trouvée")

        _apply_reconcile(
            transaction=transaction,
            is_reconciled=item.is_reconciled,
            bank_statement_ref=item.bank_statement_ref,
            user_id=user.id if user else None,
        )

        await log_action(
            db,
            user_id=user.id if user else None,
            action=("RECONCILE" if item.is_reconciled else "UNRECONCILE"),
            target_table="encaissements" if tx_type == "encaissement" else "sorties_fonds",
            target_id=str(transaction.id),
            old_value=None,
            new_value={"is_reconciled": item.is_reconciled, "bank_statement_ref": item.bank_statement_ref},
        )

        results.append(
            ReconcileResult(
                transaction_type=tx_type,
                transaction_id=str(transaction.id),
                is_reconciled=transaction.is_reconciled,
                reconciled_at=transaction.reconciled_at,
                reconciled_by_id=str(transaction.reconciled_by_id) if transaction.reconciled_by_id else None,
                bank_statement_ref=transaction.bank_statement_ref,
            )
        )

    await db.commit()

    return ReconcileBatchResponse(updated=len(results), items=results)
