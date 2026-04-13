from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.encaissement import Encaissement
from app.models.payment_transaction import PaymentTransaction
from app.models.compte_bancaire import CompteBancaire
from app.services.payments.registry import get_provider
from app.schemas.online_payments import (
    OnlinePaymentInitRequest,
    OnlinePaymentInitResponse,
    OnlinePaymentStatusResponse,
)

router = APIRouter()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/initiate", response_model=OnlinePaymentInitResponse)
async def initiate_payment(
    payload: OnlinePaymentInitRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OnlinePaymentInitResponse:
    provider = get_provider(payload.provider)

    if payload.currency not in {"USD", "CDF"}:
        raise HTTPException(status_code=400, detail="Devise invalide")

    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Montant invalide")

    result = await provider.initiate_payment(
        amount=float(payload.amount),
        currency=payload.currency,
        reference=payload.reference,
        method=payload.method,
        phone=payload.phone,
        description=payload.description,
    )

    tx = PaymentTransaction(
        organisation_id=user.organisation_id,
        provider=provider.name,
        provider_ref=result.provider_ref,
        reference=payload.reference,
        amount=Decimal(payload.amount),
        currency=payload.currency,
        fees=Decimal("0"),
        status="PENDING",
        method=payload.method,
        phone=payload.phone,
        raw_payload=result.raw,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db.add(tx)
    await db.commit()

    return OnlinePaymentInitResponse(
        provider=provider.name,
        provider_ref=result.provider_ref,
        checkout_url=result.checkout_url,
        status="PENDING",
    )


@router.post("/webhook/{provider_name}")
async def payment_webhook(
    provider_name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    provider = get_provider(provider_name)
    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    if not provider.verify_webhook(body=body, headers=headers):
        raise HTTPException(status_code=401, detail="Signature invalide")

    event = provider.parse_event(body=body, headers=headers)
    if not event.provider_ref:
        raise HTTPException(status_code=400, detail="provider_ref manquant")

    res = await db.execute(
        select(PaymentTransaction).where(PaymentTransaction.provider_ref == event.provider_ref)
    )
    tx = res.scalar_one_or_none()
    if not tx:
        org_id = None
        enc_org_res = await db.execute(
            select(Encaissement.organisation_id).where(Encaissement.reference == event.provider_ref)
        )
        org_id = enc_org_res.scalar_one_or_none()
        if org_id is None and settings.online_payments_compte_bancaire_id:
            compte_res = await db.execute(
                select(CompteBancaire.organisation_id).where(
                    CompteBancaire.id == settings.online_payments_compte_bancaire_id
                )
            )
            org_id = compte_res.scalar_one_or_none()
        if org_id is None:
            raise HTTPException(status_code=400, detail="Organisation introuvable pour la transaction")

        tx = PaymentTransaction(
            organisation_id=org_id,
            provider=provider.name,
            provider_ref=event.provider_ref,
            reference=event.reference,
            amount=Decimal(event.amount),
            currency=event.currency,
            fees=Decimal(event.fees),
            status="PENDING",
            method=event.method,
            phone=event.phone,
            raw_payload=event.raw,
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        db.add(tx)

    tx.status = event.status
    tx.amount = Decimal(event.amount)
    tx.currency = event.currency
    tx.fees = Decimal(event.fees)
    tx.method = event.method
    tx.raw_payload = event.raw
    tx.updated_at = _utcnow()

    if event.status == "SUCCESS" and not tx.encaissement_id:
        existing_enc = None
        enc_res = await db.execute(select(Encaissement).where(Encaissement.reference == event.provider_ref))
        existing_enc = enc_res.scalar_one_or_none()
        if existing_enc:
            tx.encaissement_id = existing_enc.id
            if tx.organisation_id is None:
                tx.organisation_id = existing_enc.organisation_id
            await db.commit()
            return {"status": "ACK"}

        compte_id = settings.online_payments_compte_bancaire_id
        compte = None
        if compte_id:
            res = await db.execute(select(CompteBancaire).where(CompteBancaire.id == compte_id))
            compte = res.scalar_one_or_none()

        if not compte:
            raise HTTPException(status_code=400, detail="Compte bancaire de règlement non configuré")

        if not compte.organisation_id:
            raise HTTPException(status_code=400, detail="Organisation du compte bancaire manquante")

        enc = Encaissement(
            numero_recu=f"ONL-{event.provider_ref}",
            numero_proforma=None,
            est_proforma=False,
            source_proforma_id=None,
            organisation_id=compte.organisation_id,
            type_client="autre",
            client_nom="Paiement en ligne",
            libelle=f"Paiement en ligne {event.method}",
            description=event.reference,
            montant=Decimal(event.amount),
            montant_total=Decimal(event.amount),
            montant_paye=Decimal(event.amount),
            montant_percu=Decimal(event.amount),
            devise_perception=event.currency,
            taux_change_applique=Decimal("1"),
            canal="BANQUE",
            compte_bancaire_id=compte.id,
            statut_paiement="complet",
            mode_paiement="card" if event.method == "VISA" else "mobile_money",
            reference=event.provider_ref,
            date_encaissement=_utcnow(),
            date_paiement=_utcnow(),
            created_by=None,
        )
        db.add(enc)
        tx.encaissement_id = enc.id
        if tx.organisation_id is None:
            tx.organisation_id = compte.organisation_id

        compte.solde_actuel = (compte.solde_actuel or 0) + Decimal(event.amount)

    await db.commit()
    return {"status": "ACK"}


@router.get("/status/{provider_ref}", response_model=OnlinePaymentStatusResponse)
async def payment_status(
    provider_ref: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OnlinePaymentStatusResponse:
    res = await db.execute(select(PaymentTransaction).where(PaymentTransaction.provider_ref == provider_ref))
    tx = res.scalar_one_or_none()
    if not tx:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction introuvable")
    return OnlinePaymentStatusResponse(
        provider_ref=tx.provider_ref,
        status=tx.status,
        amount=tx.amount,
        currency=tx.currency,
        fees=tx.fees,
        method=tx.method,
    )
