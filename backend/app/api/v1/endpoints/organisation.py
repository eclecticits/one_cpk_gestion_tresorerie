from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, has_permission
from app.db.session import get_db
from app.models.organisation import Organisation
from app.schemas.organisation import OrganisationOut, OrganisationPublicOut, OrganisationUpdate

router = APIRouter()


@router.get("/public/{slug}", response_model=OrganisationPublicOut)
async def get_public_organisation(slug: str, db: AsyncSession = Depends(get_db)) -> OrganisationPublicOut:
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
    )


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
        org.devise_preferee = data["devise_preferee"].upper()
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
