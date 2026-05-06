from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, has_permission
from app.db.session import get_db
from app.models.organisation import Organisation
from app.models.organisation_settings import OrganisationSettings
from app.schemas.organisation_settings import OrganisationSettingsPublicOut, OrganisationSettingsUpdate
from app.schemas.organisation import OrganisationOut, OrganisationPublicOut, OrganisationUpdate

router = APIRouter()
logger = logging.getLogger("onec_cpk_api.organisation")


@router.get("/public", response_model=list[OrganisationPublicOut])
async def list_public_organisations(db: AsyncSession = Depends(get_db)) -> list[OrganisationPublicOut]:
    started_at = time.perf_counter()
    try:
        res = await db.execute(
            select(Organisation)
            .where(Organisation.is_active.is_(True))
            .order_by(Organisation.sort_order.asc(), Organisation.nom.asc())
        )
        orgs = res.scalars().all()
        return [
            OrganisationPublicOut(
                nom=org.nom,
                slug=org.slug,
                logo_url=org.logo_url,
                icon=org.icon,
                sort_order=org.sort_order,
            )
            for org in orgs
        ]
    except Exception as exc:
        logger.exception("ORGANISATION_PUBLIC_LIST_FAILED")
        raise HTTPException(status_code=500, detail="Erreur interne lors du chargement des organisations publiques.") from exc
    finally:
        logger.info("ORGANISATION_PUBLIC_LIST_COMPLETED duration_ms=%s", round((time.perf_counter() - started_at) * 1000, 2))


@router.get("/public/{slug}", response_model=OrganisationPublicOut)
async def get_public_organisation(slug: str, db: AsyncSession = Depends(get_db)) -> OrganisationPublicOut:
    started_at = time.perf_counter()
    try:
        slug_clean = (slug or "").strip().lower()
        if not slug_clean:
            raise HTTPException(status_code=404, detail="Organisation introuvable")
        res = await db.execute(select(Organisation).where(Organisation.slug == slug_clean))
        org = res.scalar_one_or_none()
        if org is None or org.is_active is False:
            raise HTTPException(status_code=404, detail="Organisation introuvable")
        return OrganisationPublicOut(
            nom=org.nom,
            slug=org.slug,
            logo_url=org.logo_url,
            icon=org.icon,
            sort_order=org.sort_order,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("ORGANISATION_PUBLIC_GET_FAILED slug=%s", slug)
        raise HTTPException(status_code=500, detail="Erreur interne lors du chargement de l'organisation publique.") from exc
    finally:
        logger.info("ORGANISATION_PUBLIC_GET_COMPLETED slug=%s duration_ms=%s", slug, round((time.perf_counter() - started_at) * 1000, 2))


@router.get("", response_model=OrganisationOut)
async def get_organisation(
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> OrganisationOut:
    res = await db.execute(select(Organisation).where(Organisation.id == tenant_id))
    org = res.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organisation introuvable")
    return OrganisationOut(
        id=org.id,
        uuid=str(org.uuid),
        nom=org.nom,
        slug=org.slug,
        logo_url=org.logo_url,
        email_contact=org.email_contact,
        telephone=org.telephone,
        adresse=org.adresse,
        devise_preferee=org.devise_preferee,
        taux_change_interne=float(org.taux_change_interne or 0),
        plan_type=org.plan_type,
        status_abonnement=org.status_abonnement,
        date_expiration_abonnement=org.date_expiration_abonnement,
        limite_utilisateurs=org.limite_utilisateurs,
    )


@router.put("", response_model=OrganisationOut, dependencies=[Depends(has_permission("can_edit_settings"))])
async def update_organisation(
    payload: OrganisationUpdate,
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> OrganisationOut:
    res = await db.execute(select(Organisation).where(Organisation.id == tenant_id))
    org = res.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organisation introuvable")
    settings_res = await db.execute(
        select(OrganisationSettings).where(OrganisationSettings.organisation_id == tenant_id).limit(1)
    )
    settings = settings_res.scalar_one_or_none()
    if settings is None:
        settings = OrganisationSettings(organisation_id=tenant_id)
        db.add(settings)
        await db.flush()

    data = payload.model_dump(exclude_unset=True)
    if "nom" in data and data["nom"] is not None:
        org.nom = data["nom"].strip()
    if "logo_url" in data:
        org.logo_url = data["logo_url"] or None
    if "email_contact" in data:
        org.email_contact = data["email_contact"] or None
    if "telephone" in data:
        org.telephone = data["telephone"] or None
    if "adresse" in data:
        org.adresse = data["adresse"] or None
    if "devise_preferee" in data and data["devise_preferee"] is not None:
        devise_value = data["devise_preferee"].upper()
        org.devise_preferee = devise_value
        settings.currency_code = devise_value
    if "taux_change_interne" in data and data["taux_change_interne"] is not None:
        org.taux_change_interne = data["taux_change_interne"]

    await db.commit()
    await db.refresh(org)

    return OrganisationOut(
        id=org.id,
        uuid=str(org.uuid),
        nom=org.nom,
        slug=org.slug,
        logo_url=org.logo_url,
        email_contact=org.email_contact,
        telephone=org.telephone,
        adresse=org.adresse,
        devise_preferee=org.devise_preferee,
        taux_change_interne=float(org.taux_change_interne or 0),
        plan_type=org.plan_type,
        status_abonnement=org.status_abonnement,
        date_expiration_abonnement=org.date_expiration_abonnement,
        limite_utilisateurs=org.limite_utilisateurs,
    )


@router.get("/settings", response_model=OrganisationSettingsPublicOut)
async def get_organisation_settings(
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> OrganisationSettingsPublicOut:
    res = await db.execute(
        select(OrganisationSettings).where(OrganisationSettings.organisation_id == tenant_id).limit(1)
    )
    settings = res.scalar_one_or_none()
    if settings is None:
        settings = OrganisationSettings(organisation_id=tenant_id)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return OrganisationSettingsPublicOut(
        organisation_id=settings.organisation_id,
        max_users=settings.max_users,
        storage_quota_mb=settings.storage_quota_mb,
        is_ai_enabled=settings.is_ai_enabled,
        is_mobile_money_enabled=settings.is_mobile_money_enabled,
        is_audit_logs_enabled=settings.is_audit_logs_enabled,
        fiscal_year_start=settings.fiscal_year_start,
        currency_code=settings.currency_code,
        theme_primary_color=settings.theme_primary_color,
        theme_sidebar_color=settings.theme_sidebar_color,
        theme_sidebar_text_color=settings.theme_sidebar_text_color,
        theme_sidebar_active_color=settings.theme_sidebar_active_color,
        theme_accent_color=settings.theme_accent_color,
        theme_text_color=settings.theme_text_color,
        theme_button_text_color=settings.theme_button_text_color,
    )


@router.patch("/settings", response_model=OrganisationSettingsPublicOut, dependencies=[Depends(has_permission("can_edit_settings"))])
async def update_organisation_settings(
    payload: OrganisationSettingsUpdate,
    user=Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> OrganisationSettingsPublicOut:
    res = await db.execute(
        select(OrganisationSettings).where(OrganisationSettings.organisation_id == tenant_id).limit(1)
    )
    settings = res.scalar_one_or_none()
    if settings is None:
        settings = OrganisationSettings(organisation_id=tenant_id)
        db.add(settings)
        await db.flush()
    org_res = await db.execute(select(Organisation).where(Organisation.id == tenant_id))
    org = org_res.scalar_one_or_none()

    data = payload.model_dump(exclude_unset=True)
    if "currency_code" in data and data["currency_code"] is not None:
        currency_value = data["currency_code"].strip().upper()
        settings.currency_code = currency_value
        if org is not None:
            org.devise_preferee = currency_value
    if "theme_primary_color" in data and data["theme_primary_color"] is not None:
        settings.theme_primary_color = data["theme_primary_color"].strip()
    if "theme_sidebar_color" in data and data["theme_sidebar_color"] is not None:
        settings.theme_sidebar_color = data["theme_sidebar_color"].strip()
    if "theme_sidebar_text_color" in data and data["theme_sidebar_text_color"] is not None:
        settings.theme_sidebar_text_color = data["theme_sidebar_text_color"].strip()
    if "theme_sidebar_active_color" in data and data["theme_sidebar_active_color"] is not None:
        settings.theme_sidebar_active_color = data["theme_sidebar_active_color"].strip()
    if "theme_accent_color" in data and data["theme_accent_color"] is not None:
        settings.theme_accent_color = data["theme_accent_color"].strip()
    if "theme_text_color" in data and data["theme_text_color"] is not None:
        settings.theme_text_color = data["theme_text_color"].strip()
    if "theme_button_text_color" in data and data["theme_button_text_color"] is not None:
        settings.theme_button_text_color = data["theme_button_text_color"].strip()

    await db.commit()
    await db.refresh(settings)

    return OrganisationSettingsPublicOut(
        organisation_id=settings.organisation_id,
        max_users=settings.max_users,
        storage_quota_mb=settings.storage_quota_mb,
        is_ai_enabled=settings.is_ai_enabled,
        is_mobile_money_enabled=settings.is_mobile_money_enabled,
        is_audit_logs_enabled=settings.is_audit_logs_enabled,
        fiscal_year_start=settings.fiscal_year_start,
        currency_code=settings.currency_code,
        theme_primary_color=settings.theme_primary_color,
        theme_sidebar_color=settings.theme_sidebar_color,
        theme_sidebar_text_color=settings.theme_sidebar_text_color,
        theme_sidebar_active_color=settings.theme_sidebar_active_color,
        theme_accent_color=settings.theme_accent_color,
        theme_text_color=settings.theme_text_color,
        theme_button_text_color=settings.theme_button_text_color,
    )
