"""Tests for HR improvements: leave allocations, attendance, payroll, employee exit fields."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.hr import (
    HRAttendance,
    HRContract,
    HREmployee,
    HRLeave,
    HRLeaveAllocation,
    HRPayrollEntry,
    HRSalarySlip,
)
from app.models.organisation import Organisation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_org(db_session, slug: str) -> Organisation:
    org = Organisation(nom=f"Org {slug}", slug=slug)
    db_session.add(org)
    await db_session.flush()
    return org


async def _make_employee(db_session, tenant_id: int, matricule: str = "E-001", statut: str = "actif") -> HREmployee:
    emp = HREmployee(
        tenant_id=tenant_id,
        matricule=matricule,
        nom="Doe",
        prenom="John",
        statut=statut,
    )
    db_session.add(emp)
    await db_session.flush()
    return emp


async def _make_contract(db_session, tenant_id: int, employee_id: int, salaire: Decimal = Decimal("1000"), statut: str = "actif") -> HRContract:
    contract = HRContract(
        tenant_id=tenant_id,
        employee_id=employee_id,
        type_contrat="CDI",
        date_debut=date(2024, 1, 1),
        poste="Développeur",
        salaire_base=salaire,
        devise="USD",
        statut=statut,
    )
    db_session.add(contract)
    await db_session.flush()
    return contract


# ---------------------------------------------------------------------------
# 1. Leave allocation prevents excess usage calculation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_leave_allocation_prevents_excess(db_session):
    """Allocation 15j + 0 report - 10j approuvé = solde 5j."""
    org = await _make_org(db_session, "alloc-excess")
    emp = await _make_employee(db_session, org.id, "E-100")

    alloc = HRLeaveAllocation(
        tenant_id=org.id,
        employee_id=emp.id,
        type_absence="congé annuel",
        annee=2026,
        jours_alloues=Decimal("15"),
        report_annee_precedente=Decimal("0"),
    )
    db_session.add(alloc)
    await db_session.flush()

    leave = HRLeave(
        tenant_id=org.id,
        employee_id=emp.id,
        type_absence="congé annuel",
        date_debut=date(2026, 1, 6),
        date_fin=date(2026, 1, 17),
        nombre_jours=Decimal("10"),
        statut="approuvé",
    )
    db_session.add(leave)
    await db_session.commit()

    from sqlalchemy import func
    used = await db_session.scalar(
        select(func.coalesce(func.sum(HRLeave.nombre_jours), 0)).where(
            HRLeave.tenant_id == org.id,
            HRLeave.employee_id == emp.id,
            HRLeave.type_absence == "congé annuel",
            HRLeave.statut == "approuvé",
            func.extract("year", HRLeave.date_debut) == 2026,
        )
    )
    solde = alloc.jours_alloues + alloc.report_annee_precedente - Decimal(str(used))
    assert solde == Decimal("5"), f"Expected 5, got {solde}"


# ---------------------------------------------------------------------------
# 2. Leave balance computed correctly with report
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_leave_balance_computed_correctly(db_session):
    """Allocation 20j + report 5j - 8j utilisés = solde 17j."""
    org = await _make_org(db_session, "alloc-balance")
    emp = await _make_employee(db_session, org.id, "E-200")

    alloc = HRLeaveAllocation(
        tenant_id=org.id,
        employee_id=emp.id,
        type_absence="congé annuel",
        annee=2026,
        jours_alloues=Decimal("20"),
        report_annee_precedente=Decimal("5"),
    )
    db_session.add(alloc)
    await db_session.flush()

    leave = HRLeave(
        tenant_id=org.id,
        employee_id=emp.id,
        type_absence="congé annuel",
        date_debut=date(2026, 3, 2),
        date_fin=date(2026, 3, 11),
        nombre_jours=Decimal("8"),
        statut="approuvé",
    )
    db_session.add(leave)
    await db_session.commit()

    from sqlalchemy import func
    used = await db_session.scalar(
        select(func.coalesce(func.sum(HRLeave.nombre_jours), 0)).where(
            HRLeave.tenant_id == org.id,
            HRLeave.employee_id == emp.id,
            HRLeave.type_absence == "congé annuel",
            HRLeave.statut == "approuvé",
            func.extract("year", HRLeave.date_debut) == 2026,
        )
    )
    solde = alloc.jours_alloues + alloc.report_annee_precedente - Decimal(str(used))
    assert solde == Decimal("17"), f"Expected 17, got {solde}"


# ---------------------------------------------------------------------------
# 3. Attendance unique per employee/day
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_attendance_unique_per_day(db_session):
    """Creating 2 attendance records for the same employee/day raises IntegrityError."""
    org = await _make_org(db_session, "att-unique")
    emp = await _make_employee(db_session, org.id, "E-300")

    att1 = HRAttendance(
        tenant_id=org.id,
        employee_id=emp.id,
        date_presence=date(2026, 6, 1),
        statut_presence="present",
    )
    db_session.add(att1)
    await db_session.flush()

    att2 = HRAttendance(
        tenant_id=org.id,
        employee_id=emp.id,
        date_presence=date(2026, 6, 1),  # Same date → should fail
        statut_presence="absent",
    )
    db_session.add(att2)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


# ---------------------------------------------------------------------------
# 4. Attendance batch create
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_attendance_batch_create(db_session):
    """Batch creation for 3 employees creates 3 attendance entries."""
    org = await _make_org(db_session, "att-batch")
    emp1 = await _make_employee(db_session, org.id, "E-401")
    emp2 = await _make_employee(db_session, org.id, "E-402")
    emp3 = await _make_employee(db_session, org.id, "E-403")

    target_date = date(2026, 6, 10)
    for emp in [emp1, emp2, emp3]:
        att = HRAttendance(
            tenant_id=org.id,
            employee_id=emp.id,
            date_presence=target_date,
            statut_presence="present",
        )
        db_session.add(att)
    await db_session.commit()

    from sqlalchemy import func
    count = await db_session.scalar(
        select(func.count()).select_from(HRAttendance).where(
            HRAttendance.tenant_id == org.id,
            HRAttendance.date_presence == target_date,
        )
    )
    assert count == 3


# ---------------------------------------------------------------------------
# 5. Attendance monthly summary / taux de présence
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_attendance_monthly_summary(db_session):
    """20 present + 5 absent → taux_presence = 80.0%."""
    org = await _make_org(db_session, "att-summary")
    emp = await _make_employee(db_session, org.id, "E-500")

    # 20 présents + 5 absents = 25 jours saisis
    for day in range(1, 21):
        db_session.add(HRAttendance(
            tenant_id=org.id,
            employee_id=emp.id,
            date_presence=date(2026, 6, day),
            statut_presence="present",
        ))
    for day in range(21, 26):
        db_session.add(HRAttendance(
            tenant_id=org.id,
            employee_id=emp.id,
            date_presence=date(2026, 6, day),
            statut_presence="absent",
        ))
    await db_session.commit()

    rows_res = await db_session.execute(
        select(HRAttendance.statut_presence).where(
            HRAttendance.tenant_id == org.id,
            HRAttendance.employee_id == emp.id,
        )
    )
    rows = rows_res.scalars().all()
    total = len(rows)
    presents = sum(1 for s in rows if s == "present")
    demi = sum(1 for s in rows if s == "demi_journee")
    taux = (presents + demi * 0.5) / total * 100

    assert total == 25
    assert presents == 20
    assert abs(taux - 80.0) < 0.01, f"Expected 80.0%, got {taux}"


# ---------------------------------------------------------------------------
# 6. Payroll entry unique per month
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_payroll_entry_unique_per_month(db_session):
    """Creating 2 payroll entries for mois=6, annee=2026 raises IntegrityError."""
    org = await _make_org(db_session, "payroll-unique")

    entry1 = HRPayrollEntry(tenant_id=org.id, mois=6, annee=2026, statut="brouillon")
    db_session.add(entry1)
    await db_session.flush()

    entry2 = HRPayrollEntry(tenant_id=org.id, mois=6, annee=2026, statut="brouillon")
    db_session.add(entry2)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


# ---------------------------------------------------------------------------
# 7. Generate salary slips — only active employees with active contract
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_salary_slips(db_session):
    """3 active employees with active contract + 1 inactive → only 3 slips, IPR/CNSS computed."""
    from app.api.v1.endpoints.hr import generate_salary_slips

    org = await _make_org(db_session, "payroll-generate")
    org.taux_change_interne = Decimal("2500")
    await db_session.flush()

    emp1 = await _make_employee(db_session, org.id, "E-701", statut="actif")
    emp2 = await _make_employee(db_session, org.id, "E-702", statut="actif")
    emp3 = await _make_employee(db_session, org.id, "E-703", statut="actif")
    emp_inactive = await _make_employee(db_session, org.id, "E-704", statut="sorti")

    for emp in [emp1, emp2, emp3]:
        await _make_contract(db_session, org.id, emp.id, Decimal("1200"))
    # Inactive employee also has contract but statut is 'sorti'
    await _make_contract(db_session, org.id, emp_inactive.id, Decimal("800"))

    entry = HRPayrollEntry(tenant_id=org.id, mois=6, annee=2026, statut="brouillon")
    db_session.add(entry)
    await db_session.commit()

    slips_created = await generate_salary_slips(entry.id, db_session, org.id)

    assert len(slips_created) == 3, f"Expected 3 slips, got {len(slips_created)}"
    slip_emp_ids = {s.employee_id for s in slips_created}
    assert emp_inactive.id not in slip_emp_ids, "Inactive employee should not have a slip"
    for slip in slips_created:
        assert slip.ipr > Decimal("0"), "IPR should be computed, not left at 0"
        assert slip.cnss_salarie == (slip.salaire_base * Decimal("0.05")).quantize(Decimal("0.01"))
        assert slip.net_a_payer == slip.salaire_base - slip.ipr - slip.cnss_salarie
        assert slip.net_a_payer < slip.salaire_base, "Net pay must be lower than gross once deductions apply"


@pytest.mark.asyncio
async def test_generate_salary_slips_usd_without_exchange_rate_fails_cleanly(db_session):
    """USD contract + no org taux_change_interne → 400, not a raw crash."""
    from fastapi import HTTPException

    from app.api.v1.endpoints.hr import generate_salary_slips

    org = await _make_org(db_session, "payroll-no-rate")
    emp = await _make_employee(db_session, org.id, "E-900", statut="actif")
    await _make_contract(db_session, org.id, emp.id, Decimal("1200"))

    entry = HRPayrollEntry(tenant_id=org.id, mois=8, annee=2026, statut="brouillon")
    db_session.add(entry)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await generate_salary_slips(entry.id, db_session, org.id)
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# 8. Salary slip net calculation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_salary_slip_net_calculation(db_session):
    """salaire_base=1000 + primes=200 - retenues=150 → net=1050."""
    org = await _make_org(db_session, "payroll-net")
    emp = await _make_employee(db_session, org.id, "E-800")
    entry = HRPayrollEntry(tenant_id=org.id, mois=7, annee=2026, statut="brouillon")
    db_session.add(entry)
    await db_session.flush()

    salaire_base = Decimal("1000")
    primes = Decimal("200")
    retenues = Decimal("150")
    net = salaire_base + primes - retenues

    slip = HRSalarySlip(
        tenant_id=org.id,
        payroll_entry_id=entry.id,
        employee_id=emp.id,
        salaire_base=salaire_base,
        total_primes=primes,
        total_retenues=retenues,
        net_a_payer=net,
        devise="USD",
    )
    db_session.add(slip)
    await db_session.commit()
    await db_session.refresh(slip)

    assert slip.net_a_payer == Decimal("1050"), f"Expected 1050, got {slip.net_a_payer}"
    assert slip.salaire_base == Decimal("1000")
    assert slip.total_primes == Decimal("200")
    assert slip.total_retenues == Decimal("150")


# ---------------------------------------------------------------------------
# 9. Leave allocation multi-tenant isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_leave_allocation_multi_tenant(db_session):
    """Same matricule in 2 tenants — allocations are separate and isolated."""
    org_a = await _make_org(db_session, "alloc-mt-a")
    org_b = await _make_org(db_session, "alloc-mt-b")

    emp_a = await _make_employee(db_session, org_a.id, "E-001")
    emp_b = await _make_employee(db_session, org_b.id, "E-001")  # Same matricule, different tenant

    alloc_a = HRLeaveAllocation(
        tenant_id=org_a.id,
        employee_id=emp_a.id,
        type_absence="congé annuel",
        annee=2026,
        jours_alloues=Decimal("15"),
    )
    alloc_b = HRLeaveAllocation(
        tenant_id=org_b.id,
        employee_id=emp_b.id,
        type_absence="congé annuel",
        annee=2026,
        jours_alloues=Decimal("20"),
    )
    db_session.add_all([alloc_a, alloc_b])
    await db_session.commit()

    # Tenant A sees only its own allocation
    res_a = await db_session.execute(
        select(HRLeaveAllocation).where(HRLeaveAllocation.tenant_id == org_a.id)
    )
    allocs_a = res_a.scalars().all()
    assert len(allocs_a) == 1
    assert allocs_a[0].jours_alloues == Decimal("15")

    # Tenant B sees only its own allocation
    res_b = await db_session.execute(
        select(HRLeaveAllocation).where(HRLeaveAllocation.tenant_id == org_b.id)
    )
    allocs_b = res_b.scalars().all()
    assert len(allocs_b) == 1
    assert allocs_b[0].jours_alloues == Decimal("20")


# ---------------------------------------------------------------------------
# 10. Employee date_sortie — archive with exit date
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_employee_date_sortie(db_session):
    """Archiving an employee sets statut=sorti and date_sortie."""
    org = await _make_org(db_session, "emp-sortie")
    emp = await _make_employee(db_session, org.id, "E-900")
    assert emp.statut == "actif"

    exit_date = date(2026, 6, 30)
    emp.statut = "sorti"
    emp.date_sortie = exit_date
    emp.raison_sortie = "démission"
    await db_session.commit()
    await db_session.refresh(emp)

    assert emp.statut == "sorti"
    assert emp.date_sortie == exit_date
    assert emp.raison_sortie == "démission"
