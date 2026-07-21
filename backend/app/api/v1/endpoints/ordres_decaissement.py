from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_tenant_id,
    get_current_user,
)
from app.db.session import get_db
from app.models.ordre_decaissement import OrdreDecaissement
from app.models.print_settings import PrintSettings
from app.models.rbac import Permission, role_permissions
from app.models.requisition import Requisition
from app.models.sortie_fonds import SortieFonds
from app.models.user import User
from app.schemas.ordre_decaissement import (
    OrdreDecaissementCancel,
    OrdreDecaissementCreate,
    OrdreDecaissementListResponse,
    OrdreDecaissementOut,
)
from app.services.audit_service import get_request_ip, log_action
from app.services.document_sequences import generate_document_number

router = APIRouter()

# Statuts de réquisition permettant d'émettre / payer des ordres de décaissement
REQ_STATUTS_OD = {"APPROUVEE", "EN_DECAISSEMENT"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _is_admin(user: User) -> bool:
    return (user.role or "").lower() in {"admin", "super_admin"}


LIMITE_SORTIE_DIRECTE_USD = Decimal("100")


async def _user_has_permission(db: AsyncSession, user: User, permission_code: str) -> bool:
    if _is_admin(user):
        return True
    if not user.role_id:
        return False
    res = await db.execute(
        select(Permission.id)
        .join(role_permissions, role_permissions.c.permission_id == Permission.id)
        .where(role_permissions.c.role_id == user.role_id)
        .where(Permission.code == permission_code)
        .limit(1)
    )
    return res.scalar_one_or_none() is not None


def _user_info(user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {"id": str(user.id), "prenom": user.prenom, "nom": user.nom, "email": user.email}


def _ordre_out(
    ordre: OrdreDecaissement,
    *,
    requisition: Requisition | None = None,
    users_map: dict[uuid.UUID, User] | None = None,
    sortie_ref: str | None = None,
) -> dict[str, Any]:
    users_map = users_map or {}
    return {
        "id": str(ordre.id),
        "organisation_id": ordre.organisation_id,
        "requisition_id": str(ordre.requisition_id) if ordre.requisition_id else None,
        "numero_ordre": ordre.numero_ordre,
        "beneficiaire": ordre.beneficiaire,
        "montant": ordre.montant or 0,
        "devise": ordre.devise,
        "motif": ordre.motif,
        "service_id": ordre.service_id,
        "lignes": ordre.lignes,
        "statut": ordre.statut,
        "autorise_par": str(ordre.autorise_par) if ordre.autorise_par else None,
        "autorise_le": ordre.autorise_le,
        "autorise_par_user": _user_info(users_map.get(ordre.autorise_par)),
        "paye_par": str(ordre.paye_par) if ordre.paye_par else None,
        "paye_le": ordre.paye_le,
        "paye_par_user": _user_info(users_map.get(ordre.paye_par)),
        "sortie_fonds_id": str(ordre.sortie_fonds_id) if ordre.sortie_fonds_id else None,
        "sortie_reference_numero": sortie_ref,
        "annule_par": str(ordre.annule_par) if ordre.annule_par else None,
        "annule_le": ordre.annule_le,
        "motif_annulation": ordre.motif_annulation,
        "created_at": ordre.created_at,
        "requisition_numero": requisition.numero_requisition if requisition else None,
        "requisition_objet": requisition.objet if requisition else None,
        "requisition_montant_total": (requisition.montant_total or 0) if requisition else None,
        "requisition_status": requisition.status if requisition else None,
    }


async def _montants_engages(db: AsyncSession, requisition_id: uuid.UUID) -> tuple[Decimal, Decimal]:
    """Retourne (total payé, total autorisé non payé) pour une réquisition."""
    res = await db.execute(
        select(OrdreDecaissement.statut, func.coalesce(func.sum(OrdreDecaissement.montant), 0))
        .where(
            OrdreDecaissement.requisition_id == requisition_id,
            OrdreDecaissement.statut.in_(("AUTORISE", "PAYE")),
        )
        .group_by(OrdreDecaissement.statut)
    )
    total_paye = Decimal("0")
    total_autorise = Decimal("0")
    for statut, montant in res.all():
        if statut == "PAYE":
            total_paye = Decimal(montant or 0)
        elif statut == "AUTORISE":
            total_autorise = Decimal(montant or 0)
    return total_paye, total_autorise


@router.post("", response_model=OrdreDecaissementOut, status_code=status.HTTP_201_CREATED)
async def create_ordre_decaissement(
    payload: OrdreDecaissementCreate,
    request: Request,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Any:
    # --- Ordre de sortie directe (sans réquisition) : programmé par un
    # utilisateur habilité (can_direct_disbursement), payé par la caisse.
    if payload.requisition_id is None:
        if not await _user_has_permission(db, user, "can_direct_disbursement"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Privilèges insuffisants : programmer une sortie directe requiert "
                    "can_direct_disbursement (administrateur ou utilisateur habilité)"
                ),
            )
        montant_demande = Decimal(payload.montant or 0)
        if payload.devise == "USD":
            if montant_demande > LIMITE_SORTIE_DIRECTE_USD:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Sortie directe limitée à 100 USD : au-delà, créez une réquisition",
                )
        else:
            ps_res = await db.execute(
                select(PrintSettings).where(PrintSettings.organisation_id == tenant_id).limit(1)
            )
            ps = ps_res.scalar_one_or_none()
            rate = None
            if ps is not None:
                try:
                    rate = Decimal(str(ps.exchange_rate_cdf or ps.exchange_rate or 0))
                except (TypeError, ValueError, ArithmeticError):
                    rate = None
            if not rate or rate <= 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Taux de change indisponible : sortie directe en CDF impossible (plafond 100 USD)",
                )
            if montant_demande > LIMITE_SORTIE_DIRECTE_USD * rate:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Sortie directe limitée à l'équivalent de 100 USD ({LIMITE_SORTIE_DIRECTE_USD * rate:.2f} CDF)",
                )

        numero_ordre = await generate_document_number(db, "OD", tenant_id, service_id=None)
        ordre = OrdreDecaissement(
            organisation_id=tenant_id,
            requisition_id=None,
            numero_ordre=numero_ordre,
            beneficiaire=payload.beneficiaire.strip(),
            montant=payload.montant,
            devise=payload.devise,
            motif=payload.motif,
            service_id=payload.service_id,
            lignes=payload.lignes,
            statut="AUTORISE",
            autorise_par=user.id,
            autorise_le=_utcnow(),
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        db.add(ordre)
        await db.flush()

        await log_action(
            db,
            user_id=user.id,
            action="ORDRE_SORTIE_DIRECTE_AUTORISE",
            target_table="ordres_decaissement",
            target_id=str(ordre.id),
            new_value={
                "numero_ordre": numero_ordre,
                "beneficiaire": ordre.beneficiaire,
                "montant": float(ordre.montant or 0),
                "devise": ordre.devise,
                "motif": ordre.motif,
            },
            ip_address=get_request_ip(request),
        )
        await db.commit()
        await db.refresh(ordre)
        return _ordre_out(ordre, users_map={user.id: user})

    # --- Ordre lié à une réquisition à décaissement progressif.
    if not await _user_has_permission(db, user, "can_authorize_disbursement"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Privilèges insuffisants (can_authorize_disbursement)",
        )
    # Verrou sur la réquisition : garantit l'invariant de plafond en cas de
    # créations concurrentes.
    res = await db.execute(
        select(Requisition)
        .where(
            Requisition.id == payload.requisition_id,
            Requisition.organisation_id == tenant_id,
            Requisition.is_deleted.is_(False),
        )
        .with_for_update()
    )
    req = res.scalar_one_or_none()
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Réquisition introuvable")

    if not bool(req.decaissement_progressif):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cette réquisition n'est pas en mode décaissement progressif",
        )
    if (req.status or "").upper() not in REQ_STATUTS_OD:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La réquisition doit être approuvée avant d'autoriser un décaissement",
        )
    # Séparation des pouvoirs : seul le demandeur (ou un admin) autorise les tranches
    if not _is_admin(user) and (req.created_by is None or req.created_by != user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seul le demandeur de la réquisition peut autoriser un décaissement",
        )

    total_paye, total_autorise = await _montants_engages(db, req.id)
    plafond = Decimal(req.montant_total or 0)
    engage = total_paye + total_autorise
    if engage + Decimal(payload.montant) > plafond:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Plafond de la réquisition dépassé : montant total {plafond}, "
                f"déjà payé {total_paye}, autorisé en attente {total_autorise}, "
                f"reliquat disponible {plafond - engage}"
            ),
        )

    numero_ordre = await generate_document_number(db, "OD", tenant_id, service_id=req.service_id)
    ordre = OrdreDecaissement(
        organisation_id=tenant_id,
        requisition_id=req.id,
        numero_ordre=numero_ordre,
        beneficiaire=payload.beneficiaire.strip(),
        montant=payload.montant,
        devise=payload.devise,
        motif=payload.motif,
        statut="AUTORISE",
        autorise_par=user.id,
        autorise_le=_utcnow(),
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db.add(ordre)
    await db.flush()  # garantit ordre.id pour le journal d'audit

    await log_action(
        db,
        user_id=user.id,
        action="ORDRE_DECAISSEMENT_AUTORISE",
        target_table="ordres_decaissement",
        target_id=str(ordre.id),
        new_value={
            "numero_ordre": numero_ordre,
            "requisition_id": str(req.id),
            "numero_requisition": req.numero_requisition,
            "beneficiaire": ordre.beneficiaire,
            "montant": float(ordre.montant or 0),
            "devise": ordre.devise,
        },
        ip_address=get_request_ip(request),
    )
    await db.commit()
    await db.refresh(ordre)
    return _ordre_out(ordre, requisition=req, users_map={user.id: user})


@router.get("", response_model=OrdreDecaissementListResponse)
async def list_ordres_decaissement(
    requisition_id: str | None = Query(default=None),
    sans_requisition: bool | None = Query(default=None),
    statut: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Any:
    query = select(OrdreDecaissement).where(OrdreDecaissement.organisation_id == tenant_id)
    req: Requisition | None = None
    if requisition_id:
        try:
            req_uid = uuid.UUID(requisition_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id UUID")
        query = query.where(OrdreDecaissement.requisition_id == req_uid)
        req_res = await db.execute(
            select(Requisition).where(Requisition.id == req_uid, Requisition.organisation_id == tenant_id)
        )
        req = req_res.scalar_one_or_none()
    if sans_requisition:
        query = query.where(OrdreDecaissement.requisition_id.is_(None))
    if statut:
        query = query.where(OrdreDecaissement.statut == statut.upper())

    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar_one()
    res = await db.execute(query.order_by(OrdreDecaissement.created_at.desc()).limit(limit).offset(offset))
    ordres = list(res.scalars().all())

    # Enrichissements : utilisateurs, réquisitions, références de sortie
    user_ids = {u for o in ordres for u in (o.autorise_par, o.paye_par) if u}
    users_map: dict[uuid.UUID, User] = {}
    if user_ids:
        u_res = await db.execute(select(User).where(User.id.in_(user_ids)))
        users_map = {u.id: u for u in u_res.scalars().all()}

    req_map: dict[uuid.UUID, Requisition] = {req.id: req} if req else {}
    missing_req_ids = {o.requisition_id for o in ordres if o.requisition_id} - set(req_map)
    if missing_req_ids:
        r_res = await db.execute(select(Requisition).where(Requisition.id.in_(missing_req_ids)))
        req_map.update({r.id: r for r in r_res.scalars().all()})

    sortie_ids = {o.sortie_fonds_id for o in ordres if o.sortie_fonds_id}
    sortie_ref_map: dict[uuid.UUID, str | None] = {}
    if sortie_ids:
        s_res = await db.execute(
            select(SortieFonds.id, SortieFonds.reference_numero).where(SortieFonds.id.in_(sortie_ids))
        )
        sortie_ref_map = {row[0]: row[1] for row in s_res.all()}

    items = [
        _ordre_out(
            o,
            requisition=req_map.get(o.requisition_id) if o.requisition_id else None,
            users_map=users_map,
            sortie_ref=sortie_ref_map.get(o.sortie_fonds_id) if o.sortie_fonds_id else None,
        )
        for o in ordres
    ]

    montant_total_requisition = None
    total_paye = Decimal("0")
    total_autorise = Decimal("0")
    reliquat = None
    if req is not None:
        montant_total_requisition = Decimal(req.montant_total or 0)
        total_paye, total_autorise = await _montants_engages(db, req.id)
        reliquat = montant_total_requisition - total_paye - total_autorise

    return {
        "items": items,
        "total": total,
        "montant_total_requisition": montant_total_requisition,
        "total_paye": total_paye,
        "total_autorise_non_paye": total_autorise,
        "reliquat": reliquat,
    }


@router.post("/{ordre_id}/annuler", response_model=OrdreDecaissementOut)
async def annuler_ordre_decaissement(
    ordre_id: str,
    payload: OrdreDecaissementCancel,
    request: Request,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Any:
    try:
        oid = uuid.UUID(ordre_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid ordre_id UUID")

    res = await db.execute(
        select(OrdreDecaissement)
        .where(OrdreDecaissement.id == oid, OrdreDecaissement.organisation_id == tenant_id)
        .with_for_update()
    )
    ordre = res.scalar_one_or_none()
    if ordre is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ordre de décaissement introuvable")
    if ordre.statut != "AUTORISE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seul un ordre au statut AUTORISE peut être annulé",
        )
    if not _is_admin(user) and ordre.autorise_par != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seul l'auteur de l'autorisation (ou un admin) peut annuler cet ordre",
        )

    ordre.statut = "ANNULE"
    ordre.annule_par = user.id
    ordre.annule_le = _utcnow()
    ordre.motif_annulation = payload.motif_annulation
    ordre.updated_at = _utcnow()

    await log_action(
        db,
        user_id=user.id,
        action="ORDRE_DECAISSEMENT_ANNULE",
        target_table="ordres_decaissement",
        target_id=str(ordre.id),
        new_value={
            "numero_ordre": ordre.numero_ordre,
            "motif_annulation": payload.motif_annulation,
        },
        ip_address=get_request_ip(request),
    )
    await db.commit()
    await db.refresh(ordre)

    req = None
    if ordre.requisition_id:
        req_res = await db.execute(select(Requisition).where(Requisition.id == ordre.requisition_id))
        req = req_res.scalar_one_or_none()
    return _ordre_out(ordre, requisition=req, users_map={user.id: user})
