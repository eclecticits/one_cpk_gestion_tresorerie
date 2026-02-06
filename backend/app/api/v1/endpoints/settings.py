from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.print_settings import PrintSettings
from app.models.user import User
from app.schemas.settings import PrintSettingsResponse, PrintSettingsUpdate

router = APIRouter()


def _settings_to_response(settings: PrintSettings) -> dict:
    """Convertit un modèle PrintSettings en dict pour la réponse."""
    return {
        "id": str(settings.id),
        "organization_name": settings.organization_name,
        "organization_subtitle": settings.organization_subtitle,
        "header_text": settings.header_text,
        "address": settings.address,
        "phone": settings.phone,
        "email": settings.email,
        "website": settings.website,
        "bank_name": settings.bank_name,
        "bank_account": settings.bank_account,
        "mobile_money_name": settings.mobile_money_name,
        "mobile_money_number": settings.mobile_money_number,
        "footer_text": settings.footer_text,
        "show_header_logo": settings.show_header_logo,
        "show_footer_signature": settings.show_footer_signature,
        "logo_url": settings.logo_url,
        "stamp_url": settings.stamp_url,
        "signature_name": settings.signature_name,
        "signature_title": settings.signature_title,
        "paper_format": settings.paper_format,
        "compact_header": settings.compact_header,
        "default_currency": settings.default_currency,
        "secondary_currency": settings.secondary_currency,
        "exchange_rate": float(settings.exchange_rate or 0),
        "fiscal_year": settings.fiscal_year,
        "budget_alert_threshold": settings.budget_alert_threshold,
        "budget_block_overrun": settings.budget_block_overrun,
        "budget_force_roles": settings.budget_force_roles,
        "updated_by": str(settings.updated_by) if settings.updated_by else None,
        "updated_at": settings.updated_at,
    }


@router.get("", response_model=PrintSettingsResponse)
async def get_print_settings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Récupère les paramètres d'impression (singleton)."""
    result = await db.execute(select(PrintSettings).limit(1))
    settings = result.scalar_one_or_none()

    if not settings:
        # Créer les paramètres par défaut s'ils n'existent pas
        settings = PrintSettings(
            organization_name="ONEC - Ordre National des Experts Comptables",
            organization_subtitle="République Démocratique du Congo",
            footer_text="Ce reçu fait foi de paiement. Conservez-le précieusement.",
        )
        db.add(settings)
        await db.commit()
        await db.refresh(settings)

    return _settings_to_response(settings)


@router.put("", response_model=PrintSettingsResponse)
async def update_print_settings(
    payload: PrintSettingsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Met à jour les paramètres d'impression."""
    # Seuls les admins peuvent modifier les paramètres
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seuls les administrateurs peuvent modifier les paramètres"
        )

    result = await db.execute(select(PrintSettings).limit(1))
    settings = result.scalar_one_or_none()

    if not settings:
        # Créer si n'existe pas
        settings = PrintSettings()
        db.add(settings)

    # Appliquer les mises à jour
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(settings, key, value)

    settings.updated_by = user.id
    settings.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(settings)

    return _settings_to_response(settings)
