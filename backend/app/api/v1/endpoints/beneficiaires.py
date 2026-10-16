"""Bénéficiaires des sorties de fonds : recherche et répertoire des externes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, has_permission
from app.db.session import get_db
from app.models.user import User
from app.services import beneficiaires as service

router = APIRouter()


class BeneficiaireSuggestion(BaseModel):
    type: str
    id: str
    nom: str
    detail: str | None = None
    email: str | None = None
    telephone: str | None = None


class BeneficiaireExterneCreate(BaseModel):
    nom: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=200)
    telephone: str | None = Field(default=None, max_length=50)
    structure: str | None = Field(default=None, max_length=200)


@router.get("", response_model=list[BeneficiaireSuggestion])
async def rechercher_beneficiaires(
    q: str = Query("", max_length=100),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
    _: User = Depends(get_current_user),
) -> list[BeneficiaireSuggestion]:
    """Experts-comptables, puis personnel, puis externes dont le nom contient `q`."""
    return [BeneficiaireSuggestion(**item) for item in await service.rechercher(db, tenant_id, q)]


@router.post("/externes", response_model=BeneficiaireSuggestion, status_code=201)
async def creer_beneficiaire_externe(
    payload: BeneficiaireExterneCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(has_permission("can_execute_payment")),
) -> BeneficiaireSuggestion:
    """Fiche externe de ce nom — reprise si elle existe déjà, contacts complétés."""
    externe = await service.enregistrer_externe(
        db,
        tenant_id,
        nom=payload.nom,
        email=service.nettoyer_email(payload.email),
        telephone=service.nettoyer_telephone(payload.telephone),
        structure=payload.structure,
        created_by=user.id,
    )
    await db.commit()
    await db.refresh(externe)
    return BeneficiaireSuggestion(
        type=service.TYPE_EXTERNE,
        id=str(externe.id),
        nom=externe.nom,
        detail=externe.structure or "Personne externe",
        email=externe.email,
        telephone=externe.telephone,
    )
