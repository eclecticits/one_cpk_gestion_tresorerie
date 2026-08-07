from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
import uuid
import unicodedata
from sqlalchemy import case, delete, func, select, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    has_permission,
    get_current_user,
    get_current_tenant_id,
    invalidate_auth_context_cache,
)
from app.db.session import get_db
from app.models.budget import BudgetPoste
from app.models.budget_audit_log import BudgetAuditLog
from app.models.encaissement import Encaissement
from app.models.requisition import Requisition
from app.models.ligne_requisition import LigneRequisition
from app.models.service import Service
from app.models.commission_member import CommissionMember, CommissionRole, utcnow as commission_member_utcnow
from app.models.service_member_function import ServiceMemberFunction
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
from app.schemas.service_member_function import (
    ServiceMemberFunctionCreate,
    ServiceMemberFunctionOut,
    ServiceMemberFunctionUpdate,
)
from app.services.forecasting import PENDING_REQUISITION_STATUSES
from app.services.service_access import get_user_service_ids

router = APIRouter()

DEFAULT_MEMBER_FUNCTIONS = [
    "Président(e)",
    "Vice-président(e)",
    "Rapporteur",
    "Rapporteur adjoint",
    "Trésorier",
    "Trésorier(e) adjoint",
    "Secrétaire exécutif",
    "Assistant(e)",
    "Autre",
]

DEFAULT_MEMBER_FUNCTION_KEYS = {
    "president": "Président(e)",
    "vicepresident": "Vice-président(e)",
    "rapporteur": "Rapporteur",
    "rapporteuradjoint": "Rapporteur adjoint",
    "tresorier": "Trésorier",
    "tresoriereadjoint": "Trésorier(e) adjoint",
    "secretaireexecutif": "Secrétaire exécutif",
    "assistant": "Assistant(e)",
    "autre": "Autre",
}


def _normalize_service_code(value: str | None) -> str:
    normalized = " ".join((value or "").strip().split()).upper()
    if normalized == "ADMIN":
        return "ADM"
    return normalized


def _normalize_service_libelle(value: str | None) -> str:
    normalized = " ".join((value or "").strip().split())
    if normalized.lower() in {"administration", "administrations"}:
        return "Administration"
    return normalized


def _service_libelle_key(value: str | None) -> str:
    normalized = " ".join((value or "").strip().split()).lower()
    if normalized in {"administration", "administrations"}:
        return "administration"
    return normalized


def _service_libelle_expr():
    normalized_expr = func.regexp_replace(func.lower(func.btrim(Service.libelle)), r"\s+", " ", "g")
    return case(
        (normalized_expr.in_(["administration", "administrations"]), "administration"),
        else_=normalized_expr,
    )


def _service_code_expr():
    normalized_expr = func.regexp_replace(func.upper(func.btrim(Service.code)), r"\s+", " ", "g")
    return case(
        (normalized_expr == "ADMIN", "ADM"),
        else_=normalized_expr,
    )


def _service_logical_key(service: Service) -> str:
    code_key = _normalize_service_code(service.code)
    libelle_key = _service_libelle_key(service.libelle)
    if code_key == "ADM" or libelle_key == "administration":
        return "ADM::administration"
    return f"{code_key}::{libelle_key}"


def _service_rank(service: Service) -> tuple[int, int, int]:
    is_canonical_administration = int(not (_normalize_service_code(service.code) == "ADM" and _normalize_service_libelle(service.libelle) == "Administration"))
    is_inactive = int(not service.is_active)
    return (is_canonical_administration, is_inactive, service.id)


def _dedupe_services(services: list[Service]) -> list[Service]:
    deduped: dict[str, Service] = {}
    for service in services:
        key = _service_logical_key(service)
        current = deduped.get(key)
        if current is None or _service_rank(service) < _service_rank(current):
            deduped[key] = service
    return sorted(deduped.values(), key=lambda item: (_normalize_service_code(item.code), item.id))


async def _find_service_by_normalized_libelle(
    db: AsyncSession,
    *,
    tenant_id: int,
    libelle: str,
    exclude_service_id: int | None = None,
) -> Service | None:
    query = select(Service).where(
        Service.organisation_id == tenant_id,
        _service_libelle_expr() == _service_libelle_key(libelle),
    )
    if exclude_service_id is not None:
        query = query.where(Service.id != exclude_service_id)
    res = await db.execute(query.limit(1))
    return res.scalar_one_or_none()


async def _find_service_by_normalized_code(
    db: AsyncSession,
    *,
    tenant_id: int,
    code: str,
    exclude_service_id: int | None = None,
) -> Service | None:
    query = select(Service).where(
        Service.organisation_id == tenant_id,
        _service_code_expr() == _normalize_service_code(code),
    )
    if exclude_service_id is not None:
        query = query.where(Service.id != exclude_service_id)
    res = await db.execute(query.limit(1))
    return res.scalar_one_or_none()


@router.get("", response_model=list[ServiceOut])
async def list_services(
    active: bool | None = Query(default=None, description="Filtrer sur les services actifs"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[ServiceOut]:
    query = select(Service).where(Service.organisation_id == tenant_id)
    if active is not None:
        query = query.where(Service.is_active.is_(active))
    role = (user.role or "").lower().replace("-", "_")
    if role not in {"admin", "super_admin"}:
        service_ids = await get_user_service_ids(db, user)
        if service_ids:
            query = query.where(Service.id.in_(service_ids))
        else:
            return []
    query = query.order_by(Service.code.asc())
    res = await db.execute(query)
    services = _dedupe_services(res.scalars().all())
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

@router.get(
    "/{service_id}/member-functions",
    response_model=list[ServiceMemberFunctionOut],
)
async def list_service_member_functions(
    service_id: int,
    active: bool | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[ServiceMemberFunctionOut]:
    await _ensure_service_access(service_id, db, user, tenant_id)
    await _ensure_default_member_functions(db, tenant_id, service_id)
    query = select(ServiceMemberFunction).where(
        ServiceMemberFunction.organisation_id == tenant_id,
        ServiceMemberFunction.service_id == service_id,
    )
    if active is not None:
        query = query.where(ServiceMemberFunction.is_active.is_(active))
    query = query.order_by(ServiceMemberFunction.sort_order.asc(), ServiceMemberFunction.label.asc())
    rows = (await db.execute(query)).scalars().all()
    return [_member_function_out(row) for row in rows if row is not None]


@router.post(
    "/{service_id}/member-functions",
    response_model=ServiceMemberFunctionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_permission("can_manage_users"))],
)
async def create_service_member_function(
    service_id: int,
    payload: ServiceMemberFunctionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> ServiceMemberFunctionOut:
    await _ensure_service_access(service_id, db, user, tenant_id)
    function = await _create_member_function(
        db,
        tenant_id,
        service_id,
        payload.label,
        payload.sort_order,
        payload.is_active if payload.is_active is not None else True,
    )
    await db.commit()
    await db.refresh(function)
    return _member_function_out(function)


@router.patch(
    "/{service_id}/member-functions/{function_id}",
    response_model=ServiceMemberFunctionOut,
    dependencies=[Depends(has_permission("can_manage_users"))],
)
async def update_service_member_function(
    service_id: int,
    function_id: int,
    payload: ServiceMemberFunctionUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> ServiceMemberFunctionOut:
    await _ensure_service_access(service_id, db, user, tenant_id)
    await _ensure_default_member_functions(db, tenant_id, service_id)
    res = await db.execute(
        select(ServiceMemberFunction).where(
            ServiceMemberFunction.id == function_id,
            ServiceMemberFunction.organisation_id == tenant_id,
            ServiceMemberFunction.service_id == service_id,
        )
    )
    function = res.scalar_one_or_none()
    if function is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fonction non trouvée")

    if payload.label is not None:
        normalized_label = _normalize_function_label(payload.label)
        if not normalized_label:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="label requis")
        existing = await db.execute(
            select(ServiceMemberFunction).where(
                ServiceMemberFunction.organisation_id == tenant_id,
                ServiceMemberFunction.service_id == service_id,
            )
        )
        if any(
            item.id != function_id and _function_canonical_key(item.label) == _function_canonical_key(normalized_label)
            for item in existing.scalars().all()
        ):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cette fonction existe déjà")
        function.label = normalized_label
    if payload.sort_order is not None:
        function.sort_order = payload.sort_order
    if payload.is_active is not None:
        function.is_active = payload.is_active

    await db.commit()
    await db.refresh(function)
    return _member_function_out(function)


@router.delete(
    "/{service_id}/member-functions/{function_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(has_permission("can_manage_users"))],
)
async def delete_service_member_function(
    service_id: int,
    function_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> Response:
    await _ensure_service_access(service_id, db, user, tenant_id)
    res = await db.execute(
        select(ServiceMemberFunction).where(
            ServiceMemberFunction.id == function_id,
            ServiceMemberFunction.organisation_id == tenant_id,
            ServiceMemberFunction.service_id == service_id,
        )
    )
    function = res.scalar_one_or_none()
    if function is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fonction non trouvée")

    usage_res = await db.execute(
        select(func.count(CommissionMember.id)).where(CommissionMember.function_id == function_id)
    )
    usage_count = int(usage_res.scalar_one() or 0)
    if usage_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Impossible de supprimer cette fonction : elle est encore utilisée par des membres.",
        )

    await db.delete(function)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.get("/{service_id}", response_model=ServiceOut)
async def get_service(
    service_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> ServiceOut:
    role = (user.role or "").lower().replace("-", "_")
    if role not in {"admin", "super_admin"}:
        service_ids = await get_user_service_ids(db, user)
        if service_id not in service_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès interdit")
    res = await db.execute(
        select(Service).where(Service.id == service_id, Service.organisation_id == tenant_id)
    )
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
    code = _normalize_service_code(payload.code)
    libelle = _normalize_service_libelle(payload.libelle)
    if len(code) < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Code service invalide")
    if len(libelle) < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Libellé service invalide")
    existing_by_code = await _find_service_by_normalized_code(db, tenant_id=tenant_id, code=code)
    if existing_by_code is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Code service déjà utilisé")
    existing_by_libelle = await _find_service_by_normalized_libelle(db, tenant_id=tenant_id, libelle=libelle)
    if existing_by_libelle is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Un service avec ce libellé existe déjà dans cette organisation.",
        )
    service = Service(code=code, libelle=libelle, is_active=bool(payload.is_active), organisation_id=tenant_id)
    db.add(service)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Un service avec ce code ou ce libellé existe déjà dans cette organisation.",
        )
    await db.refresh(service)
    await _ensure_default_member_functions(db, tenant_id, service.id)
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
            uid = payload.user_id if isinstance(payload.user_id, uuid.UUID) else uuid.UUID(str(payload.user_id))
        except (ValueError, AttributeError, TypeError):
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
        code = _normalize_service_code(payload.code)
        if len(code) < 2:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Code service invalide")
        existing_by_code = await _find_service_by_normalized_code(
            db,
            tenant_id=tenant_id,
            code=code,
            exclude_service_id=service_id,
        )
        if existing_by_code is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Code service déjà utilisé")
        service.code = code
    if payload.libelle is not None:
        libelle = _normalize_service_libelle(payload.libelle)
        if len(libelle) < 2:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Libellé service invalide")
        existing_by_libelle = await _find_service_by_normalized_libelle(
            db,
            tenant_id=tenant_id,
            libelle=libelle,
            exclude_service_id=service_id,
        )
        if existing_by_libelle is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Un service avec ce libellé existe déjà dans cette organisation.",
            )
        service.libelle = libelle
    if payload.is_active is not None:
        service.is_active = payload.is_active

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Un service avec ce code ou ce libellé existe déjà dans cette organisation.",
        )
    await db.refresh(service)
    return ServiceOut(id=service.id, code=service.code, libelle=service.libelle, is_active=service.is_active)


@router.get("/{service_id}/consommation", response_model=ServiceConsumption)
async def get_service_consumption(
    service_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> ServiceConsumption:
    role = (user.role or "").lower().replace("-", "_")
    if role not in {"admin", "super_admin"}:
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
            ServiceRubrique.active.is_(True),
            BudgetPoste.is_deleted.is_(False),
        )
    )
    total_budget_prevu = total_budget_res.scalar_one() or 0

    total_recettes_res = await db.execute(
        select(func.coalesce(func.sum(func.coalesce(Encaissement.montant_paye, 0)), 0)).where(
            Encaissement.service_id == service_id,
            Encaissement.est_proforma.is_(False),
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
    role = (user.role or "").lower().replace("-", "_")
    if role not in {"admin", "super_admin"}:
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
            ServiceRubrique.active.is_(True),
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


# Réquisitions « en cours » (non soldées) : ouvertes + en décaissement progressif.
STATUTS_REQ_EN_COURS = tuple(PENDING_REQUISITION_STATUSES) + ("EN_DECAISSEMENT",)


async def _rubriques_usage(
    db: AsyncSession, service_id: int, poste_ids: set[int] | None = None
) -> tuple[set[int], set[int]]:
    """Détecte l'usage de postes budgétaires dans un service.

    Retourne (en_cours_ids, used_ids) :
    - ``en_cours_ids`` : postes engagés par une réquisition NON soldée du service ;
    - ``used_ids`` : postes ayant un usage quelconque (réquisition tout statut,
      sortie de fonds valide, ou encaissement actif) dans le service.

    ``poste_ids`` restreint l'analyse à ces postes ; ``None`` = tous les postes
    utilisés du service.
    """
    if poste_ids is not None and not poste_ids:
        return set(), set()
    ids = list(poste_ids) if poste_ids is not None else None

    en_cours_q = (
        select(LigneRequisition.budget_poste_id)
        .join(Requisition, Requisition.id == LigneRequisition.requisition_id)
        .where(
            Requisition.service_id == service_id,
            Requisition.is_deleted.is_(False),
            func.upper(Requisition.status).in_(STATUTS_REQ_EN_COURS),
        )
        .distinct()
    )
    req_q = (
        select(LigneRequisition.budget_poste_id)
        .join(Requisition, Requisition.id == LigneRequisition.requisition_id)
        .where(
            Requisition.service_id == service_id,
            Requisition.is_deleted.is_(False),
        )
        .distinct()
    )
    sortie_q = (
        select(SortieFonds.budget_poste_id)
        .where(
            SortieFonds.service_id == service_id,
            SortieFonds.budget_poste_id.isnot(None),
            (SortieFonds.statut.is_(None)) | (func.upper(SortieFonds.statut) != "ANNULEE"),
        )
        .distinct()
    )
    enc_q = (
        select(Encaissement.budget_poste_id)
        .where(
            Encaissement.service_id == service_id,
            Encaissement.budget_poste_id.isnot(None),
            Encaissement.is_deleted.is_(False),
            func.upper(Encaissement.statut_operation) != "ANNULEE",
        )
        .distinct()
    )
    if ids is not None:
        en_cours_q = en_cours_q.where(LigneRequisition.budget_poste_id.in_(ids))
        req_q = req_q.where(LigneRequisition.budget_poste_id.in_(ids))
        sortie_q = sortie_q.where(SortieFonds.budget_poste_id.in_(ids))
        enc_q = enc_q.where(Encaissement.budget_poste_id.in_(ids))

    en_cours_ids = {r[0] for r in (await db.execute(en_cours_q)).all() if r[0] is not None}
    used_ids = {r[0] for r in (await db.execute(req_q)).all() if r[0] is not None}
    used_ids |= {r[0] for r in (await db.execute(sortie_q)).all() if r[0] is not None}
    used_ids |= {r[0] for r in (await db.execute(enc_q)).all() if r[0] is not None}
    used_ids |= en_cours_ids
    return en_cours_ids, used_ids


async def _postes_info(db: AsyncSession, poste_ids: set[int]) -> dict[int, dict]:
    if not poste_ids:
        return {}
    res = await db.execute(
        select(BudgetPoste.id, BudgetPoste.code, BudgetPoste.libelle).where(
            BudgetPoste.id.in_(list(poste_ids))
        )
    )
    return {row.id: {"id": row.id, "code": row.code, "libelle": row.libelle} for row in res.all()}


@router.get("/{service_id}/rubriques/usage")
async def service_rubriques_usage(
    service_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> dict:
    """Postes déjà utilisés dans un service, pour prévenir avant désactivation.

    ``used`` : postes ayant un usage quelconque ; ``en_cours`` : sous-ensemble
    engagé par des réquisitions non soldées (désactivation bloquée).
    """
    service_res = await db.execute(
        select(Service).where(Service.id == service_id, Service.organisation_id == tenant_id)
    )
    if service_res.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service non trouvé")
    en_cours_ids, used_ids = await _rubriques_usage(db, service_id, None)
    return {"used": sorted(used_ids), "en_cours": sorted(en_cours_ids)}


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

    # --- Diff avec l'existant (au lieu d'un remplacement brut) ---
    current_rows = (
        await db.execute(select(ServiceRubrique).where(ServiceRubrique.service_id == service_id))
    ).scalars().all()
    current_by_poste = {r.budget_poste_id: r for r in current_rows}
    current_active = {pid for pid, r in current_by_poste.items() if r.active}

    desired = set(rubrique_ids)
    to_add = desired - current_active     # nouveaux postes ou réactivations
    to_remove = current_active - desired  # postes désautorisés

    # --- Garde-fous sur les retraits : usage dans le service ---
    used_ids: set[int] = set()
    if to_remove:
        en_cours_ids, used_ids = await _rubriques_usage(db, service_id, to_remove)
        confirm_ids = used_ids - en_cours_ids  # usage uniquement historique
        # Blocage si opérations en cours ; confirmation (force) si usage historique.
        if en_cours_ids or (confirm_ids and not payload.force):
            postes_info = await _postes_info(db, en_cours_ids | confirm_ids)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "rubriques_utilisees",
                    "message": "Des postes retirés ont déjà servi dans ce service.",
                    "bloques": [
                        {**postes_info.get(i, {"id": i}), "raison": "operations_en_cours"}
                        for i in sorted(en_cours_ids)
                    ],
                    "a_confirmer": [
                        {**postes_info.get(i, {"id": i}), "raison": "usage_historique"}
                        for i in sorted(confirm_ids)
                    ],
                },
            )

    # --- Application + journalisation (BudgetAuditLog) ---
    uid = getattr(user, "id", None)
    field = f"service:{service_id}"

    def _log(pid: int, action: str, old: int, new: int) -> None:
        db.add(
            BudgetAuditLog(
                organisation_id=tenant_id,
                budget_poste_id=pid,
                action=action,
                field_name=field,
                old_value=old,
                new_value=new,
                user_id=uid,
            )
        )

    for pid in to_add:
        row = current_by_poste.get(pid)
        if row is None:
            db.add(ServiceRubrique(service_id=service_id, budget_poste_id=pid, active=True))
            _log(pid, "RUB_AUTORISEE", 0, 1)
        else:
            row.active = True  # réactivation d'un poste précédemment désactivé
            _log(pid, "RUB_REACTIVEE", 0, 1)
    for pid in to_remove:
        row = current_by_poste[pid]
        if pid in used_ids:
            row.active = False  # soft-deactivate : on conserve la trace
            _log(pid, "RUB_DESACTIVEE", 1, 0)
        else:
            await db.delete(row)  # jamais utilisé : suppression franche
            _log(pid, "RUB_RETIREE", 1, 0)
    await db.commit()

    return {"ok": True, "rubrique_ids": sorted(desired)}


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


def _normalize_function_label(label: str | None) -> str:
    return " ".join((label or "").strip().split())


def _function_canonical_key(label: str | None) -> str:
    normalized = _normalize_function_label(label)
    ascii_label = unicodedata.normalize("NFKD", normalized).encode("ascii", "ignore").decode("ascii")
    cleaned = "".join(ch for ch in ascii_label.lower() if ch.isalnum())
    if cleaned.endswith("e") and cleaned[:-1] in DEFAULT_MEMBER_FUNCTION_KEYS:
        return cleaned[:-1]
    return cleaned


def _canonical_function_label(label: str | None) -> str:
    normalized = _normalize_function_label(label)
    return DEFAULT_MEMBER_FUNCTION_KEYS.get(_function_canonical_key(normalized), normalized)


def _function_label_for_member(member: CommissionMember) -> str | None:
    if member.function and member.function.label:
        return member.function.label
    return None


def _member_function_out(function: ServiceMemberFunction | None) -> ServiceMemberFunctionOut | None:
    if function is None:
        return None
    return ServiceMemberFunctionOut(
        id=function.id,
        service_id=function.service_id,
        label=function.label,
        sort_order=function.sort_order,
        is_default=function.is_default,
        is_active=function.is_active,
        created_at=function.created_at,
        updated_at=function.updated_at,
    )


def _member_out(member: CommissionMember, target_user: User | None = None) -> CommissionMemberOut:
    return CommissionMemberOut(
        id=member.id,
        service_id=member.service_id,
        user_id=str(member.user_id) if member.user_id else None,
        full_name=member.full_name,
        email=member.email,
        matricule=member.matricule,
        function_id=member.function_id,
        function_label=_function_label_for_member(member),
        function=_member_function_out(member.function),
        role_type=member.role_type,
        custom_title=member.custom_title,
        is_signer=member.is_signer,
        created_at=member.created_at,
        user=_member_user_out(target_user or member.user),
    )


def _is_assistant_function(label: str | None) -> bool:
    normalized = _normalize_function_label(label).lower()
    return "assistant" in normalized


def _is_vice_president_function(label: str | None) -> bool:
    normalized = _normalize_function_label(label).lower()
    return "vice" in normalized and "président" in normalized


def _is_president_function(label: str | None) -> bool:
    normalized = _normalize_function_label(label).lower()
    return normalized.startswith("président") or normalized.startswith("president")


def _derive_role_from_function(label: str | None, fallback: CommissionRole | str | None = None) -> CommissionRole:
    normalized = _normalize_function_label(label)
    if _is_assistant_function(normalized):
        return CommissionRole.ASSISTANT
    if _is_vice_president_function(normalized):
        return CommissionRole.DELEGUE
    if _is_president_function(normalized):
        return CommissionRole.PRESIDENT
    return _coerce_role(fallback)


async def _ensure_default_member_functions(db: AsyncSession, tenant_id: int, service_id: int) -> None:
    existing_res = await db.execute(
        select(ServiceMemberFunction).where(
            ServiceMemberFunction.organisation_id == tenant_id,
            ServiceMemberFunction.service_id == service_id,
        )
    )
    existing = {_function_canonical_key(item.label) for item in existing_res.scalars().all()}
    created = False
    for index, label in enumerate(DEFAULT_MEMBER_FUNCTIONS, start=1):
        if _function_canonical_key(label) in existing:
            continue
        db.add(
            ServiceMemberFunction(
                label=label,
                sort_order=index,
                is_default=True,
                is_active=True,
                organisation_id=tenant_id,
                service_id=service_id,
            )
        )
        created = True
    if created:
        await db.commit()


async def _find_member_function_by_label(
    db: AsyncSession,
    tenant_id: int,
    service_id: int,
    function_label: str | None,
) -> ServiceMemberFunction | None:
    await _ensure_default_member_functions(db, tenant_id, service_id)

    normalized_label = _normalize_function_label(function_label)
    if not normalized_label:
        return None

    res = await db.execute(
        select(ServiceMemberFunction).where(
            ServiceMemberFunction.organisation_id == tenant_id,
            ServiceMemberFunction.service_id == service_id,
        )
    )
    target_key = _function_canonical_key(normalized_label)
    for function in res.scalars().all():
        if _function_canonical_key(function.label) == target_key:
            return function
    return None


async def _resolve_member_function(
    db: AsyncSession,
    tenant_id: int,
    service_id: int,
    function_id: int | None,
    function_label: str | None,
) -> ServiceMemberFunction | None:
    await _ensure_default_member_functions(db, tenant_id, service_id)

    if function_id is not None:
        res = await db.execute(
            select(ServiceMemberFunction).where(
                ServiceMemberFunction.id == function_id,
                ServiceMemberFunction.organisation_id == tenant_id,
                ServiceMemberFunction.service_id == service_id,
            )
        )
        function = res.scalar_one_or_none()
        if function is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fonction non trouvée")
        if not function.is_active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cette fonction est désactivée")
        return function

    function = await _find_member_function_by_label(db, tenant_id, service_id, function_label)
    if function is None:
        return None
    if not function.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cette fonction est désactivée")
    return function


async def _create_member_function(
    db: AsyncSession,
    tenant_id: int,
    service_id: int,
    label: str,
    sort_order: int | None = None,
    is_active: bool = True,
) -> ServiceMemberFunction:
    await _ensure_default_member_functions(db, tenant_id, service_id)
    normalized_label = _normalize_function_label(label)
    if not normalized_label:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="label requis")

    existing = await _find_member_function_by_label(db, tenant_id, service_id, normalized_label)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cette fonction existe déjà")

    if sort_order is None:
        max_sort = await db.execute(
            select(func.coalesce(func.max(ServiceMemberFunction.sort_order), 0)).where(
                ServiceMemberFunction.organisation_id == tenant_id,
                ServiceMemberFunction.service_id == service_id,
            )
        )
        resolved_sort_order = int(max_sort.scalar_one() or 0) + 1
    else:
        resolved_sort_order = sort_order

    function = ServiceMemberFunction(
        label=normalized_label,
        sort_order=resolved_sort_order,
        is_default=False,
        is_active=is_active,
        organisation_id=tenant_id,
        service_id=service_id,
    )
    db.add(function)
    await db.flush()
    return function


async def _ensure_service_access(service_id: int, db: AsyncSession, user: User, tenant_id: int) -> None:
    service_res = await db.execute(
        select(Service.id).where(
            Service.id == service_id,
            Service.organisation_id == tenant_id,
        )
    )
    if service_res.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service non trouvé")
    role = (user.role or "").lower().replace("-", "_")
    if role in {"admin", "super_admin"}:
        return
    service_ids = await get_user_service_ids(db, user)
    if service_id not in service_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès interdit à ce service")


@router.get("/{service_id}/members", response_model=list[CommissionMemberOut])
async def list_commission_members(
    service_id: int,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CommissionMemberOut]:
    await _ensure_service_access(service_id, db, user, tenant_id)
    await _ensure_default_member_functions(db, tenant_id, service_id)
    res = await db.execute(
        select(CommissionMember)
        .options(selectinload(CommissionMember.user), selectinload(CommissionMember.function))
        .where(CommissionMember.service_id == service_id)
        .order_by(
            func.coalesce(ServiceMemberFunction.sort_order, 999999).asc(),
            CommissionMember.full_name.asc(),
        )
        .outerjoin(ServiceMemberFunction, CommissionMember.function_id == ServiceMemberFunction.id)
    )
    members = res.scalars().all()
    return [_member_out(member) for member in members]


@router.get(
    "/members/lookup",
    response_model=list[CommissionMemberLookupOut],
    dependencies=[Depends(has_permission("can_manage_users"))],
)
async def lookup_commission_members(
    q: str = Query(..., min_length=2),
    tenant_id: int = Depends(get_current_tenant_id),
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
        User.organisation_id == tenant_id,
        or_(User.email.ilike(query_value), User.prenom.ilike(query_value), User.nom.ilike(query_value)),
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
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommissionMemberOut:
    await _ensure_service_access(service_id, db, user, tenant_id)
    service_res = await db.execute(select(Service).where(Service.id == service_id, Service.organisation_id == tenant_id))
    if service_res.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service non trouvé")

    target_user: User | None = None
    if payload.user_id:
        try:
            uid = uuid.UUID(str(payload.user_id))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="user_id invalide") from exc
        res_user = await db.execute(select(User).where(User.id == uid, User.organisation_id == tenant_id))
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

    function = await _resolve_member_function(db, tenant_id, service_id, payload.function_id, payload.function_label)
    if function is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="function_id requis")
    role_type = _derive_role_from_function(function.label if function else None, payload.role_type)
    is_signer = payload.is_signer
    if is_signer is None:
        is_signer = role_type in {CommissionRole.PRESIDENT, CommissionRole.DELEGUE}

    member = CommissionMember(
        service_id=service_id,
        user_id=target_user.id if target_user else None,
        full_name=full_name,
        email=email,
        matricule=matricule,
        function_id=function.id if function else None,
        role_type=role_type,
        custom_title=payload.custom_title,
        is_signer=bool(is_signer),
    )
    db.add(member)
    await db.commit()
    if target_user is not None:
        await invalidate_auth_context_cache(target_user.id)
    await db.refresh(member, attribute_names=["user", "function"])
    if member.created_at is None:
        member.created_at = commission_member_utcnow()
    return _member_out(member, target_user)


@router.post(
    "/members/assign",
    response_model=list[CommissionMemberOut],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_permission("can_manage_users"))],
)
async def multi_assign_commission_member(
    payload: CommissionMemberMultiAssign,
    tenant_id: int = Depends(get_current_tenant_id),
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
        res_user = await db.execute(select(User).where(User.id == uid, User.organisation_id == tenant_id))
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

    selected_function_label = (payload.function_label or "").strip() or None
    if selected_function_label is None and payload.function_id is not None:
        base_function = await db.get(ServiceMemberFunction, payload.function_id)
        if base_function is not None and base_function.organisation_id == tenant_id:
            selected_function_label = base_function.label
    if not selected_function_label:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="function_id requis")

    created_members: list[CommissionMemberOut] = []
    for service_id in service_ids:
        await _ensure_service_access(service_id, db, user, tenant_id)
        service_res = await db.execute(select(Service).where(Service.id == service_id, Service.organisation_id == tenant_id))
        if service_res.scalar_one_or_none() is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Service {service_id} non trouvé")
        function = await _resolve_member_function(db, tenant_id, service_id, None, selected_function_label)
        if function is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Aucune fonction '{selected_function_label}' n'existe pour le service {service_id}",
            )
        role_type = _derive_role_from_function(function.label if function else None, payload.role_type)
        is_signer = payload.is_signer
        if is_signer is None:
            is_signer = role_type in {CommissionRole.PRESIDENT, CommissionRole.DELEGUE}

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
            function_id=function.id if function else None,
            role_type=role_type,
            custom_title=payload.custom_title,
            is_signer=bool(is_signer),
        )
        db.add(member)
        await db.flush()
        if member.created_at is None:
            member.created_at = commission_member_utcnow()
        member.function = function
        created_members.append(_member_out(member, target_user))

    await db.commit()
    if target_user is not None:
        await invalidate_auth_context_cache(target_user.id)
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
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommissionMemberOut:
    await _ensure_service_access(service_id, db, user, tenant_id)
    res = await db.execute(
        select(CommissionMember)
        .options(selectinload(CommissionMember.user), selectinload(CommissionMember.function))
        .where(CommissionMember.id == member_id, CommissionMember.service_id == service_id)
    )
    member = res.scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membre non trouvé")

    previous_user_id = member.user_id
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
            res_user = await db.execute(select(User).where(User.id == uid, User.organisation_id == tenant_id))
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

    if payload.function_id is not None or payload.function_label is not None:
        function = await _resolve_member_function(
            db,
            tenant_id,
            service_id,
            payload.function_id,
            payload.function_label,
        )
        if function is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="function_id requis")
        member.function_id = function.id if function else None
        member.function = function
        member.role_type = _derive_role_from_function(function.label if function else None, payload.role_type or member.role_type)
    elif payload.role_type is not None:
        member.role_type = _coerce_role(payload.role_type)

    if payload.custom_title is not None:
        member.custom_title = payload.custom_title

    if payload.is_signer is not None:
        member.is_signer = payload.is_signer
    elif payload.function_id is not None or payload.function_label is not None:
        member.is_signer = member.role_type in {CommissionRole.PRESIDENT, CommissionRole.DELEGUE}
    elif payload.role_type is not None and _coerce_role(payload.role_type) in {CommissionRole.PRESIDENT, CommissionRole.DELEGUE}:
        member.is_signer = True

    if not member.full_name and target_user:
        member.full_name = f"{target_user.prenom or ''} {target_user.nom or ''}".strip() or target_user.email
    if not member.email and target_user and target_user.email:
        member.email = target_user.email

    if not member.full_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="full_name requis")

    await db.commit()
    # Le rattachement peut avoir été déplacé d'un utilisateur à un autre : les
    # deux contextes d'auth doivent être purgés.
    for uid_to_purge in {previous_user_id, member.user_id} - {None}:
        await invalidate_auth_context_cache(uid_to_purge)
    await db.refresh(member, attribute_names=["user", "function"])

    return _member_out(member, target_user)


@router.delete(
    "/{service_id}/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(has_permission("can_manage_users"))],
)
async def delete_commission_member(
    service_id: int,
    member_id: int,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    await _ensure_service_access(service_id, db, user, tenant_id)
    res = await db.execute(
        select(CommissionMember.user_id).where(
            CommissionMember.id == member_id, CommissionMember.service_id == service_id
        )
    )
    row = res.first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membre non trouvé")
    member_user_id = row[0]
    await db.execute(
        delete(CommissionMember).where(CommissionMember.id == member_id, CommissionMember.service_id == service_id)
    )
    await db.commit()
    if member_user_id is not None:
        await invalidate_auth_context_cache(member_user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
