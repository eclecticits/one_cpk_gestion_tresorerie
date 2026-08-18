from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_tenant_id, get_current_user, require_ai_enabled, require_roles
from app.db.session import get_db
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.encaissement import Encaissement
from app.models.retour_caisse import RetourCaisse
from app.models.sortie_fonds import SortieFonds
from app.models.transfert_interne import TransfertInterne
from app.models.user import User
from app.schemas.banque import CompteBancaireOut
from app.schemas.treasury import (
    TreasuryCaisseOut,
    TreasuryConfirmClassificationRequest,
    TreasuryConfirmClassificationResponse,
    TreasuryOverviewOut,
)
from app.services.ai_batch_service import AIBatchProcessor
from app.services.ai_memory_service import AIMemoryService
# ExcelParser est importé dans la vue : il tire pandas (57 Mo de RSS et ~1,3 s
# d'import), payés par chaque worker au démarrage alors qu'un seul endpoint s'en
# sert. Import différé = mémoire rendue aux workers supplémentaires.

router = APIRouter()


@router.get("/soldes", response_model=TreasuryOverviewOut)
async def get_treasury_balances(
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TreasuryOverviewOut:
    caisse_res = await db.execute(
        select(CaisseCentrale).where(CaisseCentrale.organisation_id == tenant_id).limit(1)
    )
    caisse = caisse_res.scalar_one_or_none()
    if caisse is None:
        caisse_out = TreasuryCaisseOut(solde_usd=Decimal("0"), solde_cdf=Decimal("0"), derniere_maj=None)
    else:
        caisse_out = TreasuryCaisseOut(
            solde_usd=caisse.solde_usd,
            solde_cdf=caisse.solde_cdf,
            derniere_maj=caisse.derniere_maj,
        )

    comptes_res = await db.execute(
        select(CompteBancaire)
        .options(selectinload(CompteBancaire.banque))
        .where(CompteBancaire.organisation_id == tenant_id)
        .where(CompteBancaire.account_type == "BANK")
        .order_by(CompteBancaire.id.asc())
    )
    comptes = [CompteBancaireOut.model_validate(c) for c in comptes_res.scalars().all()]
    return TreasuryOverviewOut(caisse=caisse_out, comptes=comptes)


async def _recalculate_treasury_balances(
    tenant_id: int,
    db: AsyncSession,
) -> CaisseCentrale:
    caisse_res = await db.execute(
        select(CaisseCentrale).where(CaisseCentrale.organisation_id == tenant_id).limit(1)
    )
    caisse = caisse_res.scalar_one_or_none()
    if caisse is None:
        caisse = CaisseCentrale(organisation_id=tenant_id, solde_usd=0, solde_cdf=0)
        db.add(caisse)
        await db.flush()

    cash_init_usd_res = await db.execute(
        select(func.coalesce(func.sum(CompteBancaire.solde_initial), 0)).where(
            CompteBancaire.organisation_id == tenant_id,
            CompteBancaire.account_type == "CASH",
            CompteBancaire.devise == "USD",
            CompteBancaire.is_active.is_(True),
        )
    )
    cash_init_cdf_res = await db.execute(
        select(func.coalesce(func.sum(CompteBancaire.solde_initial), 0)).where(
            CompteBancaire.organisation_id == tenant_id,
            CompteBancaire.account_type == "CASH",
            CompteBancaire.devise == "CDF",
            CompteBancaire.is_active.is_(True),
        )
    )

    enc_usd_res = await db.execute(
        select(func.coalesce(func.sum(Encaissement.montant_paye), 0)).where(
            Encaissement.organisation_id == tenant_id,
            Encaissement.is_deleted.is_(False),
            ((Encaissement.statut_operation.is_(None)) | (Encaissement.statut_operation == "ACTIVE")),
            Encaissement.canal == "CAISSE",
            Encaissement.devise_perception == "USD",
            Encaissement.est_proforma.is_(False),
        )
    )
    enc_cdf_res = await db.execute(
        select(func.coalesce(func.sum(Encaissement.montant_percu), 0)).where(
            Encaissement.organisation_id == tenant_id,
            Encaissement.is_deleted.is_(False),
            ((Encaissement.statut_operation.is_(None)) | (Encaissement.statut_operation == "ACTIVE")),
            Encaissement.canal == "CAISSE",
            Encaissement.devise_perception == "CDF",
            Encaissement.est_proforma.is_(False),
        )
    )

    sorties_usd_res = await db.execute(
        select(func.coalesce(func.sum(SortieFonds.montant_paye), 0)).where(
            SortieFonds.organisation_id == tenant_id,
            (SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE"),
            SortieFonds.canal == "CAISSE",
            SortieFonds.devise == "USD",
        )
    )
    sorties_cdf_res = await db.execute(
        select(func.coalesce(func.sum(SortieFonds.montant_paye), 0)).where(
            SortieFonds.organisation_id == tenant_id,
            (SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE"),
            SortieFonds.canal == "CAISSE",
            SortieFonds.devise == "CDF",
        )
    )

    # Approvisionnements caisse (banque -> caisse) : canal BANQUE, donc absents
    # du total des sorties caisse ci-dessus. Ils CRÉDITENT la caisse et doivent
    # être ajoutés explicitement, sinon l'argent retiré de la banque n'apparaît
    # jamais en caisse (rupture d'équilibre).
    appro_usd_res = await db.execute(
        select(func.coalesce(func.sum(SortieFonds.montant_paye), 0)).where(
            SortieFonds.organisation_id == tenant_id,
            (SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE"),
            SortieFonds.type_sortie == "approvisionnement_caisse",
            SortieFonds.devise == "USD",
        )
    )
    appro_cdf_res = await db.execute(
        select(func.coalesce(func.sum(SortieFonds.montant_paye), 0)).where(
            SortieFonds.organisation_id == tenant_id,
            (SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE"),
            SortieFonds.type_sortie == "approvisionnement_caisse",
            SortieFonds.devise == "CDF",
        )
    )

    # Transferts internes (module dédié) : caisse créditée si destination = CAISSE,
    # débitée si source = CAISSE. Ignorés par l'ancien calcul (autre source de
    # « fonds qui disparaissent »).
    async def _transfert_sum(devise: str, *, as_destination: bool) -> Decimal:
        col = TransfertInterne.destination_type if as_destination else TransfertInterne.source_type
        res_t = await db.execute(
            select(func.coalesce(func.sum(TransfertInterne.montant), 0)).where(
                TransfertInterne.organisation_id == tenant_id,
                col == "CAISSE",
                TransfertInterne.devise == devise,
            )
        )
        return Decimal(res_t.scalar_one() or 0)

    # Retours en caisse (reliquats d'avances rendus) : `create_retour_caisse`
    # CRÉDITE la caisse au fil de l'eau. Sans ce terme, le recalcul repartirait
    # d'une formule qui les ignore et EFFACERAIT ces crédits — le solde chuterait
    # du total des retours à chaque appel de /tresorerie/soldes/recalculate.
    async def _retour_sum(devise: str) -> Decimal:
        res_r = await db.execute(
            select(func.coalesce(func.sum(RetourCaisse.montant), 0)).where(
                RetourCaisse.organisation_id == tenant_id,
                RetourCaisse.statut == "VALIDE",
                RetourCaisse.canal == "CAISSE",
                RetourCaisse.devise == devise,
            )
        )
        return Decimal(res_r.scalar_one() or 0)

    cash_init_usd = Decimal(cash_init_usd_res.scalar_one() or 0)
    cash_init_cdf = Decimal(cash_init_cdf_res.scalar_one() or 0)
    enc_usd = Decimal(enc_usd_res.scalar_one() or 0)
    enc_cdf = Decimal(enc_cdf_res.scalar_one() or 0)
    sorties_usd = Decimal(sorties_usd_res.scalar_one() or 0)
    sorties_cdf = Decimal(sorties_cdf_res.scalar_one() or 0)
    appro_usd = Decimal(appro_usd_res.scalar_one() or 0)
    appro_cdf = Decimal(appro_cdf_res.scalar_one() or 0)
    transf_in_usd = await _transfert_sum("USD", as_destination=True)
    transf_in_cdf = await _transfert_sum("CDF", as_destination=True)
    transf_out_usd = await _transfert_sum("USD", as_destination=False)
    transf_out_cdf = await _transfert_sum("CDF", as_destination=False)
    retours_usd = await _retour_sum("USD")
    retours_cdf = await _retour_sum("CDF")

    caisse.solde_usd = (
        cash_init_usd + enc_usd + appro_usd + transf_in_usd + retours_usd
        - sorties_usd - transf_out_usd
    )
    caisse.solde_cdf = (
        cash_init_cdf + enc_cdf + appro_cdf + transf_in_cdf + retours_cdf
        - sorties_cdf - transf_out_cdf
    )
    return caisse


@router.post(
    "/soldes/recalculate",
    response_model=TreasuryOverviewOut,
    dependencies=[Depends(require_roles(["admin", "tresorerie", "comptabilite"]))],
)
async def recalculate_treasury_balances(
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TreasuryOverviewOut:
    caisse = await _recalculate_treasury_balances(tenant_id, db)
    await db.commit()
    caisse_out = TreasuryCaisseOut(
        solde_usd=caisse.solde_usd,
        solde_cdf=caisse.solde_cdf,
        derniere_maj=caisse.derniere_maj,
    )

    comptes_res = await db.execute(
        select(CompteBancaire)
        .options(selectinload(CompteBancaire.banque))
        .where(CompteBancaire.organisation_id == tenant_id)
        .where(CompteBancaire.account_type == "BANK")
        .order_by(CompteBancaire.id.asc())
    )
    comptes = [CompteBancaireOut.model_validate(c) for c in comptes_res.scalars().all()]
    return TreasuryOverviewOut(caisse=caisse_out, comptes=comptes)


@router.post(
    "/import-excel",
    dependencies=[Depends(require_roles(["admin", "tresorerie", "comptabilite"])), Depends(require_ai_enabled)],
)
async def import_and_classify(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from app.services.excel_parser import ExcelParser

    content = await file.read()
    raw_transactions = await ExcelParser.parse_bank_statement(content, filename=file.filename)
    enriched_data = await AIBatchProcessor.process_batch(raw_transactions[:50], db=db, org_id=user.organisation_id)
    return {"count": len(enriched_data), "data": enriched_data}


@router.post(
    "/confirm-classification",
    response_model=TreasuryConfirmClassificationResponse,
    dependencies=[Depends(require_roles(["admin", "tresorerie", "comptabilite"])), Depends(require_ai_enabled)],
)
async def confirm_classification(
    payload: TreasuryConfirmClassificationRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TreasuryConfirmClassificationResponse:
    await AIMemoryService.upsert_classification(
        label=payload.label.strip(),
        account=payload.account.strip(),
        org_id=user.organisation_id,
        db=db,
        confidence=payload.confidence_score,
    )
    return TreasuryConfirmClassificationResponse(status="Appris avec succès")
