from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_current_tenant_id
from app.db.session import get_db
from app.models.budget import BudgetPoste
from app.models.ligne_requisition import LigneRequisition
from app.models.requisition import Requisition
from app.models.user import User
from app.schemas.requisition import (
    LigneRequisitionCreate,
    LigneRequisitionOut,
    LigneRequisitionUpdate,
)
from app.services.historical_snapshots import ensure_requisition_editable
from app.services.requisition_service import (
    appliquer_reglement_requisition,
    recaler_montant_total_depuis_lignes,
    requisition_exige_des_lignes,
)
from app.services.budget_engagement import (
    requisition_engage_le_budget,
    resynchroniser_engagements,
    resynchroniser_engagement_requisition,
    resynchroniser_engagement_requisitions,
)
from app.services.ligne_requisition_service import (
    build_ligne_requisition,
    can_force_budget_overrun,
)
from app.services.service_access import get_user_service_ids, can_view_all_services

router = APIRouter()


def _ligne_out(l: LigneRequisition, *, rubrique: str | None = None) -> LigneRequisitionOut:
    """Seul point de construction de `LigneRequisitionOut`.

    La liste reconstruisait sa propre réponse pour y injecter une rubrique
    recalculée. Les deux constructions ont fini par diverger : celle de la liste
    a oublié `mode_paiement` et `compte_bancaire_id`, si bien que le plan de
    décaissement ne voyait plus le volet bancaire des lignes et réclamait un
    compte à débiter sans option à proposer. `rubrique` est donc un paramètre,
    pas un motif de dupliquer le reste.
    """
    return LigneRequisitionOut(
        id=str(l.id),
        requisition_id=str(l.requisition_id),
        budget_poste_id=l.budget_poste_id,
        rubrique=rubrique if rubrique is not None else l.rubrique,
        description=l.description,
        quantite=l.quantite,
        montant_unitaire=l.montant_unitaire or 0,
        montant_total=l.montant_total or 0,
        devise=l.devise or "USD",
        mode_paiement=l.mode_paiement,
        compte_bancaire_id=l.compte_bancaire_id,
        budget_poste_code_snapshot=l.budget_poste_code_snapshot,
        budget_poste_libelle_snapshot=l.budget_poste_libelle_snapshot,
        montant_alloue_snapshot=l.montant_alloue_snapshot,
        montant_disponible_snapshot=l.montant_disponible_snapshot,
    )


@router.get("", response_model=list[LigneRequisitionOut])
async def list_lignes_requisition(
    requisition_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[LigneRequisitionOut]:
    query = select(LigneRequisition).where(LigneRequisition.organisation_id == tenant_id)
    if requisition_id:
        try:
            rid = uuid.UUID(requisition_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")
        query = query.where(LigneRequisition.requisition_id == rid)
        req_res = await db.execute(
            select(Requisition).where(Requisition.id == rid, Requisition.organisation_id == tenant_id)
        )
        requisition = req_res.scalar_one_or_none()
        if requisition is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")
        if not await can_view_all_services(db, user):
            service_ids = await get_user_service_ids(db, user)
            if service_ids and requisition.service_id not in service_ids:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Vous n'avez pas l'autorisation de consulter cette réquisition.",
                )
    elif not await can_view_all_services(db, user):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="requisition_id requis")
    res = await db.execute(query)
    lignes = res.scalars().all()
    missing_ids = {
        l.budget_poste_id
        for l in lignes
        if (not (l.rubrique or "").strip()) and l.budget_poste_id is not None
    }
    budget_map: dict[int, BudgetPoste] = {}
    if missing_ids:
        budget_res = await db.execute(select(BudgetPoste).where(BudgetPoste.id.in_(list(missing_ids))))
        budget_map = {b.id: b for b in budget_res.scalars().all()}

    outputs: list[LigneRequisitionOut] = []
    for l in lignes:
        rubrique_value = (l.rubrique or "").strip()
        if not rubrique_value and l.budget_poste_id is not None:
            budget_line = budget_map.get(l.budget_poste_id)
            if budget_line:
                if budget_line.code and budget_line.libelle:
                    rubrique_value = f"{budget_line.code} - {budget_line.libelle}"
                else:
                    rubrique_value = budget_line.code or budget_line.libelle or ""
        outputs.append(_ligne_out(l, rubrique=rubrique_value))
    return outputs


@router.post("", response_model=list[LigneRequisitionOut])
async def create_lignes_requisition(
    payload: list[LigneRequisitionCreate],
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[LigneRequisitionOut]:
    lignes: list[LigneRequisition] = []
    requisition_cache: dict[uuid.UUID, Requisition] = {}
    # Même périmètre que la création de la réquisition et que la liste des postes
    # autorisés : qui peut porter une réquisition sur un service doit pouvoir en
    # écrire les lignes. Restreindre au seul rôle "admin" produisait un 403 sur
    # un poste que le formulaire venait d'afficher comme valide.
    unrestricted = await can_view_all_services(db, user)
    force_overrun: bool | None = None
    # Cumul local des montants réservés par cet envoi : les lignes ne sont pas
    # encore engagées (cf. budget_engagement), le contrôle de disponibilité doit
    # néanmoins les décompter entre elles.
    engagements_en_cours: dict[int, Decimal] = {}
    for item in payload:
        if isinstance(item.requisition_id, uuid.UUID):
            rid = item.requisition_id
        else:
            try:
                rid = uuid.UUID(item.requisition_id)
            except ValueError:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")
        requisition = requisition_cache.get(rid)
        if requisition is None:
            req_res = await db.execute(
                select(Requisition).where(
                    Requisition.id == rid,
                    Requisition.organisation_id == tenant_id,
                    Requisition.is_deleted.is_(False),
                )
            )
            requisition = req_res.scalar_one_or_none()
            if requisition is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")
            requisition_cache[rid] = requisition
        ensure_requisition_editable(requisition, user=user, attempted_fields={"lignes_requisition"})
        if not unrestricted:
            service_ids = await get_user_service_ids(db, user)
            if service_ids and requisition.service_id not in service_ids:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Vous n'avez pas l'autorisation de modifier cette réquisition.",
                )
        if force_overrun is None:
            force_overrun = await can_force_budget_overrun(db, user)
        ligne = await build_ligne_requisition(
            db=db,
            requisition=requisition,
            item=item,
            tenant_id=tenant_id,
            force_overrun=force_overrun,
            engagements_en_cours=engagements_en_cours,
        )
        lignes.append(ligne)
        db.add(ligne)
    # Le mode porté par la réquisition est un résumé de ses lignes : l'ajout
    # d'une ligne d'un autre mode le fait basculer en « mixte » et impose le
    # décaissement progressif.
    if lignes:
        await db.flush()
        for requisition in requisition_cache.values():
            await appliquer_reglement_requisition(db, requisition)
            await recaler_montant_total_depuis_lignes(db, requisition)
        # Une ligne ajoutée à une réquisition déjà soumise à l'examen alourdit
        # son engagement : on recale les postes touchés.
        await resynchroniser_engagement_requisitions(db, list(requisition_cache.values()))
    await db.commit()
    for ligne in lignes:
        await db.refresh(ligne)
    return [_ligne_out(l) for l in lignes]


async def _ligne_et_requisition(
    ligne_id: str,
    *,
    db: AsyncSession,
    user: User,
    tenant_id: int,
    champ: str,
) -> tuple[LigneRequisition, Requisition]:
    """Charge la ligne, sa réquisition, et applique les deux mêmes gardes que
    l'ajout : le verrou d'édition de la pièce, puis le périmètre de service."""
    try:
        lid = uuid.UUID(ligne_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid ligne_id")

    res = await db.execute(
        select(LigneRequisition).where(
            LigneRequisition.id == lid,
            LigneRequisition.organisation_id == tenant_id,
        )
    )
    ligne = res.scalar_one_or_none()
    if ligne is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ligne introuvable")

    req_res = await db.execute(
        select(Requisition).where(
            Requisition.id == ligne.requisition_id,
            Requisition.organisation_id == tenant_id,
            Requisition.is_deleted.is_(False),
        )
    )
    requisition = req_res.scalar_one_or_none()
    if requisition is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")

    ensure_requisition_editable(requisition, user=user, attempted_fields={champ})

    if not await can_view_all_services(db, user):
        service_ids = await get_user_service_ids(db, user)
        if service_ids and requisition.service_id not in service_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Vous n'avez pas l'autorisation de modifier cette réquisition.",
            )
    return ligne, requisition


async def _recaler_postes(
    db: AsyncSession, requisition: Requisition, postes_liberes: set[int]
) -> None:
    """Recale les engagements, y compris ceux des postes que la réquisition ne
    touche plus : `postes_de_requisition` ne voit que les lignes restantes, et
    un poste quitté resterait gelé sur un montant qui n'existe plus."""
    await db.flush()
    await resynchroniser_engagement_requisition(db, requisition)
    orphelins = sorted(pid for pid in postes_liberes if pid is not None)
    if orphelins:
        await resynchroniser_engagements(
            db, tenant_id=requisition.organisation_id, poste_ids=orphelins
        )


@router.put("/{ligne_id}", response_model=LigneRequisitionOut)
async def update_ligne_requisition(
    ligne_id: str,
    payload: LigneRequisitionUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> LigneRequisitionOut:
    ligne, requisition = await _ligne_et_requisition(
        ligne_id, db=db, user=user, tenant_id=tenant_id, champ="ligne_requisition"
    )

    ancien_poste = ligne.budget_poste_id
    ancien_montant = Decimal(ligne.montant_total or 0)

    # La ligne corrigée ne doit pas se heurter à son propre engagement : s'il
    # est déjà posé sur le même poste, on le lui rend avant de mesurer.
    engagements_en_cours: dict[int, Decimal] = {}
    if (
        ancien_poste is not None
        and ancien_poste == payload.budget_poste_id
        and requisition_engage_le_budget(requisition)
    ):
        engagements_en_cours[ancien_poste] = -ancien_montant

    force_overrun = await can_force_budget_overrun(db, user)
    # Une ligne corrigée repasse par les contrôles de sa création : poste actif,
    # rubrique autorisée au service, disponible suffisant, règlement résolu.
    modele = await build_ligne_requisition(
        db=db,
        requisition=requisition,
        item=payload,
        tenant_id=tenant_id,
        force_overrun=force_overrun,
        engagements_en_cours=engagements_en_cours,
    )

    for champ in (
        "budget_poste_id",
        "rubrique",
        "description",
        "quantite",
        "montant_unitaire",
        "montant_total",
        "devise",
        "mode_paiement",
        "compte_bancaire_id",
        "budget_poste_code_snapshot",
        "budget_poste_libelle_snapshot",
        "montant_alloue_snapshot",
        "montant_disponible_snapshot",
    ):
        setattr(ligne, champ, getattr(modele, champ))

    await db.flush()
    await appliquer_reglement_requisition(db, requisition)
    await recaler_montant_total_depuis_lignes(db, requisition)
    libere = {ancien_poste} if ancien_poste != ligne.budget_poste_id else set()
    await _recaler_postes(db, requisition, libere)
    await db.commit()
    await db.refresh(ligne)
    return _ligne_out(ligne)


# `response_model=None` : sans lui, FastAPI déduit un modèle de
# l'annotation de retour et refuse un corps sur un 204.
@router.delete("/{ligne_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_ligne_requisition(
    ligne_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> None:
    ligne, requisition = await _ligne_et_requisition(
        ligne_id, db=db, user=user, tenant_id=tenant_id, champ="ligne_requisition"
    )

    # Une réquisition budgétaire est portée par ses lignes : la dernière ne se
    # retire pas, sinon la pièce n'autorise plus rien tout en restant en course.
    restantes = await db.scalar(
        select(func.count(LigneRequisition.id)).where(
            LigneRequisition.requisition_id == requisition.id,
            LigneRequisition.id != ligne.id,
        )
    )
    if requisition_exige_des_lignes(requisition) and not restantes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dernière ligne : une réquisition budgétaire ne peut pas rester sans ligne.",
        )

    poste_libere = ligne.budget_poste_id
    await db.delete(ligne)
    await db.flush()
    await appliquer_reglement_requisition(db, requisition)
    await recaler_montant_total_depuis_lignes(db, requisition)
    await _recaler_postes(db, requisition, {poste_libere} if poste_libere else set())
    await db.commit()
