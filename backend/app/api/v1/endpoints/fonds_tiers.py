from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, has_permission
from app.db.session import get_db
from app.models.fonds_tiers_operation import FondsTiersOperation
from app.schemas.fonds_tiers import FondsTiersOut
from app.services.fonds_tiers import fonds_tiers_amounts


router = APIRouter()


async def _to_out(db: AsyncSession, tenant_id: int, operation: FondsTiersOperation) -> FondsTiersOut:
    montant_recu, devise, montant_rembourse, solde = await fonds_tiers_amounts(
        db,
        organisation_id=tenant_id,
        operation=operation,
    )
    return FondsTiersOut(
        id=operation.id,
        organisation_id=operation.organisation_id,
        encaissement_id=operation.encaissement_id,
        statut=operation.statut,
        tiers_concerne=operation.tiers_concerne,
        payeur_origine=operation.payeur_origine,
        beneficiaire_reel=operation.beneficiaire_reel,
        motif=operation.motif,
        reference=operation.reference,
        piece_justificative=operation.piece_justificative,
        montant_recu=Decimal(str(montant_recu)),
        devise=devise,  # type: ignore[arg-type]
        montant_rembourse=Decimal(str(montant_rembourse)),
        solde_restant=Decimal(str(solde)),
        created_by=operation.created_by,
        created_at=operation.created_at,
        updated_at=operation.updated_at,
    )


@router.get("", response_model=list[FondsTiersOut], dependencies=[Depends(has_permission("encaissements"))])
async def list_fonds_tiers(
    statut: str | None = Query(default=None),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[FondsTiersOut]:
    stmt = select(FondsTiersOperation).where(FondsTiersOperation.organisation_id == tenant_id)
    if statut:
        stmt = stmt.where(FondsTiersOperation.statut == statut.strip().upper())
    stmt = stmt.order_by(FondsTiersOperation.created_at.desc()).limit(500)
    res = await db.execute(stmt)
    return [await _to_out(db, tenant_id, operation) for operation in res.scalars().all()]


@router.get("/{operation_id}", response_model=FondsTiersOut, dependencies=[Depends(has_permission("encaissements"))])
async def get_fonds_tiers(
    operation_id: str,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> FondsTiersOut:
    try:
        operation_uuid = uuid.UUID(operation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="operation_id invalide")
    res = await db.execute(
        select(FondsTiersOperation).where(
            FondsTiersOperation.id == operation_uuid,
            FondsTiersOperation.organisation_id == tenant_id,
        )
    )
    operation = res.scalar_one_or_none()
    if operation is None:
        raise HTTPException(status_code=404, detail="Fonds de tiers introuvable")
    return await _to_out(db, tenant_id, operation)
