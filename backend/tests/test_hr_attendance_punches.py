from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.hr import HRAttendancePunch, HRLeave
from app.services.hr_attendance_calc import calculate_daily_attendance


def _employee() -> SimpleNamespace:
    return SimpleNamespace(id=1, matricule="EMP001", nom="KIDIKALA", post_nom=None, prenom="Christian", service_id=None, service=None)


def _punch(hour: int, minute: int, event_type: str, punch_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        id=punch_id,
        employee_id=1,
        punched_at=datetime(2026, 8, 17, hour, minute, tzinfo=timezone.utc),
        event_type=event_type,
        source="DEVICE",
        device_id="DEV-1",
        external_reference=f"REF-{punch_id}",
        notes=None,
    )


def test_present_full_day_without_late():
    result = calculate_daily_attendance(
        employee=_employee(),
        day=date(2026, 8, 17),
        punches=[_punch(7, 55, "IN", 1), _punch(17, 0, "OUT", 2)],
        leaves=[],
    )

    assert result["status"] == "present"
    assert result["has_late"] is False
    assert result["worked_minutes"] == 545


def test_late_after_configured_tolerance():
    result = calculate_daily_attendance(
        employee=_employee(),
        day=date(2026, 8, 17),
        punches=[_punch(8, 30, "IN", 1), _punch(17, 0, "OUT", 2)],
        leaves=[],
    )

    assert result["status"] == "present"
    assert result["has_late"] is True
    assert result["late_minutes"] == 15


def test_worked_time_uses_in_out_pairs_not_first_last_delta():
    result = calculate_daily_attendance(
        employee=_employee(),
        day=date(2026, 8, 17),
        punches=[_punch(7, 55, "IN", 1), _punch(12, 0, "OUT", 2), _punch(13, 0, "IN", 3), _punch(17, 0, "OUT", 4)],
        leaves=[],
    )

    assert result["status"] == "present"
    assert result["worked_minutes"] == 485
    assert result["pause_minutes"] == 60


def test_missing_checkout_is_anomaly():
    result = calculate_daily_attendance(
        employee=_employee(),
        day=date(2026, 8, 17),
        punches=[_punch(7, 55, "IN", 1)],
        leaves=[],
    )

    assert result["has_anomaly"] is True
    assert "Sortie de fin de journée manquante" in result["anomalies"]


def test_no_punch_on_working_day_is_absent():
    result = calculate_daily_attendance(employee=_employee(), day=date(2026, 8, 17), punches=[], leaves=[])

    assert result["status"] == "absent"
    assert result["has_anomaly"] is True


def test_approved_leave_without_punch_is_leave_not_absent():
    leave = HRLeave(
        id=10,
        tenant_id=1,
        employee_id=1,
        type_absence="conge_annuel",
        date_debut=date(2026, 8, 17),
        date_fin=date(2026, 8, 17),
        nombre_jours=1,
        statut="approuvé",
    )
    result = calculate_daily_attendance(employee=_employee(), day=date(2026, 8, 17), punches=[], leaves=[leave])

    assert result["status"] == "conge"
    assert "Aucun pointage un jour ouvrable" not in result["anomalies"]


def test_no_punch_on_sunday_is_not_absent():
    result = calculate_daily_attendance(employee=_employee(), day=date(2026, 8, 16), punches=[], leaves=[])

    assert result["status"] == "non_ouvrable"
    assert result["has_anomaly"] is False


@pytest.mark.asyncio
async def test_external_reference_device_deduplicates_punches(db_session):
    from app.models.organisation import Organisation
    from app.models.hr import HREmployee

    org = Organisation(nom="Tenant RH Punch", slug="tenant-rh-punch", is_active=True)
    db_session.add(org)
    await db_session.flush()
    employee = HREmployee(tenant_id=org.id, matricule="EMP-DEDUP", nom="KIDIKALA", prenom="Christian", statut="actif")
    db_session.add(employee)
    await db_session.flush()

    first = HRAttendancePunch(
        tenant_id=org.id,
        employee_id=employee.id,
        punched_at=datetime(2026, 8, 17, 7, 55, tzinfo=timezone.utc),
        event_type="IN",
        source="DEVICE",
        device_id="CLOCK-1",
        external_reference="EVT-1",
    )
    duplicate = HRAttendancePunch(
        tenant_id=org.id,
        employee_id=employee.id,
        punched_at=datetime(2026, 8, 17, 7, 55, tzinfo=timezone.utc),
        event_type="IN",
        source="DEVICE",
        device_id="CLOCK-1",
        external_reference="EVT-1",
    )
    db_session.add(first)
    await db_session.flush()
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        await db_session.flush()
