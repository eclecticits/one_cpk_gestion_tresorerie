from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
import uuid
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import has_permission, get_current_user
from app.db.session import get_db
from app.models.budget import BudgetPoste
from app.models.encaissement import Encaissement
from app.models.requisition import Requisition
from app.models.service import Service
from app.models.service_rubrique import ServiceRubrique
from app.models.sortie_fonds import SortieFonds
from app.models.user import User
from app.schemas.budget import BudgetPosteSummary
from app.schemas.service import (
    ServiceOut,
    ServiceResponsableOut,
    ServiceConsumption,
    ServiceConsumptionItem,
    ServiceCreate,
    ServiceUpdate,
    ServiceRubriqueAssignRequest,
    ServiceResponsableAssignRequest,
)
from app.services.forecasting import PENDING_REQUISITION_STATUSES
from app.services.service_access import get_user_service_ids

router = APIRouter()


@router.get("", response_model=list[ServiceOut])
async def list_services(
    active: bool | None = Query(default=None, description="Filtrer sur les services actifs"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ServiceOut]:
    query = select(Service)
    if active is not None:
        query = query.where(Service.is_active.is_(active))
    if user.role != "admin":
        service_ids = await get_user_service_ids(db, user)
        if service_ids:
            query = query.where(Service.id.in_(service_ids))
        else:
            return []
    query = query.order_by(Service.code.asc())
    res = await db.execute(query)
    services = res.scalars().all()
    responsable_ids = {s.responsable_id for s in services if s.responsable_id}
    responsables: dict[str, User] = {}
    if responsable_ids:
        res_users = await db.execute(select(User).where(User.id.in_(responsable_ids)))
        for u in res_users.scalars().all():
            responsables[str(u.id)] = u
    return [
        ServiceOut(
            id=service.id,
            code=service.code,
            libelle=service.libelle,
            is_active=service.is_active,
            responsable_id=str(service.responsable_id) if service.responsable_id else None,
            responsable=(
                ServiceResponsableOut(
                    id=str(responsables[str(service.responsable_id)].id),
                    nom=responsables[str(service.responsable_id)].nom,
                    prenom=responsables[str(service.responsable_id)].prenom,
                    email=responsables[str(service.responsable_id)].email,
                )
                if service.responsable_id and str(service.responsable_id) in responsables
                else None
            ),
        )
        for service in services
    ]

@router.get("/{service_id}", response_model=ServiceOut)
async def get_service(
    service_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ServiceOut:
    if user.role != "admin":
        service_ids = await get_user_service_ids(db, user)
        if service_id not in service_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès interdit")
    res = await db.execute(select(Service).where(Service.id == service_id))
    service = res.scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service non trouvé")
    responsable = None
    if service.responsable_id:
        res_user = await db.execute(select(User).where(User.id == service.responsable_id))
        u = res_user.scalar_one_or_none()
        if u:
            responsable = ServiceResponsableOut(id=str(u.id), nom=u.nom, prenom=u.prenom, email=u.email)
    return ServiceOut(
        id=service.id,
        code=service.code,
        libelle=service.libelle,
        is_active=service.is_active,
        responsable_id=str(service.responsable_id) if service.responsable_id else None,
        responsable=responsable,
    )


@router.post("", response_model=ServiceOut, status_code=status.HTTP_201_CREATED)
async def create_service(
    payload: ServiceCreate,
    db: AsyncSession = Depends(get_db),
    user: object = Depends(has_permission("budget")),
) -> ServiceOut:
    code = payload.code.strip().upper()
    libelle = payload.libelle.strip()
    existing_res = await db.execute(select(Service).where(Service.code == code))
    if existing_res.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Code service déjà utilisé")
    service = Service(code=code, libelle=libelle, is_active=bool(payload.is_active))
    db.add(service)
    await db.commit()
    await db.refresh(service)
    return ServiceOut(id=service.id, code=service.code, libelle=service.libelle, is_active=service.is_active)


@router.put("/{service_id}/responsable", response_model=ServiceOut, dependencies=[Depends(has_permission("can_manage_users"))])
async def assign_service_responsable(
    service_id: int,
    payload: ServiceResponsableAssignRequest,
    db: AsyncSession = Depends(get_db),
) -> ServiceOut:
    res = await db.execute(select(Service).where(Service.id == service_id))
    service = res.scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service non trouvé")

    responsable = None
    if payload.user_id:
        try:
            uid = uuid.UUID(payload.user_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="user_id invalide")
        user_res = await db.execute(select(User).where(User.id == uid))
        responsable = user_res.scalar_one_or_none()
        if responsable is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur non trouvé")
        service.responsable_id = uid
    else:
        service.responsable_id = None

    await db.commit()
    await db.refresh(service)
    if responsable is None and service.responsable_id:
        res_user = await db.execute(select(User).where(User.id == service.responsable_id))
        responsable = res_user.scalar_one_or_none()

    return ServiceOut(
        id=service.id,
        code=service.code,
        libelle=service.libelle,
        is_active=service.is_active,
        responsable_id=str(service.responsable_id) if service.responsable_id else None,
        responsable=(
            ServiceResponsableOut(
                id=str(responsable.id),
                nom=responsable.nom,
                prenom=responsable.prenom,
                email=responsable.email,
            )
            if responsable
            else None
        ),
    )


@router.patch("/{service_id}", response_model=ServiceOut)
async def update_service(
    service_id: int,
    payload: ServiceUpdate,
    db: AsyncSession = Depends(get_db),
    user: object = Depends(has_permission("budget")),
) -> ServiceOut:
    res = await db.execute(select(Service).where(Service.id == service_id))
    service = res.scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service non trouvé")

    if payload.code is not None:
        code = payload.code.strip().upper()
        existing_res = await db.execute(
            select(Service).where(Service.code == code, Service.id != service_id)
        )
        if existing_res.scalar_one_or_none() is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Code service déjà utilisé")
        service.code = code
    if payload.libelle is not None:
        service.libelle = payload.libelle.strip()
    if payload.is_active is not None:
        service.is_active = payload.is_active

    await db.commit()
    await db.refresh(service)
    return ServiceOut(id=service.id, code=service.code, libelle=service.libelle, is_active=service.is_active)


@router.get("/{service_id}/consommation", response_model=ServiceConsumption)
async def get_service_consumption(
    service_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ServiceConsumption:
    if user.role != "admin":
        service_ids = await get_user_service_ids(db, user)
        if service_id not in service_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès interdit")
    service_res = await db.execute(select(Service).where(Service.id == service_id))
    service = service_res.scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service non trouvé")

    total_depenses_res = await db.execute(
        select(func.coalesce(func.sum(func.coalesce(SortieFonds.montant_paye, 0)), 0)).where(
            SortieFonds.service_id == service_id,
            (SortieFonds.statut.is_(None)) | (func.upper(SortieFonds.statut) == "VALIDE"),
        )
    )
    total_depenses = total_depenses_res.scalar_one() or 0

    total_budget_res = await db.execute(
        select(func.coalesce(func.sum(func.coalesce(BudgetPoste.montant_prevu, 0)), 0))
        .join(ServiceRubrique, ServiceRubrique.budget_poste_id == BudgetPoste.id)
        .where(
            ServiceRubrique.service_id == service_id,
            BudgetPoste.is_deleted.is_(False),
        )
    )
    total_budget_prevu = total_budget_res.scalar_one() or 0

    total_recettes_res = await db.execute(
        select(func.coalesce(func.sum(func.coalesce(Encaissement.montant_paye, 0)), 0)).where(
            Encaissement.service_id == service_id
        )
    )
    total_recettes = total_recettes_res.scalar_one() or 0

    pending_res = await db.execute(
        select(func.count())
        .select_from(Requisition)
        .where(
            Requisition.service_id == service_id,
            func.upper(Requisition.status).in_(PENDING_REQUISITION_STATUSES),
        )
    )
    requisitions_en_attente = int(pending_res.scalar_one() or 0)

    detail_res = await db.execute(
        select(
            BudgetPoste.id,
            BudgetPoste.code,
            BudgetPoste.libelle,
            func.coalesce(func.sum(func.coalesce(SortieFonds.montant_paye, 0)), 0).label("total_paye"),
        )
        .join(SortieFonds, SortieFonds.budget_poste_id == BudgetPoste.id)
        .where(
            SortieFonds.service_id == service_id,
            (SortieFonds.statut.is_(None)) | (func.upper(SortieFonds.statut) == "VALIDE"),
        )
        .group_by(BudgetPoste.id)
        .order_by(BudgetPoste.code)
    )
    detail_par_rubrique = [
        ServiceConsumptionItem(
            budget_poste_id=row.id,
            code=row.code,
            libelle=row.libelle,
            total_paye=row.total_paye or 0,
        )
        for row in detail_res.all()
    ]

    return ServiceConsumption(
        service_id=service_id,
        total_budget_prevu=total_budget_prevu,
        total_depenses=total_depenses,
        total_recettes=total_recettes,
        requisitions_en_attente=requisitions_en_attente,
        detail_par_rubrique=detail_par_rubrique,
    )


@router.get("/{service_id}/rubriques", response_model=list[BudgetPosteSummary])
async def list_service_rubriques(
    service_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[BudgetPosteSummary]:
    if user.role != "admin":
        service_ids = await get_user_service_ids(db, user)
        if service_id not in service_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès interdit")
    service_res = await db.execute(select(Service).where(Service.id == service_id))
    if service_res.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service non trouvé")

    res = await db.execute(
        select(BudgetPoste)
        .join(ServiceRubrique, ServiceRubrique.budget_poste_id == BudgetPoste.id)
        .where(
            ServiceRubrique.service_id == service_id,
            BudgetPoste.is_deleted.is_(False),
        )
        .order_by(BudgetPoste.code)
    )
    lignes = res.scalars().all()
    return [
        BudgetPosteSummary(
            id=line.id,
            code=line.code,
            libelle=line.libelle,
            parent_code=line.parent_code,
            parent_id=line.parent_id,
            type=line.type,
            active=line.active,
            montant_prevu=line.montant_prevu or 0,
            montant_engage=line.montant_engage or 0,
            montant_paye=line.montant_paye or 0,
            montant_disponible=(line.montant_prevu or 0) - (line.montant_engage or 0),
            pourcentage_consomme=0,
        )
        for line in lignes
    ]


@router.post("/{service_id}/rubriques")
async def assign_service_rubriques(
    service_id: int,
    payload: ServiceRubriqueAssignRequest,
    db: AsyncSession = Depends(get_db),
    user: object = Depends(has_permission("budget")),
) -> dict:
    service_res = await db.execute(select(Service).where(Service.id == service_id))
    if service_res.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service non trouvé")

    rubrique_ids = sorted({int(r) for r in payload.rubrique_ids if r is not None})
    if rubrique_ids:
        valid_res = await db.execute(
            select(BudgetPoste.id).where(BudgetPoste.id.in_(rubrique_ids), BudgetPoste.is_deleted.is_(False))
        )
        valid_ids = {row[0] for row in valid_res.all()}
        missing = [rid for rid in rubrique_ids if rid not in valid_ids]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Rubriques invalides: {', '.join(str(r) for r in missing)}",
            )

    await db.execute(delete(ServiceRubrique).where(ServiceRubrique.service_id == service_id))
    for rid in rubrique_ids:
        db.add(ServiceRubrique(service_id=service_id, budget_poste_id=rid))
    await db.commit()

    return {"ok": True, "rubrique_ids": rubrique_ids}
