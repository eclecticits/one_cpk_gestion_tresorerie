from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.encaissement import Encaissement
from app.models.fonds_tiers_operation import FondsTiersOperation
from app.models.sortie_fonds import SortieFonds


def _money(value: object) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


async def create_fonds_tiers_operation(
    db: AsyncSession,
    *,
    organisation_id: int,
    encaissement: Encaissement,
    tiers_concerne: str,
    payeur_origine: str | None,
    beneficiaire_reel: str | None,
    motif: str | None,
    reference: str | None,
    piece_justificative: str | None,
    created_by: uuid.UUID | None,
) -> FondsTiersOperation:
    if encaissement.organisation_id != organisation_id:
        raise HTTPException(status_code=404, detail="Encaissement introuvable")
    if (encaissement.nature_mouvement or "").upper() != "FONDS_DE_TIERS":
        raise HTTPException(status_code=400, detail="L'encaissement n'est pas un fonds de tiers")
    operation = FondsTiersOperation(
        organisation_id=organisation_id,
        encaissement_id=encaissement.id,
        statut="OUVERT",
        tiers_concerne=tiers_concerne.strip(),
        payeur_origine=(payeur_origine or "").strip() or None,
        beneficiaire_reel=(beneficiaire_reel or "").strip() or None,
        motif=(motif or "").strip() or None,
        reference=(reference or "").strip() or None,
        piece_justificative=(piece_justificative or "").strip() or None,
        created_by=created_by,
    )
    db.add(operation)
    await db.flush()
    return operation


async def get_fonds_tiers_locked(
    db: AsyncSession,
    *,
    organisation_id: int,
    operation_id: uuid.UUID,
) -> FondsTiersOperation:
    res = await db.execute(
        select(FondsTiersOperation)
        .where(FondsTiersOperation.id == operation_id, FondsTiersOperation.organisation_id == organisation_id)
        .with_for_update()
    )
    operation = res.scalar_one_or_none()
    if operation is None:
        raise HTTPException(status_code=404, detail="Fonds de tiers introuvable")
    return operation


async def fonds_tiers_amounts(
    db: AsyncSession,
    *,
    organisation_id: int,
    operation: FondsTiersOperation,
) -> tuple[Decimal, str, Decimal, Decimal]:
    enc_res = await db.execute(
        select(Encaissement).where(
            Encaissement.id == operation.encaissement_id,
            Encaissement.organisation_id == organisation_id,
        )
    )
    encaissement = enc_res.scalar_one_or_none()
    if encaissement is None or (encaissement.statut_operation or "ACTIVE").upper() != "ACTIVE":
        montant_recu = Decimal("0.00")
        devise = "USD"
    else:
        montant_recu = _money(encaissement.montant_paye or encaissement.montant_total or encaissement.montant or 0)
        devise = (encaissement.devise_perception or "USD").upper()

    remb_res = await db.execute(
        select(func.coalesce(func.sum(SortieFonds.montant_paye), 0)).where(
            SortieFonds.organisation_id == organisation_id,
            SortieFonds.fonds_tiers_operation_id == operation.id,
            SortieFonds.statut == "VALIDE",
        )
    )
    montant_rembourse = _money(remb_res.scalar_one() or 0)
    solde = max(Decimal("0.00"), montant_recu - montant_rembourse)
    return montant_recu, devise, montant_rembourse, solde


async def refresh_fonds_tiers_status(
    db: AsyncSession,
    *,
    organisation_id: int,
    operation: FondsTiersOperation,
) -> None:
    montant_recu, _devise, montant_rembourse, solde = await fonds_tiers_amounts(
        db,
        organisation_id=organisation_id,
        operation=operation,
    )
    if operation.statut == "ANNULE":
        return
    if montant_recu <= 0:
        operation.statut = "ANNULE"
    elif solde <= 0:
        operation.statut = "REGULARISE"
    elif montant_rembourse > 0:
        operation.statut = "PARTIELLEMENT_REMBOURSE"
    else:
        operation.statut = "OUVERT"
    operation.updated_at = datetime.now(timezone.utc)
    await db.flush()


async def assert_fonds_tiers_refundable(
    db: AsyncSession,
    *,
    organisation_id: int,
    operation_id: uuid.UUID,
    montant: Decimal,
    devise: str,
) -> FondsTiersOperation:
    operation = await get_fonds_tiers_locked(db, organisation_id=organisation_id, operation_id=operation_id)
    if operation.statut == "ANNULE":
        raise HTTPException(status_code=400, detail="Fonds de tiers annulé")
    montant_recu, devise_origine, _rembourse, solde = await fonds_tiers_amounts(
        db,
        organisation_id=organisation_id,
        operation=operation,
    )
    if montant_recu <= 0:
        raise HTTPException(status_code=400, detail="Encaissement d'origine inactif")
    if (devise or "").upper() != devise_origine:
        raise HTTPException(status_code=400, detail="Remboursement dans une devise différente non supporté en V1")
    if _money(montant) > solde:
        raise HTTPException(status_code=400, detail=f"Montant supérieur au solde à rembourser: {solde} {devise_origine}")
    return operation


async def assert_fonds_tiers_origin_can_be_cancelled(
    db: AsyncSession,
    *,
    organisation_id: int,
    encaissement_id: uuid.UUID,
) -> None:
    op_res = await db.execute(
        select(FondsTiersOperation)
        .where(FondsTiersOperation.organisation_id == organisation_id, FondsTiersOperation.encaissement_id == encaissement_id)
        .with_for_update()
    )
    operation = op_res.scalar_one_or_none()
    if operation is None:
        return
    remb_res = await db.execute(
        select(func.count(SortieFonds.id)).where(
            SortieFonds.organisation_id == organisation_id,
            SortieFonds.fonds_tiers_operation_id == operation.id,
            SortieFonds.statut == "VALIDE",
        )
    )
    if int(remb_res.scalar_one() or 0) > 0:
        raise HTTPException(status_code=409, detail="Annulation refusée: des remboursements fonds de tiers valides existent")
    operation.statut = "ANNULE"
    operation.updated_at = datetime.now(timezone.utc)
