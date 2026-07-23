from __future__ import annotations

import uuid
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime, timezone

from app.api.deps import get_current_tenant_id, get_current_user, has_permission
from app.db.session import get_db
from app.models.budget import BudgetPoste
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.encaissement import Encaissement
from app.models.payment_history import PaymentHistory
from app.models.user import User
from app.schemas.payment import PaymentHistoryCreate, PaymentHistoryResponse
from app.services.client_receipt_email import schedule_client_payment_email

router = APIRouter(dependencies=[Depends(has_permission("encaissements"))])


def _clean_money(value: Decimal | str | int | float | None) -> Decimal:
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


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
    background_tasks: BackgroundTasks,
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Ajoute un nouveau paiement à un encaissement."""
    enc_uid = payload.encaissement_id

    # Vérifier que l'encaissement existe
    result = await db.execute(
        select(Encaissement)
        .where(
            Encaissement.id == enc_uid,
            Encaissement.organisation_id == tenant_id,
        )
        .with_for_update()
    )
    encaissement = result.scalar_one_or_none()

    if not encaissement:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encaissement non trouvé")
    if encaissement.est_proforma:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Paiement indisponible pour une proforma")
    if str(getattr(encaissement, "statut_operation", "ACTIVE") or "ACTIVE").upper() == "ANNULEE":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Paiement impossible sur un encaissement annulé")

    # Vérifier que le montant ne dépasse pas le restant dû
    montant_restant = _clean_money(encaissement.montant_total - encaissement.montant_paye)
    payload_montant = _clean_money(payload.montant)
    # Tolérance pour éviter les rejets dus aux arrondis (ex: 0.03)
    epsilon = Decimal("0.01")
    if payload_montant - montant_restant > epsilon:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Montant trop élevé. Restant dû: {montant_restant}"
        )

    # Créer le paiement
    payment = PaymentHistory(
        organisation_id=tenant_id,
        encaissement_id=enc_uid,
        montant=payload_montant,
        mode_paiement=payload.mode_paiement,
        reference=payload.reference,
        notes=payload.notes,
        created_by=user.id,
    )
    db.add(payment)

    # Mettre à jour l'encaissement
    new_montant_paye = _clean_money(encaissement.montant_paye + payload_montant)
    encaissement.montant_paye = new_montant_paye

    if encaissement.budget_poste_id:
        res = await db.execute(
            select(BudgetPoste)
            .where(
                BudgetPoste.id == encaissement.budget_poste_id,
                BudgetPoste.organisation_id == tenant_id,
            )
            .with_for_update()
        )
        budget_line = res.scalar_one_or_none()
        if budget_line is not None:
            budget_line.montant_paye = _clean_money((budget_line.montant_paye or 0) + payload_montant)

    # Déterminer le nouveau statut
    if new_montant_paye >= encaissement.montant_total:
        encaissement.statut_paiement = "complet"
    elif new_montant_paye > 0:
        encaissement.statut_paiement = "partiel"
    else:
        encaissement.statut_paiement = "non_paye"

    # Créditer la trésorerie : l'argent du complément entre réellement en
    # caisse ou en banque (même canal que l'encaissement d'origine).
    canal = (encaissement.canal or "CAISSE").upper()
    devise = (encaissement.devise_perception or "USD").upper()
    if canal == "CAISSE":
        await db.execute(
            pg_insert(CaisseCentrale)
            .values(organisation_id=tenant_id, solde_usd=0, solde_cdf=0)
            .on_conflict_do_nothing(index_elements=["organisation_id"])
        )
        caisse_res = await db.execute(
            select(CaisseCentrale)
            .where(CaisseCentrale.organisation_id == tenant_id)
            .limit(1)
            .with_for_update()
        )
        caisse = caisse_res.scalar_one_or_none()
        if caisse is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Caisse centrale indisponible")
        if not caisse.est_ouverte:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Caisse fermée : ouvrez la caisse avant d'encaisser le complément.",
            )
        if devise == "USD":
            caisse.solde_usd = (caisse.solde_usd or 0) + payload_montant
        else:
            caisse.solde_cdf = (caisse.solde_cdf or 0) + payload_montant
        caisse.derniere_maj = datetime.now(timezone.utc)
    elif encaissement.compte_bancaire_id is not None:
        compte_res = await db.execute(
            select(CompteBancaire)
            .where(
                CompteBancaire.id == encaissement.compte_bancaire_id,
                CompteBancaire.organisation_id == tenant_id,
            )
            .with_for_update()
        )
        compte = compte_res.scalar_one_or_none()
        if compte is not None:
            compte.solde_actuel = (compte.solde_actuel or 0) + payload_montant

    await db.commit()
    await db.refresh(payment)
    await db.refresh(encaissement)

    # Reçu par email au client : montant payé cumulé et reste à payer.
    await schedule_client_payment_email(
        db, background_tasks, encaissement, encaissement.organisation_id
    )

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
