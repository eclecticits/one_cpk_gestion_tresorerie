from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Integer, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_tenant_id, get_current_user, get_db, has_any_permission, has_permission
from app.models.hr import (
    HRAttendance,
    HRContract,
    HRDocument,
    HREmployee,
    HREvaluation,
    HRFunction,
    HRLeave,
    HRLeaveAllocation,
    HRPayrollEntry,
    HRReference,
    HRSalarySlip,
    HRSanction,
    HRService,
)
from app.models.rbac import Permission, Role, role_permissions
from app.models.user import User
from app.schemas.hr import (
    HRAttendanceBatchCreate,
    HRAttendanceCreate,
    HRAttendanceOut,
    HRAttendanceSummaryOut,
    HRAttendanceUpdate,
    HRContractCreate,
    HRContractOut,
    HRContractUpdate,
    HRDashboardOut,
    HRDocumentCreate,
    HRDocumentOut,
    HRDocumentUpdate,
    HREmployeeCreate,
    HREmployeeOut,
    HREmployeeUpdate,
    HRFunctionCreate,
    HRFunctionOut,
    HRFunctionUpdate,
    HRLeaveAllocationCreate,
    HRLeaveAllocationOut,
    HRLeaveAllocationUpdate,
    HRLeaveBalanceOut,
    HRLeaveCreate,
    HRLeaveOut,
    HRLeaveUpdate,
    HRPayrollEntryCreate,
    HRPayrollEntryOut,
    HRReferenceCreate,
    HRReferenceOut,
    HRReferenceUpdate,
    HREvaluationCreate,
    HREvaluationOut,
    HREvaluationUpdate,
    HRReportOut,
    HRSalarySlipOut,
    HRSanctionCreate,
    HRSanctionOut,
    HRSanctionUpdate,
    HRServiceCreate,
    HRServiceOut,
    HRServiceUpdate,
)

router = APIRouter()

ALLOWED_REFERENCE_CATEGORIES = {
    "departements",
    "types-contrats",
    "statuts-contrats",
    "types-absences",
    "regles-conges",
    "jours-feries",
    "types-primes",
    "types-retenues",
    "devises",
    "types-documents",
}


async def _user_has_permission(db: AsyncSession, user: User, code: str) -> bool:
    if (user.role or "").lower() in {"admin", "super_admin"}:
        return True
    if not user.role_id:
        return False
    res = await db.execute(
        select(Permission.id)
        .join(role_permissions, role_permissions.c.permission_id == Permission.id)
        .where(role_permissions.c.role_id == user.role_id, Permission.code == code)
        .limit(1)
    )
    if res.scalar_one_or_none() is not None:
        return True
    role_res = await db.execute(select(Role.code).where(Role.id == user.role_id))
    return (role_res.scalar_one_or_none() or "").lower() == "admin"


async def _employee_or_404(db: AsyncSession, tenant_id: int, employee_id: int) -> HREmployee:
    res = await db.execute(
        select(HREmployee)
        .options(selectinload(HREmployee.service), selectinload(HREmployee.fonction))
        .where(HREmployee.tenant_id == tenant_id, HREmployee.id == employee_id)
    )
    employee = res.scalar_one_or_none()
    if employee is None:
        raise HTTPException(status_code=404, detail="Agent introuvable")
    return employee


def _hide_salary(contract: HRContractOut, can_view_salary: bool) -> HRContractOut:
    if not can_view_salary:
        contract.salaire_base = None
    return contract


@router.get("/dashboard", response_model=HRDashboardOut, dependencies=[Depends(has_permission("rh.dashboard.view"))])
async def dashboard(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> HRDashboardOut:
    from datetime import date as date_type
    today = date.today()
    soon = today + timedelta(days=45)
    active_count = await db.scalar(select(func.count()).select_from(HREmployee).where(HREmployee.tenant_id == tenant_id, HREmployee.statut == "actif"))
    leave_count = await db.scalar(select(func.count()).select_from(HREmployee).where(HREmployee.tenant_id == tenant_id, HREmployee.statut == "en_conge"))
    expiring_count = await db.scalar(
        select(func.count()).select_from(HRContract).where(
            HRContract.tenant_id == tenant_id,
            HRContract.statut == "actif",
            HRContract.date_fin.is_not(None),
            HRContract.date_fin >= today,
            HRContract.date_fin <= soon,
        )
    )
    pending_leave_count = await db.scalar(select(func.count()).select_from(HRLeave).where(HRLeave.tenant_id == tenant_id, HRLeave.statut == "soumis"))
    can_view_salary = await _user_has_permission(db, user, "rh.salaries.view")
    payroll_mass = None
    if can_view_salary:
        payroll_mass = await db.scalar(
            select(func.coalesce(func.sum(HRContract.salaire_base), 0)).where(HRContract.tenant_id == tenant_id, HRContract.statut == "actif")
        )
    movements_res = await db.execute(
        select(HREmployee).where(HREmployee.tenant_id == tenant_id).order_by(HREmployee.created_at.desc()).limit(5)
    )
    movements = [
        {"type": "agent", "label": f"{emp.matricule} - {emp.nom} {emp.prenom or ''}".strip(), "date": emp.created_at.isoformat()}
        for emp in movements_res.scalars().all()
    ]
    # New dashboard metrics
    total_absences_mois = await db.scalar(
        select(func.count()).select_from(HRAttendance).where(
            HRAttendance.tenant_id == tenant_id,
            func.extract("month", HRAttendance.date_presence) == today.month,
            func.extract("year", HRAttendance.date_presence) == today.year,
            HRAttendance.statut_presence == "absent",
        )
    )
    nb_bulletins_en_attente = await db.scalar(
        select(func.count()).select_from(HRPayrollEntry).where(
            HRPayrollEntry.tenant_id == tenant_id,
            HRPayrollEntry.statut == "brouillon",
        )
    )
    # Compute attendance rate for current month
    att_res = await db.execute(
        select(HRAttendance.statut_presence).where(
            HRAttendance.tenant_id == tenant_id,
            func.extract("month", HRAttendance.date_presence) == today.month,
            func.extract("year", HRAttendance.date_presence) == today.year,
        )
    )
    att_rows = att_res.scalars().all()
    taux_presence_mois: float | None = None
    if att_rows:
        presents = sum(1 for s in att_rows if s == "present")
        demi = sum(1 for s in att_rows if s == "demi_journee")
        total = len(att_rows)
        taux_presence_mois = round((presents + demi * 0.5) / total * 100, 2)

    return HRDashboardOut(
        total_agents_actifs=active_count or 0,
        agents_en_conge=leave_count or 0,
        contrats_expirant_bientot=expiring_count or 0,
        demandes_conge_en_attente=pending_leave_count or 0,
        masse_salariale_estimee=Decimal(payroll_mass or 0) if can_view_salary else None,
        derniers_mouvements=movements,
        total_absences_mois=total_absences_mois or 0,
        nb_bulletins_en_attente=nb_bulletins_en_attente or 0,
        taux_presence_mois=taux_presence_mois,
    )


@router.get(
    "/employees",
    response_model=list[HREmployeeOut],
    dependencies=[Depends(has_any_permission(["rh.employees.view", "rh.contracts.view", "rh.leave.view", "rh.documents.view"]))],
)
async def list_employees(
    q: str | None = Query(default=None),
    statut: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[HREmployee]:
    stmt = select(HREmployee).options(selectinload(HREmployee.service), selectinload(HREmployee.fonction)).where(HREmployee.tenant_id == tenant_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where((HREmployee.nom.ilike(like)) | (HREmployee.prenom.ilike(like)) | (HREmployee.matricule.ilike(like)))
    if statut:
        stmt = stmt.where(HREmployee.statut == statut)
    res = await db.execute(stmt.order_by(HREmployee.nom.asc(), HREmployee.prenom.asc()))
    return list(res.scalars().all())


@router.post("/employees", response_model=HREmployeeOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(has_permission("rh.employees.create"))])
async def create_employee(payload: HREmployeeCreate, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)) -> HREmployee:
    employee = HREmployee(**payload.model_dump(), tenant_id=tenant_id)
    db.add(employee)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Matricule déjà utilisé pour cette organisation")
    await db.refresh(employee, ["service", "fonction"])
    return employee


@router.get("/employees/{employee_id}", response_model=HREmployeeOut, dependencies=[Depends(has_permission("rh.employees.view"))])
async def get_employee(employee_id: int, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)) -> HREmployee:
    return await _employee_or_404(db, tenant_id, employee_id)


@router.patch("/employees/{employee_id}", response_model=HREmployeeOut, dependencies=[Depends(has_permission("rh.employees.update"))])
async def update_employee(employee_id: int, payload: HREmployeeUpdate, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)) -> HREmployee:
    employee = await _employee_or_404(db, tenant_id, employee_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(employee, key, value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Matricule déjà utilisé pour cette organisation")
    await db.refresh(employee, ["service", "fonction"])
    return employee


@router.post("/employees/{employee_id}/archive", response_model=HREmployeeOut, dependencies=[Depends(has_permission("rh.employees.archive"))])
async def archive_employee(employee_id: int, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)) -> HREmployee:
    employee = await _employee_or_404(db, tenant_id, employee_id)
    employee.statut = "sorti"
    await db.commit()
    await db.refresh(employee, ["service", "fonction"])
    return employee


@router.get("/contracts", response_model=list[HRContractOut], dependencies=[Depends(has_permission("rh.contracts.view"))])
async def list_contracts(
    employee_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[HRContractOut]:
    stmt = select(HRContract).where(HRContract.tenant_id == tenant_id)
    if employee_id:
        stmt = stmt.where(HRContract.employee_id == employee_id)
    res = await db.execute(stmt.order_by(HRContract.date_debut.desc()))
    can_view_salary = await _user_has_permission(db, user, "rh.salaries.view")
    return [_hide_salary(HRContractOut.model_validate(contract), can_view_salary) for contract in res.scalars().all()]


@router.post("/contracts", response_model=HRContractOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(has_permission("rh.contracts.manage"))])
async def create_contract(
    payload: HRContractCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> HRContractOut:
    await _employee_or_404(db, tenant_id, payload.employee_id)
    data = payload.model_dump()
    can_view_salary = await _user_has_permission(db, user, "rh.salaries.view")
    if not can_view_salary:
        data["salaire_base"] = Decimal("0")
        data["devise"] = "USD"
    contract = HRContract(**data, tenant_id=tenant_id)
    db.add(contract)
    await db.commit()
    await db.refresh(contract)
    return _hide_salary(HRContractOut.model_validate(contract), can_view_salary)


@router.patch("/contracts/{contract_id}", response_model=HRContractOut, dependencies=[Depends(has_permission("rh.contracts.manage"))])
async def update_contract(
    contract_id: int,
    payload: HRContractUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> HRContractOut:
    res = await db.execute(select(HRContract).where(HRContract.tenant_id == tenant_id, HRContract.id == contract_id))
    contract = res.scalar_one_or_none()
    if contract is None:
        raise HTTPException(status_code=404, detail="Contrat introuvable")
    can_view_salary = await _user_has_permission(db, user, "rh.salaries.view")
    data = payload.model_dump(exclude_unset=True)
    if not can_view_salary:
        data.pop("salaire_base", None)
        data.pop("devise", None)
    for key, value in data.items():
        setattr(contract, key, value)
    await db.commit()
    await db.refresh(contract)
    return _hide_salary(HRContractOut.model_validate(contract), can_view_salary)


@router.get("/leaves", response_model=list[HRLeaveOut], dependencies=[Depends(has_permission("rh.leave.view"))])
async def list_leaves(employee_id: int | None = None, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)) -> list[HRLeave]:
    stmt = select(HRLeave).where(HRLeave.tenant_id == tenant_id)
    if employee_id:
        stmt = stmt.where(HRLeave.employee_id == employee_id)
    res = await db.execute(stmt.order_by(HRLeave.date_debut.desc()))
    return list(res.scalars().all())


@router.post("/leaves", response_model=HRLeaveOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(has_permission("rh.leave.request"))])
async def create_leave(payload: HRLeaveCreate, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)) -> HRLeave:
    await _employee_or_404(db, tenant_id, payload.employee_id)
    leave = HRLeave(**payload.model_dump(), tenant_id=tenant_id)
    db.add(leave)
    await db.commit()
    await db.refresh(leave)
    return leave


@router.patch("/leaves/{leave_id}", response_model=HRLeaveOut, dependencies=[Depends(has_permission("rh.leave.request"))])
async def update_leave(leave_id: int, payload: HRLeaveUpdate, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)) -> HRLeave:
    res = await db.execute(select(HRLeave).where(HRLeave.tenant_id == tenant_id, HRLeave.id == leave_id))
    leave = res.scalar_one_or_none()
    if leave is None:
        raise HTTPException(status_code=404, detail="Demande introuvable")
    if leave.statut not in {"brouillon", "soumis"}:
        raise HTTPException(status_code=400, detail="Demande déjà traitée")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(leave, key, value)
    await db.commit()
    await db.refresh(leave)
    return leave


@router.post("/leaves/{leave_id}/submit", response_model=HRLeaveOut, dependencies=[Depends(has_permission("rh.leave.request"))])
async def submit_leave(leave_id: int, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)) -> HRLeave:
    res = await db.execute(select(HRLeave).where(HRLeave.tenant_id == tenant_id, HRLeave.id == leave_id))
    leave = res.scalar_one_or_none()
    if leave is None:
        raise HTTPException(status_code=404, detail="Demande introuvable")
    if leave.statut != "brouillon":
        raise HTTPException(status_code=400, detail="Seules les demandes brouillon peuvent être soumises")
    leave.statut = "soumis"
    await db.commit()
    await db.refresh(leave)
    return leave


@router.post("/leaves/{leave_id}/{decision}", response_model=HRLeaveOut, dependencies=[Depends(has_permission("rh.leave.approve"))])
async def decide_leave(decision: str, leave_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user), tenant_id: int = Depends(get_current_tenant_id)) -> HRLeave:
    if decision not in {"approve", "reject"}:
        raise HTTPException(status_code=404, detail="Action inconnue")
    res = await db.execute(select(HRLeave).where(HRLeave.tenant_id == tenant_id, HRLeave.id == leave_id))
    leave = res.scalar_one_or_none()
    if leave is None:
        raise HTTPException(status_code=404, detail="Demande introuvable")
    if leave.statut != "soumis":
        raise HTTPException(status_code=400, detail="Seules les demandes soumises peuvent être validées")
    leave.statut = "approuvé" if decision == "approve" else "rejeté"
    leave.validateur_id = user.id
    await db.commit()
    await db.refresh(leave)
    return leave


@router.get("/documents", response_model=list[HRDocumentOut], dependencies=[Depends(has_permission("rh.documents.view"))])
async def list_documents(employee_id: int | None = None, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)) -> list[HRDocument]:
    stmt = select(HRDocument).where(HRDocument.tenant_id == tenant_id)
    if employee_id:
        stmt = stmt.where(HRDocument.employee_id == employee_id)
    res = await db.execute(stmt.order_by(HRDocument.date_upload.desc()))
    return list(res.scalars().all())


@router.post("/documents", response_model=HRDocumentOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(has_permission("rh.documents.manage"))])
async def create_document(payload: HRDocumentCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user), tenant_id: int = Depends(get_current_tenant_id)) -> HRDocument:
    await _employee_or_404(db, tenant_id, payload.employee_id)
    document = HRDocument(**payload.model_dump(), tenant_id=tenant_id, uploaded_by=user.id)
    db.add(document)
    await db.commit()
    await db.refresh(document)
    return document


@router.patch("/documents/{document_id}", response_model=HRDocumentOut, dependencies=[Depends(has_permission("rh.documents.manage"))])
async def update_document(document_id: int, payload: HRDocumentUpdate, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)) -> HRDocument:
    res = await db.execute(select(HRDocument).where(HRDocument.tenant_id == tenant_id, HRDocument.id == document_id))
    document = res.scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail="Document introuvable")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(document, key, value)
    await db.commit()
    await db.refresh(document)
    return document


# ─── Leave Allocations ────────────────────────────────────────────────────────

@router.get("/leave-allocations", response_model=list[HRLeaveAllocationOut], dependencies=[Depends(has_permission("rh.leave.view"))])
async def list_leave_allocations(
    employee_id: int | None = None,
    annee: int | None = None,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[HRLeaveAllocation]:
    stmt = select(HRLeaveAllocation).where(HRLeaveAllocation.tenant_id == tenant_id)
    if employee_id:
        stmt = stmt.where(HRLeaveAllocation.employee_id == employee_id)
    if annee:
        stmt = stmt.where(HRLeaveAllocation.annee == annee)
    res = await db.execute(stmt.order_by(HRLeaveAllocation.annee.desc(), HRLeaveAllocation.type_absence))
    return list(res.scalars().all())


@router.post("/leave-allocations", response_model=HRLeaveAllocationOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(has_permission("rh.leave.approve"))])
async def create_leave_allocation(payload: HRLeaveAllocationCreate, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)) -> HRLeaveAllocation:
    await _employee_or_404(db, tenant_id, payload.employee_id)
    alloc = HRLeaveAllocation(**payload.model_dump(), tenant_id=tenant_id)
    db.add(alloc)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Allocation déjà existante pour cet employé/type/année")
    await db.refresh(alloc)
    return alloc


@router.patch("/leave-allocations/{alloc_id}", response_model=HRLeaveAllocationOut, dependencies=[Depends(has_permission("rh.leave.approve"))])
async def update_leave_allocation(alloc_id: int, payload: HRLeaveAllocationUpdate, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)) -> HRLeaveAllocation:
    res = await db.execute(select(HRLeaveAllocation).where(HRLeaveAllocation.tenant_id == tenant_id, HRLeaveAllocation.id == alloc_id))
    alloc = res.scalar_one_or_none()
    if alloc is None:
        raise HTTPException(status_code=404, detail="Allocation introuvable")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(alloc, key, value)
    await db.commit()
    await db.refresh(alloc)
    return alloc


@router.get("/leave-allocations/balance", response_model=list[HRLeaveBalanceOut], dependencies=[Depends(has_permission("rh.leave.view"))])
async def get_leave_balance(
    employee_id: int,
    annee: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[HRLeaveBalanceOut]:
    allocations_res = await db.execute(
        select(HRLeaveAllocation).where(
            HRLeaveAllocation.tenant_id == tenant_id,
            HRLeaveAllocation.employee_id == employee_id,
            HRLeaveAllocation.annee == annee,
        )
    )
    allocations = allocations_res.scalars().all()
    result = []
    for alloc in allocations:
        used_res = await db.scalar(
            select(func.coalesce(func.sum(HRLeave.nombre_jours), 0)).where(
                HRLeave.tenant_id == tenant_id,
                HRLeave.employee_id == employee_id,
                HRLeave.type_absence == alloc.type_absence,
                HRLeave.statut == "approuvé",
                func.extract("year", HRLeave.date_debut) == annee,
            )
        )
        jours_utilises = Decimal(used_res or 0)
        solde = alloc.jours_alloues + alloc.report_annee_precedente - jours_utilises
        result.append(
            HRLeaveBalanceOut(
                employee_id=employee_id,
                type_absence=alloc.type_absence,
                annee=annee,
                jours_alloues=alloc.jours_alloues,
                report_annee_precedente=alloc.report_annee_precedente,
                jours_utilises=jours_utilises,
                solde=solde,
            )
        )
    return result


# ─── Attendances ──────────────────────────────────────────────────────────────

@router.get("/attendances", response_model=list[HRAttendanceOut], dependencies=[Depends(has_permission("rh.attendance.view"))])
async def list_attendances(
    employee_id: int | None = None,
    mois: int | None = None,
    annee: int | None = None,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[HRAttendance]:
    stmt = select(HRAttendance).where(HRAttendance.tenant_id == tenant_id)
    if employee_id:
        stmt = stmt.where(HRAttendance.employee_id == employee_id)
    if mois:
        stmt = stmt.where(func.extract("month", HRAttendance.date_presence) == mois)
    if annee:
        stmt = stmt.where(func.extract("year", HRAttendance.date_presence) == annee)
    res = await db.execute(stmt.order_by(HRAttendance.date_presence.desc()))
    return list(res.scalars().all())


@router.post("/attendances", response_model=HRAttendanceOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(has_permission("rh.attendance.manage"))])
async def create_attendance(payload: HRAttendanceCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user), tenant_id: int = Depends(get_current_tenant_id)) -> HRAttendance:
    await _employee_or_404(db, tenant_id, payload.employee_id)
    att = HRAttendance(**payload.model_dump(), tenant_id=tenant_id, saisi_par=user.id)
    db.add(att)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Présence déjà saisie pour cet employé ce jour")
    await db.refresh(att)
    return att


@router.patch("/attendances/{att_id}", response_model=HRAttendanceOut, dependencies=[Depends(has_permission("rh.attendance.manage"))])
async def update_attendance(att_id: int, payload: HRAttendanceUpdate, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)) -> HRAttendance:
    res = await db.execute(select(HRAttendance).where(HRAttendance.tenant_id == tenant_id, HRAttendance.id == att_id))
    att = res.scalar_one_or_none()
    if att is None:
        raise HTTPException(status_code=404, detail="Présence introuvable")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(att, key, value)
    await db.commit()
    await db.refresh(att)
    return att


@router.get("/attendances/summary", response_model=HRAttendanceSummaryOut, dependencies=[Depends(has_permission("rh.attendance.view"))])
async def attendance_summary(
    mois: int,
    annee: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> HRAttendanceSummaryOut:
    rows_res = await db.execute(
        select(HRAttendance.statut_presence).where(
            HRAttendance.tenant_id == tenant_id,
            func.extract("month", HRAttendance.date_presence) == mois,
            func.extract("year", HRAttendance.date_presence) == annee,
        )
    )
    rows = rows_res.scalars().all()
    total = len(rows)
    presents = sum(1 for s in rows if s == "present")
    absents = sum(1 for s in rows if s == "absent")
    demi = sum(1 for s in rows if s == "demi_journee")
    conges = sum(1 for s in rows if s == "conge")
    teletravail = sum(1 for s in rows if s == "teletravail")
    taux: float | None = None
    if total > 0:
        taux = round((presents + demi * 0.5) / total * 100, 2)
    return HRAttendanceSummaryOut(
        mois=mois,
        annee=annee,
        total_jours_saisis=total,
        presents=presents,
        absents=absents,
        demi_journees=demi,
        conges=conges,
        teletravail=teletravail,
        taux_presence=taux,
    )


@router.post("/attendances/batch", response_model=list[HRAttendanceOut], dependencies=[Depends(has_permission("rh.attendance.manage"))])
async def batch_create_attendance(payload: HRAttendanceBatchCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user), tenant_id: int = Depends(get_current_tenant_id)) -> list[HRAttendance]:
    created: list[HRAttendance] = []
    for emp_id in payload.employee_ids:
        existing_res = await db.execute(
            select(HRAttendance).where(
                HRAttendance.tenant_id == tenant_id,
                HRAttendance.employee_id == emp_id,
                HRAttendance.date_presence == payload.date,
            )
        )
        existing = existing_res.scalar_one_or_none()
        if existing:
            existing.statut_presence = payload.statut
            created.append(existing)
        else:
            att = HRAttendance(
                tenant_id=tenant_id,
                employee_id=emp_id,
                date_presence=payload.date,
                statut_presence=payload.statut,
                saisi_par=user.id,
            )
            db.add(att)
            created.append(att)
    await db.commit()
    for att in created:
        await db.refresh(att)
    return created


# ─── Payroll ──────────────────────────────────────────────────────────────────

@router.get("/payroll-entries", response_model=list[HRPayrollEntryOut], dependencies=[Depends(has_permission("rh.payroll.view"))])
async def list_payroll_entries(
    annee: int | None = None,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[HRPayrollEntry]:
    stmt = select(HRPayrollEntry).where(HRPayrollEntry.tenant_id == tenant_id)
    if annee:
        stmt = stmt.where(HRPayrollEntry.annee == annee)
    res = await db.execute(stmt.order_by(HRPayrollEntry.annee.desc(), HRPayrollEntry.mois.desc()))
    return list(res.scalars().all())


@router.post("/payroll-entries", response_model=HRPayrollEntryOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(has_permission("rh.payroll.prepare"))])
async def create_payroll_entry(payload: HRPayrollEntryCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user), tenant_id: int = Depends(get_current_tenant_id)) -> HRPayrollEntry:
    entry = HRPayrollEntry(**payload.model_dump(), tenant_id=tenant_id, created_by=user.id)
    db.add(entry)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Un run de paie existe déjà pour ce mois/année")
    await db.refresh(entry)
    return entry


@router.post("/payroll-entries/{entry_id}/generate-slips", response_model=list[HRSalarySlipOut], dependencies=[Depends(has_permission("rh.payroll.prepare"))])
async def generate_salary_slips(entry_id: int, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)) -> list[HRSalarySlip]:
    entry_res = await db.execute(select(HRPayrollEntry).where(HRPayrollEntry.tenant_id == tenant_id, HRPayrollEntry.id == entry_id))
    entry = entry_res.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Run de paie introuvable")
    if entry.statut != "brouillon":
        raise HTTPException(status_code=400, detail="Seuls les runs en brouillon peuvent générer des bulletins")
    # Get active employees with active contract
    active_emp_res = await db.execute(
        select(HREmployee.id, HRContract.salaire_base, HRContract.devise).join(
            HRContract,
            (HRContract.employee_id == HREmployee.id) & (HRContract.statut == "actif") & (HRContract.tenant_id == tenant_id),
        ).where(HREmployee.tenant_id == tenant_id, HREmployee.statut == "actif")
    )
    active_employees = active_emp_res.all()
    slips: list[HRSalarySlip] = []
    for emp_id, salaire_base, devise in active_employees:
        existing_res = await db.execute(
            select(HRSalarySlip).where(HRSalarySlip.payroll_entry_id == entry_id, HRSalarySlip.employee_id == emp_id)
        )
        existing = existing_res.scalar_one_or_none()
        if existing:
            slips.append(existing)
            continue
        net = (salaire_base or Decimal("0"))
        slip = HRSalarySlip(
            tenant_id=tenant_id,
            payroll_entry_id=entry_id,
            employee_id=emp_id,
            salaire_base=salaire_base or Decimal("0"),
            net_a_payer=net,
            devise=devise or "USD",
        )
        db.add(slip)
        slips.append(slip)
    entry.nb_bulletins = len(slips)
    await db.commit()
    for slip in slips:
        await db.refresh(slip)
    return slips


@router.post("/payroll-entries/{entry_id}/validate", response_model=HRPayrollEntryOut, dependencies=[Depends(has_permission("rh.payroll.validate"))])
async def validate_payroll_entry(entry_id: int, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)) -> HRPayrollEntry:
    entry_res = await db.execute(select(HRPayrollEntry).where(HRPayrollEntry.tenant_id == tenant_id, HRPayrollEntry.id == entry_id))
    entry = entry_res.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Run de paie introuvable")
    if entry.statut == "validé":
        raise HTTPException(status_code=400, detail="Run déjà validé")
    entry.statut = "validé"
    # Validate all slips
    await db.execute(
        select(HRSalarySlip).where(HRSalarySlip.payroll_entry_id == entry_id)
    )
    slips_res = await db.execute(select(HRSalarySlip).where(HRSalarySlip.payroll_entry_id == entry_id))
    for slip in slips_res.scalars().all():
        slip.statut = "validé"
    await db.commit()
    await db.refresh(entry)
    return entry


@router.get("/payroll-entries/{entry_id}/slips", response_model=list[HRSalarySlipOut], dependencies=[Depends(has_permission("rh.payroll.view"))])
async def list_entry_slips(entry_id: int, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)) -> list[HRSalarySlip]:
    entry_res = await db.execute(select(HRPayrollEntry).where(HRPayrollEntry.tenant_id == tenant_id, HRPayrollEntry.id == entry_id))
    if entry_res.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Run de paie introuvable")
    res = await db.execute(select(HRSalarySlip).where(HRSalarySlip.payroll_entry_id == entry_id).order_by(HRSalarySlip.employee_id))
    return list(res.scalars().all())


@router.get("/salary-slips", response_model=list[HRSalarySlipOut], dependencies=[Depends(has_permission("rh.payslips.view"))])
async def list_salary_slips(
    employee_id: int | None = None,
    annee: int | None = None,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[HRSalarySlip]:
    stmt = select(HRSalarySlip).where(HRSalarySlip.tenant_id == tenant_id)
    if employee_id:
        stmt = stmt.where(HRSalarySlip.employee_id == employee_id)
    if annee:
        stmt = stmt.join(HRPayrollEntry, HRPayrollEntry.id == HRSalarySlip.payroll_entry_id).where(HRPayrollEntry.annee == annee)
    res = await db.execute(stmt.order_by(HRSalarySlip.created_at.desc()))
    return list(res.scalars().all())


settings_router = APIRouter(prefix="/settings")


@settings_router.get(
    "/services",
    response_model=list[HRServiceOut],
    dependencies=[Depends(has_any_permission(["rh.settings.manage", "rh.dashboard.view", "rh.employees.view", "rh.contracts.view", "rh.leave.view", "rh.documents.view"]))],
)
async def list_hr_services(db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)) -> list[HRService]:
    res = await db.execute(select(HRService).where(HRService.tenant_id == tenant_id).order_by(HRService.code.asc()))
    return list(res.scalars().all())


@settings_router.post("/services", response_model=HRServiceOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(has_permission("rh.settings.manage"))])
async def create_hr_service(payload: HRServiceCreate, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)) -> HRService:
    row = HRService(**payload.model_dump(), tenant_id=tenant_id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@settings_router.patch("/services/{service_id}", response_model=HRServiceOut, dependencies=[Depends(has_permission("rh.settings.manage"))])
async def update_hr_service(service_id: int, payload: HRServiceUpdate, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)) -> HRService:
    res = await db.execute(select(HRService).where(HRService.tenant_id == tenant_id, HRService.id == service_id))
    row = res.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Service RH introuvable")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    await db.commit()
    await db.refresh(row)
    return row


@settings_router.get(
    "/functions",
    response_model=list[HRFunctionOut],
    dependencies=[Depends(has_any_permission(["rh.settings.manage", "rh.dashboard.view", "rh.employees.view", "rh.contracts.view", "rh.leave.view", "rh.documents.view"]))],
)
async def list_hr_functions(db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)) -> list[HRFunction]:
    res = await db.execute(select(HRFunction).where(HRFunction.tenant_id == tenant_id).order_by(HRFunction.libelle.asc()))
    return list(res.scalars().all())


@settings_router.post("/functions", response_model=HRFunctionOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(has_permission("rh.settings.manage"))])
async def create_hr_function(payload: HRFunctionCreate, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)) -> HRFunction:
    row = HRFunction(**payload.model_dump(), tenant_id=tenant_id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@settings_router.patch("/functions/{function_id}", response_model=HRFunctionOut, dependencies=[Depends(has_permission("rh.settings.manage"))])
async def update_hr_function(function_id: int, payload: HRFunctionUpdate, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)) -> HRFunction:
    res = await db.execute(select(HRFunction).where(HRFunction.tenant_id == tenant_id, HRFunction.id == function_id))
    row = res.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Fonction RH introuvable")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    await db.commit()
    await db.refresh(row)
    return row


def _validate_reference_category(category: str) -> str:
    if category not in ALLOWED_REFERENCE_CATEGORIES:
        raise HTTPException(status_code=404, detail="Référentiel RH inconnu")
    return category


@settings_router.get("/references/{category}", response_model=list[HRReferenceOut], dependencies=[Depends(has_permission("rh.settings.manage"))])
async def list_hr_references(category: str, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)) -> list[HRReference]:
    category = _validate_reference_category(category)
    res = await db.execute(
        select(HRReference)
        .where(HRReference.tenant_id == tenant_id, HRReference.category == category)
        .order_by(HRReference.libelle.asc())
    )
    return list(res.scalars().all())


@settings_router.post("/references/{category}", response_model=HRReferenceOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(has_permission("rh.settings.manage"))])
async def create_hr_reference(category: str, payload: HRReferenceCreate, db: AsyncSession = Depends(get_db), tenant_id: int = Depends(get_current_tenant_id)) -> HRReference:
    category = _validate_reference_category(category)
    row = HRReference(**payload.model_dump(), category=category, tenant_id=tenant_id)
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Code déjà utilisé pour ce référentiel")
    await db.refresh(row)
    return row


@settings_router.patch("/references/{category}/{reference_id}", response_model=HRReferenceOut, dependencies=[Depends(has_permission("rh.settings.manage"))])
async def update_hr_reference(
    category: str,
    reference_id: int,
    payload: HRReferenceUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> HRReference:
    category = _validate_reference_category(category)
    res = await db.execute(
        select(HRReference).where(
            HRReference.tenant_id == tenant_id,
            HRReference.category == category,
            HRReference.id == reference_id,
        )
    )
    row = res.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Référentiel introuvable")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Code déjà utilisé pour ce référentiel")
    await db.refresh(row)
    return row


router.include_router(settings_router)


# ─── Evaluations ──────────────────────────────────────────────────────────────

@router.get("/evaluations", response_model=list[HREvaluationOut], dependencies=[Depends(has_permission("rh.evaluations.view"))])
async def list_evaluations(
    employee_id: int | None = Query(default=None),
    annee: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[HREvaluation]:
    q = select(HREvaluation).where(HREvaluation.tenant_id == tenant_id)
    if employee_id is not None:
        q = q.where(HREvaluation.employee_id == employee_id)
    if annee is not None:
        q = q.where(HREvaluation.annee == annee)
    result = await db.execute(q.order_by(HREvaluation.annee.desc(), HREvaluation.created_at.desc()))
    return list(result.scalars().all())


@router.post("/evaluations", response_model=HREvaluationOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(has_permission("rh.evaluations.manage"))])
async def create_evaluation(
    body: HREvaluationCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> HREvaluation:
    await _employee_or_404(db, tenant_id, body.employee_id)
    row = HREvaluation(tenant_id=tenant_id, **body.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.patch("/evaluations/{eval_id}", response_model=HREvaluationOut, dependencies=[Depends(has_permission("rh.evaluations.manage"))])
async def update_evaluation(
    eval_id: int,
    body: HREvaluationUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> HREvaluation:
    row = await db.scalar(select(HREvaluation).where(HREvaluation.tenant_id == tenant_id, HREvaluation.id == eval_id))
    if not row:
        raise HTTPException(status_code=404, detail="Évaluation introuvable")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(row, k, v)
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/evaluations/{eval_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None, dependencies=[Depends(has_permission("rh.evaluations.manage"))])
async def delete_evaluation(
    eval_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> None:
    row = await db.scalar(select(HREvaluation).where(HREvaluation.tenant_id == tenant_id, HREvaluation.id == eval_id))
    if not row:
        raise HTTPException(status_code=404, detail="Évaluation introuvable")
    await db.delete(row)
    await db.commit()


# ─── Sanctions ────────────────────────────────────────────────────────────────

@router.get("/sanctions", response_model=list[HRSanctionOut], dependencies=[Depends(has_permission("rh.sanctions.view"))])
async def list_sanctions(
    employee_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[HRSanction]:
    q = select(HRSanction).where(HRSanction.tenant_id == tenant_id)
    if employee_id is not None:
        q = q.where(HRSanction.employee_id == employee_id)
    result = await db.execute(q.order_by(HRSanction.date_sanction.desc()))
    return list(result.scalars().all())


@router.post("/sanctions", response_model=HRSanctionOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(has_permission("rh.sanctions.manage"))])
async def create_sanction(
    body: HRSanctionCreate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> HRSanction:
    await _employee_or_404(db, tenant_id, body.employee_id)
    row = HRSanction(tenant_id=tenant_id, **body.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.patch("/sanctions/{sanction_id}", response_model=HRSanctionOut, dependencies=[Depends(has_permission("rh.sanctions.manage"))])
async def update_sanction(
    sanction_id: int,
    body: HRSanctionUpdate,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> HRSanction:
    row = await db.scalar(select(HRSanction).where(HRSanction.tenant_id == tenant_id, HRSanction.id == sanction_id))
    if not row:
        raise HTTPException(status_code=404, detail="Sanction introuvable")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(row, k, v)
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/sanctions/{sanction_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None, dependencies=[Depends(has_permission("rh.sanctions.manage"))])
async def delete_sanction(
    sanction_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> None:
    row = await db.scalar(select(HRSanction).where(HRSanction.tenant_id == tenant_id, HRSanction.id == sanction_id))
    if not row:
        raise HTTPException(status_code=404, detail="Sanction introuvable")
    await db.delete(row)
    await db.commit()


# ─── Rapports RH ──────────────────────────────────────────────────────────────

@router.get("/rapports", response_model=HRReportOut, dependencies=[Depends(has_permission("rh.reports.view"))])
async def get_hr_report(
    annee: int = Query(default=None),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> dict:
    from datetime import date as date_cls
    if annee is None:
        annee = date_cls.today().year

    # Effectifs par service
    emp_rows = await db.execute(
        select(HREmployee).where(HREmployee.tenant_id == tenant_id)
        .options(selectinload(HREmployee.service))
    )
    employees = list(emp_rows.scalars().all())
    service_map: dict[str, dict] = {}
    for e in employees:
        svc = e.service.libelle if e.service else "Non affecté"
        if svc not in service_map:
            service_map[svc] = {"service": svc, "total": 0, "actifs": 0, "en_conge": 0}
        service_map[svc]["total"] += 1
        if e.statut == "actif":
            service_map[svc]["actifs"] += 1
        elif e.statut == "en_conge":
            service_map[svc]["en_conge"] += 1
    effectifs = sorted(service_map.values(), key=lambda x: x["total"], reverse=True)

    # Présences par mois (année en cours)
    presences = []
    for mois in range(1, 13):
        summary_rows = await db.execute(
            select(HRAttendance.statut_presence, func.count().label("cnt"))
            .where(
                HRAttendance.tenant_id == tenant_id,
                func.extract("year", HRAttendance.date_presence) == annee,
                func.extract("month", HRAttendance.date_presence) == mois,
            )
            .group_by(HRAttendance.statut_presence)
        )
        counts = {r.statut_presence: r.cnt for r in summary_rows}
        total = sum(counts.values())
        if total == 0:
            continue
        presents = counts.get("present", 0)
        taux = round(presents / total * 100, 1) if total > 0 else None
        presences.append({
            "mois": mois, "annee": annee,
            "presents": presents,
            "absents": counts.get("absent", 0),
            "demi_journees": counts.get("demi_journee", 0),
            "conges": counts.get("conge", 0),
            "taux_presence": taux,
        })

    # Masse salariale par mois validée
    payroll_rows = await db.execute(
        select(HRPayrollEntry).where(
            HRPayrollEntry.tenant_id == tenant_id,
            HRPayrollEntry.annee == annee,
            HRPayrollEntry.statut == "validé",
        ).order_by(HRPayrollEntry.mois)
    )
    masse_sal = []
    for entry in payroll_rows.scalars().all():
        slip_rows = await db.execute(
            select(func.sum(HRSalarySlip.net_a_payer), HRSalarySlip.devise)
            .where(HRSalarySlip.payroll_entry_id == entry.id)
            .group_by(HRSalarySlip.devise)
        )
        for total_net, devise in slip_rows:
            masse_sal.append({
                "mois": entry.mois, "annee": annee,
                "total_net": total_net or 0,
                "nb_bulletins": entry.nb_bulletins,
                "devise": devise or "USD",
            })

    # Congés par type
    leave_rows = await db.execute(
        select(
            HRLeave.type_absence,
            func.count().label("total_demandes"),
            func.coalesce(func.sum(HRLeave.nombre_jours), 0).label("total_jours"),
            func.sum(func.cast(HRLeave.statut == "approuvé", Integer)).label("approuves"),
            func.sum(func.cast(HRLeave.statut == "soumis", Integer)).label("en_attente"),
        )
        .where(
            HRLeave.tenant_id == tenant_id,
            func.extract("year", HRLeave.date_debut) == annee,
        )
        .group_by(HRLeave.type_absence)
        .order_by(func.count().desc())
    )
    conges = [
        {
            "type_absence": r.type_absence,
            "total_demandes": r.total_demandes,
            "total_jours": r.total_jours,
            "approuves": r.approuves or 0,
            "en_attente": r.en_attente or 0,
        }
        for r in leave_rows
    ]

    return {
        "effectifs_par_service": effectifs,
        "presences": presences,
        "masse_salariale": masse_sal,
        "conges_par_type": conges,
    }
