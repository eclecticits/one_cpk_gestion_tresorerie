from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, has_permission
from app.db.session import get_db
from app.models.encaissement import Encaissement
from app.models.payment_history import PaymentHistory
from app.models.user import User
from app.schemas.payment import PaymentHistoryCancelPayload, PaymentHistoryCreate, PaymentHistoryResponse
from app.services.client_receipt_email import schedule_client_payment_email
from app.services.audit_service import get_request_ip
from app.services.encaissement_payments import cancel_encaissement_payment, record_encaissement_payment

router = APIRouter(dependencies=[Depends(has_permission("encaissements"))])


def _payment_to_response(payment: PaymentHistory) -> dict:
    """Convertit un modèle PaymentHistory en dict pour la réponse."""
    return {
        "id": str(payment.id),
        "encaissement_id": str(payment.encaissement_id),
        "montant": payment.montant,
        "devise": payment.devise,
        "canal": payment.canal,
        "compte_bancaire_id": payment.compte_bancaire_id,
        "budget_poste_id": payment.budget_poste_id,
        "taux_change_applique": payment.taux_change_applique,
        "date_paiement": payment.date_paiement,
        "statut": payment.statut,
        "statut_comptabilisation": payment.statut_comptabilisation,
        "message_comptabilisation": payment.message_comptabilisation,
        "mode_paiement": payment.mode_paiement,
        "reference": payment.reference,
        "notes": payment.notes,
        "created_by": str(payment.created_by) if payment.created_by else None,
        "created_at": payment.created_at,
        "annule_le": payment.annule_le,
        "annule_par_id": str(payment.annule_par_id) if payment.annule_par_id else None,
        "motif_annulation": payment.motif_annulation,
        "annulation_ip": payment.annulation_ip,
    }


@router.get("", response_model=list[PaymentHistoryResponse])
async def list_payments(
    encaissement_id: str = Query(..., description="ID de l'encaissement"),
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Liste l'historique des paiements pour un encaissement."""
    try:
        enc_uid = uuid.UUID(encaissement_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid encaissement_id UUID")

    encaissement_exists = await db.execute(
        select(Encaissement.id).where(
            Encaissement.id == enc_uid,
            Encaissement.organisation_id == tenant_id,
        )
    )
    if encaissement_exists.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encaissement non trouvé")

    result = await db.execute(
        select(PaymentHistory)
        .where(
            PaymentHistory.encaissement_id == enc_uid,
            PaymentHistory.organisation_id == tenant_id,
        )
        .order_by(PaymentHistory.created_at.desc())
    )
    payments = result.scalars().all()

    return [_payment_to_response(p) for p in payments]


@router.post("", response_model=PaymentHistoryResponse, status_code=status.HTTP_201_CREATED)
async def create_payment(
    payload: PaymentHistoryCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Ajoute un nouveau paiement à un encaissement."""
    payment = await record_encaissement_payment(
        db,
        organisation_id=tenant_id,
        encaissement_id=payload.encaissement_id,
        montant=payload.montant,
        mode_paiement=payload.mode_paiement,
        reference=payload.reference,
        notes=payload.notes,
        user_id=user.id,
        ip_address=get_request_ip(request),
    )

    await db.commit()
    await db.refresh(payment)
    encaissement = await db.get(Encaissement, payload.encaissement_id)

    # Note de débit par email au client : montant payé cumulé et reste à payer.
    if encaissement is not None:
        await schedule_client_payment_email(
            db, background_tasks, encaissement, encaissement.organisation_id
        )

    return _payment_to_response(payment)


@router.post("/{payment_id}/cancel", response_model=PaymentHistoryResponse)
async def cancel_payment(
    payment_id: str,
    payload: PaymentHistoryCancelPayload,
    request: Request,
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        uid = uuid.UUID(payment_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID")

    payment = await cancel_encaissement_payment(
        db,
        organisation_id=tenant_id,
        payment_id=uid,
        motif_annulation=payload.motif_annulation.strip(),
        user_id=user.id,
        ip_address=get_request_ip(request),
    )
    await db.commit()
    await db.refresh(payment)
    return _payment_to_response(payment)


@router.get("/{payment_id}", response_model=PaymentHistoryResponse)
async def get_payment(
    payment_id: str,
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Récupère un paiement par son ID."""
    try:
        uid = uuid.UUID(payment_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID")

    result = await db.execute(
        select(PaymentHistory).where(
            PaymentHistory.id == uid,
            PaymentHistory.organisation_id == tenant_id,
        )
    )
    payment = result.scalar_one_or_none()

    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paiement non trouvé")

    return _payment_to_response(payment)
