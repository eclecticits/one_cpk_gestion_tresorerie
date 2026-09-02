"""Retours en trésorerie : remboursement de fonds après une sortie de fonds.

Le retour recrédite la caisse OU un compte bancaire (`canal`) : le vocabulaire
visible dit donc « trésorerie ». Les identifiants techniques (table, route,
modèle) gardent leur nom d'origine `retour_caisse`.

Cas d'usage principal — le **reliquat d'une avance « à valoir »** : un agent a
reçu une avance (sortie de fonds), en a dépensé une partie et rend le solde non
utilisé. Couvre aussi la **correction** d'une sortie erronée hors fenêtre
d'annulation, et le **trop-perçu** rendu par un bénéficiaire.

Effets d'un retour VALIDE :
- la trésorerie de destination (caisse ou compte bancaire) est **créditée** ;
- l'imputation budgétaire de la sortie d'origine est **réduite** du montant rendu ;
- une écriture comptable inverse (D Trésorerie / C Charge) est générée si le
  module Comptabilité est en intégration automatique.

Le montant cumulé des retours d'une sortie ne peut pas dépasser le montant
décaissé. L'annulation d'un retour (fenêtre de 30 min) rétablit intégralement
la trésorerie, le budget et la comptabilité.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_current_tenant_id, has_permission
from app.db.session import get_db
from app.models.budget import BudgetPoste
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.requisition import Requisition
from app.models.retour_caisse import RetourCaisse
from app.models.sortie_fonds import SortieFonds
from app.models.user import User
# Réutilise les helpers de trésorerie/budget des sorties de fonds (source unique
# de vérité pour la conversion budgétaire et l'accès à la caisse).
from app.api.v1.endpoints.sorties_fonds import _get_or_create_caisse, _to_budget_currency
from app.modules.comptabilite.services.generation_service import (
    annuler_ecriture_operation,
    generer_ecriture_retour_caisse,
)
from app.modules.comptabilite.services.integration_mode import (
    STATUT_A_COMPTABILISER_MANUELLEMENT,
    STATUT_COMPTABILISEE,
    get_accounting_integration_mode,
    is_accounting_automatic,
    status_for_recorded_operation,
)
from app.schemas.retour_caisse import (
    RetourCaisseCreate,
    RetourCaisseOut,
    RetourCaisseStatusUpdate,
    RetoursCaisseListResponse,
)
from app.services.audit_service import get_request_ip, log_action
from app.services.document_sequences import generate_document_number
from app.services.report_cache import invalidate_report_summary_cache

logger = logging.getLogger("onec_cpk_api.retours_caisse")

router = APIRouter()

# Une sortie qui n'est pas une vraie dépense (transfert interne caisse <-> banque)
# n'a pas de reliquat à rendre : un retour n'a pas de sens.
TRANSFERT_TYPES = ("versement_banque", "approvisionnement_caisse")
ANNULATION_WINDOW = timedelta(minutes=30)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _user_info(user: User | None) -> dict[str, Any] | None:
    if not user:
        return None
    return {"id": str(user.id), "prenom": user.prenom, "nom": user.nom, "email": user.email}


def _retour_out(retour: RetourCaisse, *, creator: User | None = None) -> RetourCaisseOut:
    return RetourCaisseOut(
        id=retour.id,
        organisation_id=retour.organisation_id,
        sortie_fonds_id=retour.sortie_fonds_id,
        requisition_id=retour.requisition_id,
        type_retour=retour.type_retour,
        budget_poste_id=retour.budget_poste_id,
        budget_poste_code=retour.budget_poste_code,
        budget_poste_libelle=retour.budget_poste_libelle,
        ajuste_budget=retour.ajuste_budget,
        service_id=retour.service_id,
        montant=retour.montant or Decimal("0"),
        devise=retour.devise,
        canal=retour.canal,
        compte_bancaire_id=retour.compte_bancaire_id,
        mode=retour.mode,
        reference=retour.reference,
        reference_numero=retour.reference_numero,
        motif=retour.motif,
        commentaire=retour.commentaire,
        piece_justificative=retour.piece_justificative,
        exchange_rate_snapshot=retour.exchange_rate_snapshot,
        date_retour=retour.date_retour,
        statut=retour.statut or "VALIDE",
        statut_comptabilisation=getattr(retour, "statut_comptabilisation", "NON_COMPTABILISEE"),
        message_comptabilisation=retour.message_comptabilisation,
        motif_annulation=retour.motif_annulation,
        annulee_le=retour.annulee_le,
        annulee_par_id=retour.annulee_par_id,
        ancien_statut=retour.ancien_statut,
        created_by=retour.created_by,
        created_by_user=_user_info(creator),
        created_at=retour.created_at,
    )


async def _total_retourne(db: AsyncSession, tenant_id: int, sortie_id: uuid.UUID) -> Decimal:
    """Somme des retours VALIDES déjà enregistrés pour une sortie."""
    res = await db.execute(
        select(func.coalesce(func.sum(RetourCaisse.montant), 0)).where(
            RetourCaisse.organisation_id == tenant_id,
            RetourCaisse.sortie_fonds_id == sortie_id,
            RetourCaisse.statut == "VALIDE",
        )
    )
    return Decimal(str(res.scalar_one() or 0))


@router.post("", response_model=RetourCaisseOut, status_code=status.HTTP_201_CREATED)
async def create_retour_caisse(
    payload: RetourCaisseCreate,
    request: Request,
    user: User = Depends(has_permission("can_execute_payment")),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> RetourCaisseOut:
    # --- Sortie d'origine (verrouillée) -----------------------------------
    res = await db.execute(
        select(SortieFonds)
        .where(SortieFonds.id == payload.sortie_fonds_id, SortieFonds.organisation_id == tenant_id)
        .with_for_update()
    )
    sortie = res.scalar_one_or_none()
    if sortie is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sortie de fonds introuvable")
    if (sortie.statut or "VALIDE").upper() != "VALIDE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La sortie de fonds d'origine doit être valide (une sortie annulée n'a rien à rendre).",
        )
    if (sortie.type_sortie or "").lower() in TRANSFERT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Un transfert interne (versement / approvisionnement) ne peut pas faire l'objet d'un retour en trésorerie.",
        )

    # --- Devise : imposée par la sortie -----------------------------------
    devise = (payload.devise or sortie.devise or "USD").upper()
    if devise != (sortie.devise or "USD").upper():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La devise du retour doit être identique à celle de la sortie de fonds.",
        )

    # --- Canal de destination (par défaut celui de la sortie) -------------
    canal = (payload.canal or sortie.canal or "CAISSE").upper()
    if canal not in {"CAISSE", "BANQUE"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="canal invalide")

    compte_bancaire: CompteBancaire | None = None
    compte_bancaire_id: int | None = None
    if canal == "BANQUE":
        compte_bancaire_id = payload.compte_bancaire_id or sortie.compte_bancaire_id
        if compte_bancaire_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="compte_bancaire_id requis pour un retour par canal BANQUE",
            )

    montant = Decimal(payload.montant)
    if montant <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le montant doit être strictement positif")

    # --- Garde-fou : pas plus que ce qui a été décaissé -------------------
    deja_rendu = await _total_retourne(db, tenant_id, sortie.id)
    reste = Decimal(sortie.montant_paye or 0) - deja_rendu
    if montant > reste:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Retour supérieur au reste dû : décaissé {sortie.montant_paye} {devise}, "
                f"déjà rendu {deja_rendu}, reste {reste}."
            ),
        )

    date_retour = _parse_datetime(str(payload.date_retour)) if payload.date_retour else None
    if date_retour is None:
        date_retour = datetime.now(timezone.utc)

    # --- Créditer la trésorerie de destination ----------------------------
    if canal == "CAISSE":
        caisse = await _get_or_create_caisse(db, tenant_id)
        res = await db.execute(
            select(CaisseCentrale)
            .where(CaisseCentrale.id == caisse.id, CaisseCentrale.organisation_id == tenant_id)
            .with_for_update()
        )
        caisse = res.scalar_one()
        if not caisse.est_ouverte:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Caisse fermée : ouvrez la caisse avant d'enregistrer un retour.",
            )
        if devise == "USD":
            caisse.solde_usd = (caisse.solde_usd or 0) + montant
        else:
            caisse.solde_cdf = (caisse.solde_cdf or 0) + montant
        caisse.derniere_maj = datetime.now(timezone.utc)
    else:
        res = await db.execute(
            select(CompteBancaire)
            .where(
                CompteBancaire.id == compte_bancaire_id,
                CompteBancaire.organisation_id == tenant_id,
            )
            .with_for_update()
        )
        compte_bancaire = res.scalar_one_or_none()
        if compte_bancaire is None or compte_bancaire.is_active is False:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="compte_bancaire_id invalide")
        if (compte_bancaire.devise or "").upper() != devise:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="devise incompatible avec le compte bancaire")
        if (compte_bancaire.account_type or "BANK").upper() != "BANK":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le compte de destination doit être un compte bancaire")
        compte_bancaire.solde_actuel = (compte_bancaire.solde_actuel or 0) + montant

    # --- Réduire l'imputation budgétaire de la sortie d'origine -----------
    budget_poste_id = payload.budget_poste_id or sortie.budget_poste_id
    budget_poste_code: str | None = None
    budget_poste_libelle: str | None = None
    ajuste_budget = bool(payload.ajuste_budget) and budget_poste_id is not None
    if ajuste_budget:
        res = await db.execute(
            select(BudgetPoste)
            .where(BudgetPoste.id == budget_poste_id, BudgetPoste.is_deleted.is_(False))
            .with_for_update()
        )
        budget_poste = res.scalar_one_or_none()
        if budget_poste is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="budget_poste_id invalide")
        budget_poste_code = budget_poste.code
        budget_poste_libelle = budget_poste.libelle
        montant_budget = await _to_budget_currency(
            db, tenant_id, montant, devise, exchange_rate_snapshot=sortie.exchange_rate_snapshot
        )
        budget_poste.montant_paye = max(Decimal("0"), (budget_poste.montant_paye or 0) - montant_budget)

    # --- Numéro de document (RET-...) -------------------------------------
    reference_numero = await generate_document_number(db, "RET", tenant_id, service_id=sortie.service_id)

    retour = RetourCaisse(
        organisation_id=tenant_id,
        sortie_fonds_id=sortie.id,
        requisition_id=sortie.requisition_id,
        type_retour=payload.type_retour,
        budget_poste_id=budget_poste_id if ajuste_budget else (payload.budget_poste_id or sortie.budget_poste_id),
        budget_poste_code=budget_poste_code,
        budget_poste_libelle=budget_poste_libelle,
        ajuste_budget=ajuste_budget,
        service_id=sortie.service_id,
        montant=montant,
        devise=devise,
        canal=canal,
        compte_bancaire_id=compte_bancaire_id,
        mode=payload.mode or "cash",
        reference=payload.reference,
        reference_numero=reference_numero,
        motif=(payload.motif or None),
        commentaire=payload.commentaire,
        piece_justificative=payload.piece_justificative,
        exchange_rate_snapshot=sortie.exchange_rate_snapshot,
        date_retour=date_retour,
        statut="VALIDE",
        created_by=user.id,
    )
    db.add(retour)
    await db.flush()

    # --- Écriture comptable inverse (module opt-in) -----------------------
    integration_mode = await get_accounting_integration_mode(db, tenant_id)
    retour.statut_comptabilisation = status_for_recorded_operation(integration_mode)
    if integration_mode == "manual":
        retour.message_comptabilisation = "Écriture comptable à saisir manuellement."
    elif integration_mode == "automatic":
        if ajuste_budget and budget_poste_id is not None:
            libelle_ecriture = retour.motif or f"Retour en trésorerie {reference_numero}"
            try:
                await generer_ecriture_retour_caisse(
                    db,
                    organisation_id=tenant_id,
                    retour_caisse_id=str(retour.id),
                    date_operation=date_retour.date(),
                    montant=montant,
                    devise=devise,
                    canal=canal,
                    compte_bancaire_id=compte_bancaire_id,
                    budget_poste_id=budget_poste_id,
                    libelle=libelle_ecriture,
                    created_by=user.id,
                )
                retour.statut_comptabilisation = STATUT_COMPTABILISEE
            except HTTPException as exc:
                raise HTTPException(
                    status_code=exc.status_code,
                    detail=(
                        "Impossible de générer l'écriture comptable du retour en trésorerie. "
                        f"{exc.detail} Paramètres > Comptabilité > Mode d'intégration comptable."
                    ),
                ) from exc
        else:
            # Sans réduction d'imputation budgétaire, la contrepartie du crédit de
            # trésorerie n'est pas un compte de charge résolvable automatiquement :
            # l'écriture est laissée à la saisie manuelle pour rester cohérente.
            retour.statut_comptabilisation = STATUT_A_COMPTABILISER_MANUELLEMENT
            retour.message_comptabilisation = (
                "Retour sans ajustement budgétaire : écriture à saisir manuellement."
            )

    await log_action(
        db,
        user_id=user.id,
        action="RETOUR_CAISSE_CREATED",
        target_table="retours_caisse",
        target_id=str(retour.id),
        new_value={
            "sortie_fonds_id": str(sortie.id),
            "montant": float(montant),
            "devise": devise,
            "canal": canal,
            "type_retour": retour.type_retour,
            "reference_numero": reference_numero,
        },
        ip_address=get_request_ip(request),
    )
    await db.commit()
    await invalidate_report_summary_cache(tenant_id)
    await db.refresh(retour)
    return _retour_out(retour, creator=user)


@router.get("", response_model=list[RetourCaisseOut] | RetoursCaisseListResponse)
async def list_retours_caisse(
    sortie_fonds_id: str | None = Query(default=None),
    requisition_id: str | None = Query(default=None),
    type_retour: str | None = Query(default=None),
    statut: str | None = Query(default=None),
    date_debut: str | None = Query(default=None),
    date_fin: str | None = Query(default=None),
    include_summary: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[RetourCaisseOut] | RetoursCaisseListResponse:
    conditions = [RetourCaisse.organisation_id == tenant_id]

    sortie_uid: uuid.UUID | None = None
    if sortie_fonds_id:
        try:
            sortie_uid = uuid.UUID(sortie_fonds_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="sortie_fonds_id invalide")
        conditions.append(RetourCaisse.sortie_fonds_id == sortie_uid)
    if requisition_id:
        try:
            conditions.append(RetourCaisse.requisition_id == uuid.UUID(requisition_id))
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="requisition_id invalide")
    if type_retour:
        conditions.append(RetourCaisse.type_retour == type_retour)

    if statut:
        statut_value = statut.strip().upper()
        if statut_value != "ALL":
            conditions.append(RetourCaisse.statut == statut_value)
    else:
        conditions.append(RetourCaisse.statut == "VALIDE")

    start_dt = _parse_datetime(date_debut)
    end_dt = _parse_datetime(date_fin)
    if start_dt:
        conditions.append(RetourCaisse.date_retour >= start_dt)
    if end_dt:
        conditions.append(RetourCaisse.date_retour <= end_dt)

    query = (
        select(RetourCaisse)
        .where(*conditions)
        .order_by(RetourCaisse.date_retour.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(query)).scalars().all()

    creators: dict[uuid.UUID, User] = {}
    creator_ids = {r.created_by for r in rows if r.created_by}
    if creator_ids:
        u_res = await db.execute(
            select(User).where(User.id.in_(list(creator_ids)), User.organisation_id == tenant_id)
        )
        creators = {u.id: u for u in u_res.scalars().all()}

    items = [_retour_out(r, creator=creators.get(r.created_by) if r.created_by else None) for r in rows]

    if not include_summary:
        return items

    count = int(
        (await db.execute(select(func.count()).select_from(RetourCaisse).where(*conditions))).scalar_one() or 0
    )
    total_montant = Decimal(
        str(
            (
                await db.execute(
                    select(func.coalesce(func.sum(RetourCaisse.montant), 0)).where(*conditions)
                )
            ).scalar_one()
            or 0
        )
    )

    sortie_montant_paye = total_retourne = reste = None
    if sortie_uid is not None:
        res = await db.execute(
            select(SortieFonds.montant_paye).where(
                SortieFonds.id == sortie_uid, SortieFonds.organisation_id == tenant_id
            )
        )
        montant_paye = res.scalar_one_or_none()
        if montant_paye is not None:
            sortie_montant_paye = Decimal(str(montant_paye))
            total_retourne = await _total_retourne(db, tenant_id, sortie_uid)
            reste = sortie_montant_paye - total_retourne

    return RetoursCaisseListResponse(
        items=items,
        total=count,
        total_montant=total_montant,
        sortie_montant_paye=sortie_montant_paye,
        total_retourne=total_retourne,
        reste_a_justifier=reste,
    )


@router.patch("/{retour_id}/statut", response_model=RetourCaisseOut)
async def update_retour_statut(
    retour_id: str,
    payload: RetourCaisseStatusUpdate,
    request: Request,
    user: User = Depends(has_permission("can_execute_payment")),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> RetourCaisseOut:
    try:
        retour_uid = uuid.UUID(retour_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="retour_id invalide")

    res = await db.execute(
        select(RetourCaisse)
        .where(RetourCaisse.id == retour_uid, RetourCaisse.organisation_id == tenant_id)
        .with_for_update()
    )
    retour = res.scalar_one_or_none()
    if retour is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Retour introuvable")

    previous_statut = (retour.statut or "VALIDE").strip().upper()
    statut = (payload.statut or "").strip().upper()
    if statut != "ANNULEE":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Statut invalide (ANNULEE uniquement)")
    if previous_statut == "ANNULEE":
        return _retour_out(retour)

    now = datetime.now(timezone.utc)
    reference_time = retour.created_at or retour.date_retour
    if reference_time is not None:
        if reference_time.tzinfo is None:
            reference_time = reference_time.replace(tzinfo=timezone.utc)
        if now - reference_time > ANNULATION_WINDOW:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Annulation impossible après 30 minutes",
            )

    montant = Decimal(retour.montant or 0)

    # --- Rétablir l'imputation budgétaire (re-débiter la charge) ----------
    if retour.ajuste_budget and retour.budget_poste_id:
        res = await db.execute(
            select(BudgetPoste).where(BudgetPoste.id == retour.budget_poste_id).with_for_update()
        )
        budget_poste = res.scalar_one_or_none()
        if budget_poste is not None:
            montant_budget = await _to_budget_currency(
                db, tenant_id, montant, retour.devise, exchange_rate_snapshot=retour.exchange_rate_snapshot
            )
            budget_poste.montant_paye = (budget_poste.montant_paye or 0) + montant_budget

    # --- Re-débiter la trésorerie (annuler le crédit du retour) -----------
    if retour.canal == "CAISSE":
        caisse = await _get_or_create_caisse(db, tenant_id)
        res = await db.execute(
            select(CaisseCentrale)
            .where(CaisseCentrale.id == caisse.id, CaisseCentrale.organisation_id == tenant_id)
            .with_for_update()
        )
        caisse = res.scalar_one()
        solde_courant = (caisse.solde_usd if retour.devise == "USD" else caisse.solde_cdf) or 0
        if montant > solde_courant:
            logger.warning(
                "Annulation retour %s : solde caisse %s insuffisant pour re-débiter %s. Tronqué à 0.",
                retour.reference_numero, solde_courant, montant,
            )
        if retour.devise == "USD":
            caisse.solde_usd = max(Decimal("0"), Decimal(str(solde_courant)) - montant)
        else:
            caisse.solde_cdf = max(Decimal("0"), Decimal(str(solde_courant)) - montant)
        caisse.derniere_maj = now
    elif retour.compte_bancaire_id is not None:
        res = await db.execute(
            select(CompteBancaire)
            .where(
                CompteBancaire.id == retour.compte_bancaire_id,
                CompteBancaire.organisation_id == tenant_id,
            )
            .with_for_update()
        )
        compte = res.scalar_one_or_none()
        if compte is not None:
            solde_courant = compte.solde_actuel or 0
            if montant > solde_courant:
                logger.warning(
                    "Annulation retour %s : solde banque %s insuffisant pour re-débiter %s. Tronqué à 0.",
                    retour.reference_numero, solde_courant, montant,
                )
            compte.solde_actuel = max(Decimal("0"), Decimal(str(solde_courant)) - montant)

    # --- Contre-passer l'écriture comptable du retour ---------------------
    if await is_accounting_automatic(db, tenant_id):
        motif_compta = (payload.motif_annulation or "").strip() or f"Annulation du retour en trésorerie {retour.reference_numero}"
        await annuler_ecriture_operation(
            db,
            organisation_id=tenant_id,
            module_origine="retours_caisse",
            type_origine="retour_caisse",
            objet_origine_id=str(retour.id),
            motif=motif_compta,
            user_id=user.id,
            date_annulation=now.date(),
        )

    retour.statut = "ANNULEE"
    retour.motif_annulation = (payload.motif_annulation or "").strip() or None
    retour.annulee_le = now
    retour.annulee_par_id = user.id
    retour.annulation_ip = get_request_ip(request)
    retour.ancien_statut = previous_statut

    await log_action(
        db,
        user_id=user.id,
        action="RETOUR_CAISSE_CANCELLED",
        target_table="retours_caisse",
        target_id=str(retour.id),
        old_value={"statut": previous_statut},
        new_value={"statut": retour.statut, "motif_annulation": retour.motif_annulation},
        ip_address=get_request_ip(request),
    )
    await db.commit()
    await invalidate_report_summary_cache(tenant_id)
    await db.refresh(retour)
    return _retour_out(retour)
