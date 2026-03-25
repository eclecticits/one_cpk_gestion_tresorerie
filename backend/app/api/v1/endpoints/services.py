from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
import uuid
from sqlalchemy import delete, func, select, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import has_permission, get_current_user, get_current_tenant_id
from app.db.session import get_db
from app.models.budget import BudgetPoste
from app.models.encaissement import Encaissement
from app.models.requisition import Requisition
from app.models.service import Service
from app.models.commission_member import CommissionMember, CommissionRole, utcnow as commission_member_utcnow
from app.models.expert_comptable import ExpertComptable
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
from app.schemas.commission_member import CommissionMemberLookupOut, CommissionMemberMultiAssign
from app.schemas.commission_member import (
    CommissionMemberCreate,
    CommissionMemberOut,
    CommissionMemberUpdate,
    CommissionMemberUserOut,
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
    if user.role not in {"admin", "super_admin"}:
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
    if user.role not in {"admin", "super_admin"}:
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
    tenant_id: int = Depends(get_current_tenant_id),
) -> ServiceOut:
    code = payload.code.strip().upper()
    libelle = payload.libelle.strip()
    existing_res = await db.execute(
        select(Service).where(Service.code == code, Service.organisation_id == tenant_id)
    )
    if existing_res.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Code service déjà utilisé")
    service = Service(code=code, libelle=libelle, is_active=bool(payload.is_active), organisation_id=tenant_id)
    db.add(service)
    await db.commit()
    await db.refresh(service)
    return ServiceOut(id=service.id, code=service.code, libelle=service.libelle, is_active=service.is_active)


@router.put("/{service_id}/responsable", response_model=ServiceOut, dependencies=[Depends(has_permission("can_manage_users"))])
async def assign_service_responsable(
    service_id: int,
    payload: ServiceResponsableAssignRequest,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> ServiceOut:
    res = await db.execute(
        select(Service).where(Service.id == service_id, Service.organisation_id == tenant_id)
    )
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
    tenant_id: int = Depends(get_current_tenant_id),
) -> ServiceOut:
    res = await db.execute(
        select(Service).where(Service.id == service_id, Service.organisation_id == tenant_id)
    )
    service = res.scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service non trouvé")

    if payload.code is not None:
        code = payload.code.strip().upper()
        existing_res = await db.execute(
            select(Service).where(
                Service.code == code,
                Service.id != service_id,
                Service.organisation_id == tenant_id,
            )
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
    tenant_id: int = Depends(get_current_tenant_id),
) -> ServiceConsumption:
    if user.role not in {"admin", "super_admin"}:
        service_ids = await get_user_service_ids(db, user)
        if service_id not in service_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès interdit")
    service_res = await db.execute(
        select(Service).where(Service.id == service_id, Service.organisation_id == tenant_id)
    )
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
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[BudgetPosteSummary]:
    if user.role not in {"admin", "super_admin"}:
        service_ids = await get_user_service_ids(db, user)
        if service_id not in service_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès interdit")
    service_res = await db.execute(
        select(Service).where(Service.id == service_id, Service.organisation_id == tenant_id)
    )
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
    tenant_id: int = Depends(get_current_tenant_id),
) -> dict:
    service_res = await db.execute(
        select(Service).where(Service.id == service_id, Service.organisation_id == tenant_id)
    )
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


def _member_user_out(user: User | None) -> CommissionMemberUserOut | None:
    if user is None:
        return None
    return CommissionMemberUserOut(
        id=str(user.id),
        nom=user.nom,
        prenom=user.prenom,
        email=user.email,
    )


def _coerce_role(role: CommissionRole | str | None) -> CommissionRole:
    if role is None:
        return CommissionRole.MEMBRE
    if isinstance(role, CommissionRole):
        return role
    raw = str(role)
    if raw.startswith("CommissionRole."):
        raw = raw.split(".", 1)[1]
    return CommissionRole(raw)


async def _ensure_service_access(service_id: int, db: AsyncSession, user: User) -> None:
    service_res = await db.execute(select(Service.id).where(Service.id == service_id))
    if service_res.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service non trouvé")
    if user.role in {"admin", "super_admin"}:
        return
    service_ids = await get_user_service_ids(db, user)
    if service_id not in service_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès interdit à ce service")


@router.get("/{service_id}/members", response_model=list[CommissionMemberOut])
async def list_commission_members(
    service_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CommissionMemberOut]:
    await _ensure_service_access(service_id, db, user)
    res = await db.execute(
        select(CommissionMember)
        .options(selectinload(CommissionMember.user))
        .where(CommissionMember.service_id == service_id)
        .order_by(CommissionMember.role_type.asc(), CommissionMember.full_name.asc())
    )
    members = res.scalars().all()
    return [
        CommissionMemberOut(
            id=member.id,
            service_id=member.service_id,
            user_id=str(member.user_id) if member.user_id else None,
            full_name=member.full_name,
            email=member.email,
            matricule=member.matricule,
            role_type=member.role_type,
            custom_title=member.custom_title,
            is_signer=member.is_signer,
            created_at=member.created_at,
            user=_member_user_out(member.user),
        )
        for member in members
    ]


@router.get(
    "/members/lookup",
    response_model=list[CommissionMemberLookupOut],
    dependencies=[Depends(has_permission("can_manage_users"))],
)
async def lookup_commission_members(
    q: str = Query(..., min_length=2),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CommissionMemberLookupOut]:
    query_value = f"%{q.strip()}%"
    experts_stmt = (
        select(ExpertComptable)
        .where(
            or_(
                ExpertComptable.numero_ordre.ilike(query_value),
                ExpertComptable.nom_denomination.ilike(query_value),
                ExpertComptable.email.ilike(query_value),
            )
        )
        .order_by(ExpertComptable.numero_ordre.asc())
        .limit(10)
    )
    experts = (await db.execute(experts_stmt)).scalars().all()
    results: list[CommissionMemberLookupOut] = []
    seen: set[str] = set()
    for expert in experts:
        key = (expert.email or expert.numero_ordre or expert.nom_denomination or "").lower()
        if key in seen:
            continue
        seen.add(key)
        results.append(
            CommissionMemberLookupOut(
                full_name=expert.nom_denomination,
                email=expert.email,
                matricule=expert.numero_ordre,
            )
        )

    users_stmt = select(User).where(
        or_(User.email.ilike(query_value), User.prenom.ilike(query_value), User.nom.ilike(query_value))
    )
    if (user.role or "").lower() != "super_admin":
        users_stmt = users_stmt.where(User.role != "super_admin")
    users_stmt = users_stmt.order_by(User.prenom.asc()).limit(10)
    users = (await db.execute(users_stmt)).scalars().all()
    for user in users:
        full_name = f"{user.prenom or ''} {user.nom or ''}".strip() or user.email
        key = (user.email or full_name or "").lower()
        if key in seen:
            continue
        seen.add(key)
        results.append(
            CommissionMemberLookupOut(
                full_name=full_name,
                email=user.email,
                matricule=None,
            )
        )

    return results


@router.post(
    "/{service_id}/members",
    response_model=CommissionMemberOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_permission("can_manage_users"))],
)
async def create_commission_member(
    service_id: int,
    payload: CommissionMemberCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommissionMemberOut:
    await _ensure_service_access(service_id, db, user)
    service_res = await db.execute(select(Service).where(Service.id == service_id))
    if service_res.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service non trouvé")

    target_user: User | None = None
    if payload.user_id:
        try:
            uid = uuid.UUID(str(payload.user_id))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="user_id invalide") from exc
        res_user = await db.execute(select(User).where(User.id == uid))
        target_user = res_user.scalar_one_or_none()
        if target_user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur non trouvé")

    full_name = (payload.full_name or "").strip()
    if not full_name and target_user:
        full_name = f"{target_user.prenom or ''} {target_user.nom or ''}".strip() or target_user.email
    if not full_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="full_name requis")

    email = (payload.email or "").strip() or None
    matricule = (payload.matricule or "").strip() or None
    if not email and target_user and target_user.email:
        email = target_user.email

    role_type = _coerce_role(payload.role_type)
    is_signer = payload.is_signer
    if is_signer is None:
        is_signer = role_type in {CommissionRole.PRESIDENT, CommissionRole.DELEGUE}

    member = CommissionMember(
        service_id=service_id,
        user_id=target_user.id if target_user else None,
        full_name=full_name,
        email=email,
        matricule=matricule,
        role_type=role_type,
        custom_title=payload.custom_title,
        is_signer=bool(is_signer),
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    if member.created_at is None:
        member.created_at = commission_member_utcnow()

    return CommissionMemberOut(
        id=member.id,
        service_id=member.service_id,
        user_id=str(member.user_id) if member.user_id else None,
        full_name=member.full_name,
        email=member.email,
        matricule=member.matricule,
        role_type=member.role_type,
        custom_title=member.custom_title,
        is_signer=member.is_signer,
        created_at=member.created_at,
        user=_member_user_out(target_user),
    )


@router.post(
    "/members/assign",
    response_model=list[CommissionMemberOut],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_permission("can_manage_users"))],
)
async def multi_assign_commission_member(
    payload: CommissionMemberMultiAssign,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CommissionMemberOut]:
    service_ids = [sid for sid in payload.service_ids if isinstance(sid, int)]
    if not service_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="service_ids requis")

    target_user: User | None = None
    if payload.user_id:
        try:
            uid = uuid.UUID(str(payload.user_id))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="user_id invalide") from exc
        res_user = await db.execute(select(User).where(User.id == uid))
        target_user = res_user.scalar_one_or_none()
        if target_user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur non trouvé")

    full_name = (payload.full_name or "").strip()
    if not full_name and target_user:
        full_name = f"{target_user.prenom or ''} {target_user.nom or ''}".strip() or target_user.email
    if not full_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="full_name requis")

    email = (payload.email or "").strip() or None
    matricule = (payload.matricule or "").strip() or None
    if not email and target_user and target_user.email:
        email = target_user.email

    role_type = _coerce_role(payload.role_type)
    is_signer = payload.is_signer
    if is_signer is None:
        is_signer = role_type in {CommissionRole.PRESIDENT, CommissionRole.DELEGUE}

    created_members: list[CommissionMemberOut] = []
    for service_id in service_ids:
        await _ensure_service_access(service_id, db, user)
        service_res = await db.execute(select(Service).where(Service.id == service_id))
        if service_res.scalar_one_or_none() is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Service {service_id} non trouvé")

        exists_query = select(CommissionMember).where(CommissionMember.service_id == service_id)
        if target_user:
            exists_query = exists_query.where(CommissionMember.user_id == target_user.id)
        elif email:
            exists_query = exists_query.where(CommissionMember.email == email)
        else:
            exists_query = exists_query.where(CommissionMember.full_name == full_name)

        existing = (await db.execute(exists_query)).scalar_one_or_none()
        if existing:
            continue

        member = CommissionMember(
            service_id=service_id,
            user_id=target_user.id if target_user else None,
            full_name=full_name,
            email=email,
            matricule=matricule,
            role_type=role_type,
            custom_title=payload.custom_title,
            is_signer=bool(is_signer),
        )
        db.add(member)
        await db.flush()
        if member.created_at is None:
            member.created_at = commission_member_utcnow()
        created_members.append(
            CommissionMemberOut(
                id=member.id,
                service_id=member.service_id,
                user_id=str(member.user_id) if member.user_id else None,
                full_name=member.full_name,
                email=member.email,
                matricule=member.matricule,
                role_type=member.role_type,
                custom_title=member.custom_title,
                is_signer=member.is_signer,
                created_at=member.created_at,
                user=_member_user_out(target_user),
            )
        )

    await db.commit()
    return created_members


@router.patch(
    "/{service_id}/members/{member_id}",
    response_model=CommissionMemberOut,
    dependencies=[Depends(has_permission("can_manage_users"))],
)
async def update_commission_member(
    service_id: int,
    member_id: int,
    payload: CommissionMemberUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommissionMemberOut:
    await _ensure_service_access(service_id, db, user)
    res = await db.execute(
        select(CommissionMember)
        .options(selectinload(CommissionMember.user))
        .where(CommissionMember.id == member_id, CommissionMember.service_id == service_id)
    )
    member = res.scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membre non trouvé")

    target_user = member.user
    if payload.user_id is not None:
        if payload.user_id == "":
            member.user_id = None
            target_user = None
        else:
            try:
                uid = uuid.UUID(str(payload.user_id))
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="user_id invalide") from exc
            res_user = await db.execute(select(User).where(User.id == uid))
            target_user = res_user.scalar_one_or_none()
            if target_user is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur non trouvé")
            member.user_id = target_user.id

    if payload.full_name is not None:
        member.full_name = payload.full_name.strip()

    if payload.email is not None:
        member.email = payload.email.strip() or None

    if payload.matricule is not None:
        member.matricule = payload.matricule.strip() or None

    if payload.role_type is not None:
        member.role_type = _coerce_role(payload.role_type)

    if payload.custom_title is not None:
        member.custom_title = payload.custom_title

    if payload.is_signer is not None:
        member.is_signer = payload.is_signer
    elif payload.role_type is not None and _coerce_role(payload.role_type) in {CommissionRole.PRESIDENT, CommissionRole.DELEGUE}:
        member.is_signer = True

    if not member.full_name and target_user:
        member.full_name = f"{target_user.prenom or ''} {target_user.nom or ''}".strip() or target_user.email
    if not member.email and target_user and target_user.email:
        member.email = target_user.email

    if not member.full_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="full_name requis")

    await db.commit()
    await db.refresh(member)

    return CommissionMemberOut(
        id=member.id,
        service_id=member.service_id,
        user_id=str(member.user_id) if member.user_id else None,
        full_name=member.full_name,
        email=member.email,
        matricule=member.matricule,
        role_type=member.role_type,
        custom_title=member.custom_title,
        is_signer=member.is_signer,
        created_at=member.created_at,
        user=_member_user_out(target_user),
    )


@router.delete(
    "/{service_id}/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(has_permission("can_manage_users"))],
)
async def delete_commission_member(
    service_id: int,
    member_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    await _ensure_service_access(service_id, db, user)
    res = await db.execute(
        select(CommissionMember.id).where(CommissionMember.id == member_id, CommissionMember.service_id == service_id)
    )
    if res.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membre non trouvé")
    await db.execute(
        delete(CommissionMember).where(CommissionMember.id == member_id, CommissionMember.service_id == service_id)
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
