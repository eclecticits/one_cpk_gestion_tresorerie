from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from app.models.hr import HRAttendance, HRAttendancePunch, HRLeave


@dataclass(frozen=True)
class AttendanceRules:
    work_start: time = time(8, 0)
    work_end: time = time(17, 0)
    late_tolerance_minutes: int = 15
    standard_day_minutes: int = 8 * 60
    full_day_min_minutes: int = 7 * 60
    half_day_min_minutes: int = 4 * 60
    weekend_weekdays: frozenset[int] = frozenset({5, 6})


def default_attendance_rules() -> AttendanceRules:
    # Central fallback until a dedicated HR schedule/settings screen is added.
    return AttendanceRules()


def _minutes_between(start: datetime, end: datetime) -> int:
    return max(0, int((end - start).total_seconds() // 60))


def _format_hhmm(total_minutes: int | None) -> str | None:
    if total_minutes is None:
        return None
    sign = "-" if total_minutes < 0 else ""
    value = abs(total_minutes)
    return f"{sign}{value // 60:02d}h{value % 60:02d}"


def _punch_time(value: datetime | None) -> str | None:
    return value.strftime("%H:%M") if value else None


def _leave_for_day(leaves: list[HRLeave], day: date) -> HRLeave | None:
    approved = {"approuvé", "approuve", "approuvée", "approuvee", "validé", "valide", "validée", "validee", "approved"}
    for leave in leaves:
        if (leave.statut or "").lower() in approved and leave.date_debut <= day <= leave.date_fin:
            return leave
    return None


def _manual_status(manual: HRAttendance | None) -> str | None:
    if not manual:
        return None
    return (manual.statut_presence or "").lower()


def calculate_daily_attendance(
    *,
    employee: Any,
    day: date,
    punches: list[HRAttendancePunch],
    leaves: list[HRLeave],
    manual_attendance: HRAttendance | None = None,
    rules: AttendanceRules | None = None,
) -> dict[str, Any]:
    rules = rules or default_attendance_rules()
    ordered = sorted(punches, key=lambda p: p.punched_at)
    leave = _leave_for_day(leaves, day)
    is_working_day = day.weekday() not in rules.weekend_weekdays

    anomalies: list[str] = []
    pairs: list[tuple[datetime, datetime]] = []
    open_in: HRAttendancePunch | None = None
    previous_type: str | None = None

    for punch in ordered:
        event_type = (punch.event_type or "").upper()
        if event_type not in {"IN", "OUT"}:
            anomalies.append(f"Type de pointage inconnu : {punch.event_type}")
            continue
        if previous_type == event_type:
            anomalies.append("Deux entrées successives" if event_type == "IN" else "Deux sorties successives")
        previous_type = event_type
        if event_type == "IN":
            if open_in is not None:
                anomalies.append("Entrée sans sortie précédente")
            open_in = punch
        elif open_in is None:
            anomalies.append("Sortie sans entrée")
        else:
            if punch.punched_at <= open_in.punched_at:
                anomalies.append("Sortie antérieure ou égale à l'entrée")
            else:
                pairs.append((open_in.punched_at, punch.punched_at))
            open_in = None

    if open_in is not None:
        anomalies.append("Sortie de fin de journée manquante")
    if leave and ordered:
        anomalies.append("Pointage enregistré pendant un congé")

    worked_minutes = sum(_minutes_between(start, end) for start, end in pairs)
    pause_minutes = 0
    for index in range(1, len(pairs)):
        pause_minutes += _minutes_between(pairs[index - 1][1], pairs[index][0])

    first_in = next((p.punched_at for p in ordered if (p.event_type or "").upper() == "IN"), None)
    last_out = next((p.punched_at for p in reversed(ordered) if (p.event_type or "").upper() == "OUT"), None)

    expected_start = datetime.combine(day, rules.work_start, tzinfo=first_in.tzinfo if first_in else None)
    late_minutes = 0
    if first_in and first_in > expected_start + timedelta(minutes=rules.late_tolerance_minutes):
        late_minutes = _minutes_between(expected_start + timedelta(minutes=rules.late_tolerance_minutes), first_in)

    overtime_minutes = max(0, worked_minutes - rules.standard_day_minutes)
    manual_status = _manual_status(manual_attendance)

    if leave:
        status_code = "conge"
    elif manual_status in {"teletravail", "remote_work"}:
        status_code = "teletravail"
    elif manual_status in {"conge", "leave"}:
        status_code = "conge"
    elif manual_status in {"present", "absent", "demi_journee"} and not ordered:
        status_code = manual_status
    elif worked_minutes >= rules.full_day_min_minutes:
        status_code = "present"
    elif worked_minutes >= rules.half_day_min_minutes:
        status_code = "demi_journee"
    elif ordered:
        status_code = "demi_journee"
    elif is_working_day:
        status_code = "absent"
    else:
        status_code = "non_ouvrable"

    if status_code == "absent" and is_working_day:
        anomalies.append("Aucun pointage un jour ouvrable")

    return {
        "employee_id": employee.id,
        "employee_matricule": getattr(employee, "matricule", None),
        "employee_name": " ".join(filter(None, [getattr(employee, "nom", None), getattr(employee, "post_nom", None), getattr(employee, "prenom", None)])),
        "service_id": getattr(employee, "service_id", None),
        "service_name": getattr(getattr(employee, "service", None), "libelle", None),
        "date": day,
        "is_working_day": is_working_day,
        "status": status_code,
        "has_late": late_minutes > 0,
        "has_anomaly": bool(anomalies),
        "first_in": first_in,
        "last_out": last_out,
        "first_in_time": _punch_time(first_in),
        "last_out_time": _punch_time(last_out),
        "worked_minutes": worked_minutes,
        "worked_duration": _format_hhmm(worked_minutes),
        "pause_minutes": pause_minutes,
        "pause_duration": _format_hhmm(pause_minutes),
        "late_minutes": late_minutes,
        "late_duration": _format_hhmm(late_minutes),
        "overtime_minutes": overtime_minutes,
        "overtime_duration": _format_hhmm(overtime_minutes),
        "anomalies": list(dict.fromkeys(anomalies)),
        "punches": [
            {
                "id": p.id,
                "punched_at": p.punched_at,
                "time": p.punched_at.strftime("%H:%M"),
                "event_type": (p.event_type or "").upper(),
                "source": p.source,
                "device_id": p.device_id,
                "external_reference": p.external_reference,
                "notes": p.notes,
            }
            for p in ordered
        ],
        "manual_attendance_id": manual_attendance.id if manual_attendance else None,
        "leave_id": leave.id if leave else None,
    }


def summarize_month(days: list[dict[str, Any]]) -> dict[str, Any]:
    workdays = [d for d in days if d["is_working_day"]]
    return {
        "working_days": len({d["date"] for d in workdays}),
        "present_days": sum(1 for d in days if d["status"] == "present"),
        "absent_days": sum(1 for d in days if d["status"] == "absent"),
        "half_days": sum(1 for d in days if d["status"] == "demi_journee"),
        "leave_days": sum(1 for d in days if d["status"] == "conge"),
        "remote_days": sum(1 for d in days if d["status"] == "teletravail"),
        "late_count": sum(1 for d in days if d["has_late"]),
        "anomaly_count": sum(1 for d in days if d["has_anomaly"]),
        "worked_minutes": sum(d["worked_minutes"] for d in days),
        "overtime_minutes": sum(d["overtime_minutes"] for d in days),
    }
