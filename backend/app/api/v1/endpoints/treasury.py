from __future__ import annotations

from fastapi import APIRouter, Depends
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.encaissement import Encaissement
from app.models.sortie_fonds import SortieFonds
from app.models.user import User
from app.schemas.banque import CompteBancaireOut
from app.schemas.treasury import TreasuryCaisseOut, TreasuryOverviewOut

router = APIRouter()


@router.get("/soldes", response_model=TreasuryOverviewOut)
async def get_treasury_balances(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TreasuryOverviewOut:
    caisse_res = await db.execute(
        select(CaisseCentrale).where(CaisseCentrale.organisation_id == user.organisation_id).limit(1)
    )
    caisse = caisse_res.scalar_one_or_none()
    if caisse is None:
        caisse = CaisseCentrale(organisation_id=user.organisation_id, solde_usd=0, solde_cdf=0)
        db.add(caisse)
        await db.flush()

    cash_init_usd_res = await db.execute(
        select(func.coalesce(func.sum(CompteBancaire.solde_initial), 0)).where(
            CompteBancaire.organisation_id == user.organisation_id,
            CompteBancaire.account_type == "CASH",
            CompteBancaire.devise == "USD",
            CompteBancaire.is_active.is_(True),
        )
    )
    cash_init_cdf_res = await db.execute(
        select(func.coalesce(func.sum(CompteBancaire.solde_initial), 0)).where(
            CompteBancaire.organisation_id == user.organisation_id,
            CompteBancaire.account_type == "CASH",
            CompteBancaire.devise == "CDF",
            CompteBancaire.is_active.is_(True),
        )
    )

    enc_usd_res = await db.execute(
        select(func.coalesce(func.sum(Encaissement.montant_paye), 0)).where(
            Encaissement.organisation_id == user.organisation_id,
            Encaissement.is_deleted.is_(False),
            Encaissement.canal == "CAISSE",
            Encaissement.devise_perception == "USD",
        )
    )
    enc_cdf_res = await db.execute(
        select(func.coalesce(func.sum(Encaissement.montant_percu), 0)).where(
            Encaissement.organisation_id == user.organisation_id,
            Encaissement.is_deleted.is_(False),
            Encaissement.canal == "CAISSE",
            Encaissement.devise_perception == "CDF",
        )
    )

    sorties_usd_res = await db.execute(
        select(func.coalesce(func.sum(SortieFonds.montant_paye), 0)).where(
            SortieFonds.organisation_id == user.organisation_id,
            (SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE"),
            SortieFonds.canal == "CAISSE",
            SortieFonds.devise == "USD",
        )
    )
    sorties_cdf_res = await db.execute(
        select(func.coalesce(func.sum(SortieFonds.montant_paye), 0)).where(
            SortieFonds.organisation_id == user.organisation_id,
            (SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE"),
            SortieFonds.canal == "CAISSE",
            SortieFonds.devise == "CDF",
        )
    )

    cash_init_usd = Decimal(cash_init_usd_res.scalar_one() or 0)
    cash_init_cdf = Decimal(cash_init_cdf_res.scalar_one() or 0)
    enc_usd = Decimal(enc_usd_res.scalar_one() or 0)
    enc_cdf = Decimal(enc_cdf_res.scalar_one() or 0)
    sorties_usd = Decimal(sorties_usd_res.scalar_one() or 0)
    sorties_cdf = Decimal(sorties_cdf_res.scalar_one() or 0)

    caisse.solde_usd = cash_init_usd + enc_usd - sorties_usd
    caisse.solde_cdf = cash_init_cdf + enc_cdf - sorties_cdf
    await db.commit()
    caisse_out = TreasuryCaisseOut(
        solde_usd=caisse.solde_usd,
        solde_cdf=caisse.solde_cdf,
        derniere_maj=caisse.derniere_maj,
    )

    comptes_res = await db.execute(
        select(CompteBancaire)
        .options(selectinload(CompteBancaire.banque))
        .where(CompteBancaire.organisation_id == user.organisation_id)
        .where(CompteBancaire.account_type == "BANK")
        .order_by(CompteBancaire.id.asc())
    )
    comptes = [CompteBancaireOut.model_validate(c) for c in comptes_res.scalars().all()]
    return TreasuryOverviewOut(caisse=caisse_out, comptes=comptes)
