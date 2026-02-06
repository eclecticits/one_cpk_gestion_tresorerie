from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.budget import BudgetLigne
from app.models.encaissement import Encaissement
from app.models.payment_history import PaymentHistory
from app.models.user import User
from app.schemas.payment import PaymentHistoryCreate, PaymentHistoryResponse

router = APIRouter()


def _payment_to_response(payment: PaymentHistory) -> dict:
    """Convertit un modèle PaymentHistory en dict pour la réponse."""
    return {
        "id": str(payment.id),
        "encaissement_id": str(payment.encaissement_id),
        "montant": payment.montant,
        "mode_paiement": payment.mode_paiement,
        "reference": payment.reference,
        "notes": payment.notes,
        "created_by": str(payment.created_by) if payment.created_by else None,
        "created_at": payment.created_at,
    }


@router.get("", response_model=list[PaymentHistoryResponse])
async def list_payments(
    encaissement_id: str = Query(..., description="ID de l'encaissement"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Liste l'historique des paiements pour un encaissement."""
    try:
        enc_uid = uuid.UUID(encaissement_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid encaissement_id UUID")

    result = await db.execute(
        select(PaymentHistory)
        .where(PaymentHistory.encaissement_id == enc_uid)
        .order_by(PaymentHistory.created_at.desc())
    )
    payments = result.scalars().all()

    return [_payment_to_response(p) for p in payments]


@router.post("", response_model=PaymentHistoryResponse, status_code=status.HTTP_201_CREATED)
async def create_payment(
    payload: PaymentHistoryCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Ajoute un nouveau paiement à un encaissement."""
    try:
        enc_uid = uuid.UUID(payload.encaissement_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid encaissement_id UUID")

    # Vérifier que l'encaissement existe
    result = await db.execute(select(Encaissement).where(Encaissement.id == enc_uid))
    encaissement = result.scalar_one_or_none()

    if not encaissement:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encaissement non trouvé")

    # Vérifier que le montant ne dépasse pas le restant dû
    montant_restant = encaissement.montant_total - encaissement.montant_paye
    if payload.montant > montant_restant:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Montant trop élevé. Restant dû: {montant_restant}"
        )

    # Créer le paiement
    payment = PaymentHistory(
        encaissement_id=enc_uid,
        montant=payload.montant,
        mode_paiement=payload.mode_paiement,
        reference=payload.reference,
        notes=payload.notes,
        created_by=user.id,
    )
    db.add(payment)

    # Mettre à jour l'encaissement
    new_montant_paye = encaissement.montant_paye + payload.montant
    encaissement.montant_paye = new_montant_paye

    if encaissement.budget_ligne_id:
        res = await db.execute(select(BudgetLigne).where(BudgetLigne.id == encaissement.budget_ligne_id))
        budget_line = res.scalar_one_or_none()
        if budget_line is not None:
            budget_line.montant_paye = (budget_line.montant_paye or 0) + payload.montant

    # Déterminer le nouveau statut
    if new_montant_paye >= encaissement.montant_total:
        encaissement.statut_paiement = "complet"
    elif new_montant_paye > 0:
        encaissement.statut_paiement = "partiel"
    else:
        encaissement.statut_paiement = "non_paye"

    await db.commit()
    await db.refresh(payment)

    return _payment_to_response(payment)


@router.get("/{payment_id}", response_model=PaymentHistoryResponse)
async def get_payment(
    payment_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Récupère un paiement par son ID."""
    try:
        uid = uuid.UUID(payment_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID")

    result = await db.execute(select(PaymentHistory).where(PaymentHistory.id == uid))
    payment = result.scalar_one_or_none()

    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paiement non trouvé")

    return _payment_to_response(payment)
