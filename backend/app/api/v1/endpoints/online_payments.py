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
from app.models.organisation import Organisation
from app.modules.comptabilite.models import RUBRIQUE_PRODUIT_PAIEMENT_EN_LIGNE
from app.modules.comptabilite.services.generation_service import (
    est_comptabilite_activee,
    generer_ecriture_encaissement,
)
from app.services.document_sequences import generate_document_number
from app.services.payments.registry import get_provider
from app.schemas.online_payments import (
    OnlinePaymentInitRequest,
    OnlinePaymentInitResponse,
    OnlinePaymentStatusResponse,
)

router = APIRouter()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _tenant_payment_config(org: Organisation) -> dict:
    raw = org.billing_config or {}
    tenant_payments = raw.get("tenant_payments") or raw.get("public_payments") or {}
    if not isinstance(tenant_payments, dict):
        return {}
    provider_config = tenant_payments.get("epaielink") or {}
    if not isinstance(provider_config, dict):
        return {}
    return provider_config


def _merchant_account_ref(config: dict) -> str | None:
    return (
        config.get("site_id")
        or config.get("merchant_site_id")
        or config.get("merchant_account")
        or config.get("merchant_number")
    )


async def _resolve_tenant_settlement_account(
    db: AsyncSession,
    *,
    organisation_id: int,
    config: dict,
) -> CompteBancaire:
    configured_id = config.get("settlement_compte_bancaire_id") or config.get("compte_bancaire_id")
    if configured_id:
        res = await db.execute(
            select(CompteBancaire).where(
                CompteBancaire.id == int(configured_id),
                CompteBancaire.organisation_id == organisation_id,
                CompteBancaire.is_active.is_(True),
            )
        )
        compte = res.scalar_one_or_none()
        if compte:
            return compte
        raise HTTPException(status_code=400, detail="Compte bancaire tenant invalide pour ce paiement")

    if settings.online_payments_compte_bancaire_id:
        res = await db.execute(
            select(CompteBancaire).where(
                CompteBancaire.id == settings.online_payments_compte_bancaire_id,
                CompteBancaire.organisation_id == organisation_id,
                CompteBancaire.is_active.is_(True),
            )
        )
        compte = res.scalar_one_or_none()
        if compte:
            return compte

    res = await db.execute(
        select(CompteBancaire)
        .where(
            CompteBancaire.organisation_id == organisation_id,
            CompteBancaire.is_active.is_(True),
            CompteBancaire.account_type == "BANK",
        )
        .order_by(CompteBancaire.id.asc())
    )
    compte = res.scalars().first()
    if not compte:
        raise HTTPException(status_code=400, detail="Compte bancaire tenant non configuré")
    return compte


@router.post("/initiate", response_model=OnlinePaymentInitResponse)
async def initiate_payment(
    payload: OnlinePaymentInitRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OnlinePaymentInitResponse:
    provider = get_provider(payload.provider)
    org_res = await db.execute(select(Organisation).where(Organisation.id == user.organisation_id))
    org = org_res.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organisation introuvable")
    merchant_config = _tenant_payment_config(org)
    merchant_ref = _merchant_account_ref(merchant_config)
    if not merchant_ref:
        raise HTTPException(status_code=400, detail="Compte marchand tenant non configuré")

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
        merchant_config=merchant_config,
    )

    tx = PaymentTransaction(
        organisation_id=user.organisation_id,
        provider=provider.name,
        provider_ref=result.provider_ref,
        reference=payload.reference,
        flow="TENANT_BUSINESS",
        beneficiary_type="TENANT",
        beneficiary_organisation_id=user.organisation_id,
        merchant_account_ref=str(merchant_ref),
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
        select(PaymentTransaction)
        .where(PaymentTransaction.provider_ref == event.provider_ref)
        .with_for_update()
    )
    tx = res.scalar_one_or_none()
    if not tx:
        org_id = None
        enc_org_res = await db.execute(
            select(Encaissement.organisation_id).where(Encaissement.reference == event.provider_ref)
        )
        org_id = enc_org_res.scalar_one_or_none()
        if org_id is None:
            raise HTTPException(status_code=400, detail="Organisation introuvable pour la transaction")

        tx = PaymentTransaction(
            organisation_id=org_id,
            provider=provider.name,
            provider_ref=event.provider_ref,
            reference=event.reference,
            flow="TENANT_BUSINESS",
            beneficiary_type="TENANT",
            beneficiary_organisation_id=org_id,
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

    if tx.status == "SUCCESS" and tx.encaissement_id:
        tx.raw_payload = event.raw
        tx.updated_at = _utcnow()
        await db.commit()
        return {"status": "ACK"}

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

        org_res = await db.execute(select(Organisation).where(Organisation.id == tx.organisation_id))
        org = org_res.scalar_one_or_none()
        if org is None:
            raise HTTPException(status_code=400, detail="Organisation tenant introuvable")
        merchant_config = _tenant_payment_config(org)
        tx.merchant_account_ref = tx.merchant_account_ref or _merchant_account_ref(merchant_config)
        compte = await _resolve_tenant_settlement_account(
            db,
            organisation_id=tx.organisation_id,
            config=merchant_config,
        )
        compte_res = await db.execute(
            select(CompteBancaire)
            .where(
                CompteBancaire.id == compte.id,
                CompteBancaire.organisation_id == tx.organisation_id,
            )
            .with_for_update()
        )
        compte = compte_res.scalar_one_or_none()
        if compte is None:
            raise HTTPException(status_code=400, detail="Compte bancaire tenant introuvable")

        enc = Encaissement(
            numero_recu=await generate_document_number(
                db,
                doc_type="ND",
                tenant_id=compte.organisation_id,
                service_id=None,
            ),
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

        # --- Génération automatique de l'écriture comptable (module
        # Comptabilité, opt-in) : sans effet pour les organisations qui n'ont
        # pas activé le module. Cet encaissement n'a PAS de poste budgétaire
        # (créé par webhook, sans imputation), d'où la résolution du compte de
        # produit par rubrique technique.
        # Échec bloquant si la rubrique n'est pas mappée : la transaction
        # entière est annulée et le webhook renvoie une erreur, ce qui déclenche
        # un rejeu côté fournisseur. C'est voulu — encaisser sans écriture
        # laisserait un trou comptable silencieux — et le rejeu est sans risque
        # de doublon (l'encaissement est retrouvé par sa référence en tête de
        # cette fonction, et l'écriture est idempotente).
        await db.flush()
        if await est_comptabilite_activee(db, compte.organisation_id):
            await generer_ecriture_encaissement(
                db,
                organisation_id=compte.organisation_id,
                encaissement_id=str(enc.id),
                date_operation=enc.date_paiement.date(),
                montant=Decimal(event.amount),
                devise=event.currency,
                canal="BANQUE",
                compte_bancaire_id=compte.id,
                budget_poste_id=None,
                libelle=enc.libelle,
                created_by=None,
                rubrique_produit_defaut=RUBRIQUE_PRODUIT_PAIEMENT_EN_LIGNE,
            )

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
    if tx.organisation_id != user.organisation_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction introuvable")
    return OnlinePaymentStatusResponse(
        provider_ref=tx.provider_ref,
        status=tx.status,
        amount=tx.amount,
        currency=tx.currency,
        fees=tx.fees,
        method=tx.method,
    )
