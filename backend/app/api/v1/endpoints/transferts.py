from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_current_tenant_id, has_permission
from app.db.session import get_db
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.cloture_caisse import ClotureCaisse
from app.models.transfert_interne import TransfertInterne
from app.models.user import User
from app.schemas.transfert import TransfertInterneCreate, TransfertInterneOut

router = APIRouter()


async def _get_or_create_caisse(db: AsyncSession, tenant_id: int) -> CaisseCentrale:
    res = await db.execute(select(CaisseCentrale).where(CaisseCentrale.organisation_id == tenant_id).limit(1))
    caisse = res.scalar_one_or_none()
    if caisse is None:
        await db.execute(
            pg_insert(CaisseCentrale)
            .values(organisation_id=tenant_id, solde_usd=0, solde_cdf=0)
            .on_conflict_do_nothing(index_elements=["organisation_id"])
        )
        res = await db.execute(select(CaisseCentrale).where(CaisseCentrale.organisation_id == tenant_id).limit(1))
        caisse = res.scalar_one()
    return caisse


async def _get_last_cloture_date(db: AsyncSession, tenant_id: int) -> datetime | None:
    res = await db.execute(
        select(ClotureCaisse)
        .where(ClotureCaisse.organisation_id == tenant_id)
        .order_by(ClotureCaisse.date_cloture.desc())
        .limit(1)
    )
    last = res.scalar_one_or_none()
    if not last or not last.date_cloture:
        return None
    last_dt = last.date_cloture
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=timezone.utc)
    return last_dt


def _transfer_to_out(t: TransfertInterne) -> TransfertInterneOut:
    return TransfertInterneOut(
        id=t.id,
        source_type=t.source_type,
        source_id=t.source_id,
        destination_type=t.destination_type,
        destination_id=t.destination_id,
        montant=t.montant,
        devise=t.devise,
        reference=t.reference,
        date_transfert=t.date_transfert,
        execute_par=str(t.execute_par) if t.execute_par else None,
    )


@router.get("", response_model=list[TransfertInterneOut])
async def list_transferts(
    limit: int = Query(default=50, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[TransfertInterneOut]:
    _ = user
    res = await db.execute(
        select(TransfertInterne)
        .where(TransfertInterne.organisation_id == tenant_id)
        .order_by(TransfertInterne.date_transfert.desc())
        .offset(offset)
        .limit(limit)
    )
    return [_transfer_to_out(t) for t in res.scalars().all()]


@router.post("", response_model=TransfertInterneOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(has_permission("sorties_fonds"))])
async def create_transfert(
    payload: TransfertInterneCreate,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> TransfertInterneOut:
    source_type = (payload.source_type or "").upper()
    destination_type = (payload.destination_type or "").upper()
    devise = (payload.devise or "USD").upper()

    if source_type not in {"CAISSE", "BANQUE"}:
        raise HTTPException(status_code=400, detail="source_type invalide")
    if destination_type not in {"CAISSE", "BANQUE"}:
        raise HTTPException(status_code=400, detail="destination_type invalide")
    if devise not in {"USD", "CDF"}:
        raise HTTPException(status_code=400, detail="devise invalide")

    if source_type == destination_type and payload.source_id == payload.destination_id:
        raise HTTPException(status_code=400, detail="source et destination identiques")

    montant = Decimal(payload.montant or 0)
    if montant <= 0:
        raise HTTPException(status_code=400, detail="montant invalide")

    date_transfert = payload.date_transfert or datetime.now(timezone.utc)
    if isinstance(date_transfert, datetime) and date_transfert.tzinfo is None:
        date_transfert = date_transfert.replace(tzinfo=timezone.utc)
    source_caisse: CaisseCentrale | None = None
    dest_caisse: CaisseCentrale | None = None
    source_compte: CompteBancaire | None = None
    dest_compte: CompteBancaire | None = None

    if source_type == "CAISSE":
        caisse = await _get_or_create_caisse(db, tenant_id)
        res = await db.execute(
            select(CaisseCentrale)
            .where(CaisseCentrale.id == caisse.id, CaisseCentrale.organisation_id == tenant_id)
            .with_for_update()
        )
        source_caisse = res.scalar_one()
        solde_dispo = source_caisse.solde_usd if devise == "USD" else source_caisse.solde_cdf
        if montant > (solde_dispo or 0):
            raise HTTPException(status_code=400, detail=f"Solde caisse {devise} insuffisant")
    else:
        if payload.source_id is None:
            raise HTTPException(status_code=400, detail="source_id requis")
        res = await db.execute(
            select(CompteBancaire)
            .where(
                CompteBancaire.id == payload.source_id,
                CompteBancaire.organisation_id == tenant_id,
            )
            .with_for_update()
        )
        source_compte = res.scalar_one_or_none()
        if source_compte is None or source_compte.is_active is False:
            raise HTTPException(status_code=400, detail="source_id invalide")
        if (source_compte.devise or "").upper() != devise:
            raise HTTPException(status_code=400, detail="devise incompatible avec la source")
        if montant > (source_compte.solde_actuel or 0):
            raise HTTPException(status_code=400, detail="Solde banque insuffisant")

    if destination_type == "CAISSE":
        caisse = await _get_or_create_caisse(db, tenant_id)
        res = await db.execute(
            select(CaisseCentrale)
            .where(CaisseCentrale.id == caisse.id, CaisseCentrale.organisation_id == tenant_id)
            .with_for_update()
        )
        dest_caisse = res.scalar_one()
    else:
        if payload.destination_id is None:
            raise HTTPException(status_code=400, detail="destination_id requis")
        res = await db.execute(
            select(CompteBancaire)
            .where(
                CompteBancaire.id == payload.destination_id,
                CompteBancaire.organisation_id == tenant_id,
            )
            .with_for_update()
        )
        dest_compte = res.scalar_one_or_none()
        if dest_compte is None or dest_compte.is_active is False:
            raise HTTPException(status_code=400, detail="destination_id invalide")
        if (dest_compte.devise or "").upper() != devise:
            raise HTTPException(status_code=400, detail="devise incompatible avec la destination")

    if source_caisse is not None:
        if devise == "USD":
            source_caisse.solde_usd = (source_caisse.solde_usd or 0) - montant
        else:
            source_caisse.solde_cdf = (source_caisse.solde_cdf or 0) - montant
        source_caisse.derniere_maj = datetime.now(timezone.utc)
    if source_compte is not None:
        source_compte.solde_actuel = (source_compte.solde_actuel or 0) - montant

    if dest_caisse is not None:
        if devise == "USD":
            dest_caisse.solde_usd = (dest_caisse.solde_usd or 0) + montant
        else:
            dest_caisse.solde_cdf = (dest_caisse.solde_cdf or 0) + montant
        dest_caisse.derniere_maj = datetime.now(timezone.utc)
    if dest_compte is not None:
        dest_compte.solde_actuel = (dest_compte.solde_actuel or 0) + montant

    transfert = TransfertInterne(
        organisation_id=tenant_id,
        source_type=source_type,
        source_id=payload.source_id if source_type == "BANQUE" else None,
        destination_type=destination_type,
        destination_id=payload.destination_id if destination_type == "BANQUE" else None,
        montant=montant,
        devise=devise,
        reference=payload.reference,
        date_transfert=date_transfert,
        execute_par=user.id,
    )
    db.add(transfert)
    await db.commit()
    await db.refresh(transfert)
    return _transfer_to_out(transfert)
