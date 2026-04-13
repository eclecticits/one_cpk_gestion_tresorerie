from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta
from calendar import monthrange
from zoneinfo import ZoneInfo

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.piecharts import Pie
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.mailer import send_monthly_report_email

logger = logging.getLogger("onec_cpk_api.monthly_report")


def _month_bounds(month: int, year: int) -> tuple[datetime, datetime]:
    month = max(1, min(int(month), 12))
    year = int(year)
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end_day = monthrange(year, month)[1]
    end = datetime(year, month, end_day, 23, 59, 59, tzinfo=timezone.utc)
    return start, end


def _resolve_timezone() -> ZoneInfo:
    tz_name = (settings.monthly_report_timezone or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(tz_name)
    except Exception:
        logger.warning("Invalid MONTHLY_REPORT_TIMEZONE=%s; fallback to UTC", tz_name)
        return ZoneInfo("UTC")


def _ensure_exports_dir() -> str:
    base = settings.upload_dir or os.path.join(os.path.dirname(__file__), "..", "uploads")
    base = os.path.abspath(base)
    export_dir = os.path.join(base, "exports")
    os.makedirs(export_dir, exist_ok=True)
    return export_dir


async def generate_national_report(db: AsyncSession, *, month: int, year: int) -> str:
    start, end = _month_bounds(month, year)
    res = await db.execute(
        text(
            """
            SELECT o.id AS org_id,
                   o.nom AS org_nom,
                   o.slug AS slug,
                   o.status_abonnement AS status_abonnement,
                   (SELECT COUNT(*) FROM users u WHERE u.organisation_id = o.id) AS total_users,
                   COALESCE(SUM(e.montant_paye) FILTER (WHERE e.created_at BETWEEN :start AND :end), 0) AS volume_encaisse,
                   MAX(e.created_at) AS derniere_activite
            FROM organisations o
            LEFT JOIN encaissements e ON e.organisation_id = o.id AND e.est_proforma IS FALSE
            GROUP BY o.id
            ORDER BY volume_encaisse DESC NULLS LAST
            """
        ),
        {"start": start, "end": end},
    )
    rows = res.mappings().all()

    export_dir = _ensure_exports_dir()
    filename = f"Rapport_National_{year}_{month:02d}.pdf"
    out_path = os.path.join(export_dir, filename)

    c = canvas.Canvas(out_path, pagesize=A4)
    width, height = A4

    c.setFont("Helvetica-Bold", 14)
    c.drawString(2 * cm, height - 2.2 * cm, "ONEC-MIND : RAPPORT MENSUEL CONSOLIDÉ")
    c.setFont("Helvetica", 10)
    c.drawString(2 * cm, height - 2.8 * cm, f"Période : {month:02d}/{year} · Généré le {datetime.now().strftime('%d/%m/%Y')}")

    y = height - 3.6 * cm
    c.setStrokeColor(colors.grey)
    c.line(2 * cm, y, width - 2 * cm, y)
    y -= 0.6 * cm

    c.setFont("Helvetica-Bold", 9)
    c.drawString(2 * cm, y, "PROVINCE / ENTITÉ")
    c.drawString(8 * cm, y, "VOL. ENCAISSÉ (USD)")
    c.drawString(13 * cm, y, "NB USERS")
    c.drawString(16 * cm, y, "STATUT")
    y -= 0.4 * cm

    c.setFont("Helvetica", 9)
    for row in rows:
        if y < 3 * cm:
            c.showPage()
            y = height - 2.5 * cm
        c.drawString(2 * cm, y, str(row["org_nom"]))
        c.drawRightString(12.5 * cm, y, f"{float(row['volume_encaisse'] or 0):,.2f} $")
        c.drawRightString(15.3 * cm, y, str(row["total_users"]))
        c.drawString(16 * cm, y, str(row["status_abonnement"]))
        y -= 0.35 * cm

    # Pie chart summary
    if rows:
        chart = Pie()
        chart.x = 0
        chart.y = 0
        chart.width = 260
        chart.height = 260
        chart.data = [float(r["volume_encaisse"] or 0) for r in rows[:8]]
        chart.labels = [str(r["org_nom"])[:18] for r in rows[:8]]
        chart.slices.strokeWidth = 0.5
        chart.slices.strokeColor = colors.white
        drawing = Drawing(260, 260)
        drawing.add(chart)

        c.showPage()
        c.setFont("Helvetica-Bold", 12)
        c.drawString(2 * cm, height - 2.5 * cm, "Répartition des recettes (Top 8)")
        render_x = 2 * cm
        render_y = height - 8 * cm
        drawing.drawOn(c, render_x, render_y)

    c.save()
    return out_path


async def send_monthly_report(db: AsyncSession, *, month: int, year: int) -> str | None:
    recipient = (settings.monthly_report_to or "").strip()
    cc_emails = (settings.monthly_report_cc or "").strip() or None
    if not recipient:
        logger.warning("Monthly report skipped: MONTHLY_REPORT_TO not set")
        return None

    path = await generate_national_report(db, month=month, year=year)
    subject = f"Rapport mensuel consolidé - {month:02d}/{year}"
    lines = [
        "Veuillez trouver ci-joint le rapport mensuel consolidé des entités.",
        f"Période : {month:02d}/{year}",
    ]

    send_monthly_report_email(
        smtp_host=settings.smtp_host or "smtp.gmail.com",
        smtp_port=int(settings.smtp_port or 465),
        smtp_user=settings.smtp_user or "",
        smtp_password=settings.smtp_password or "",
        sender=settings.smtp_user or "",
        recipient=recipient,
        cc_emails=cc_emails,
        subject=subject,
        body_lines=lines,
        attachment_path=path,
    )

    return path


async def run_monthly_report() -> None:
    tz = _resolve_timezone()
    now = datetime.now(tz)
    prev = (now.replace(day=1) - timedelta(days=1))
    async with SessionLocal() as db:
        await send_monthly_report(db, month=prev.month, year=prev.year)
