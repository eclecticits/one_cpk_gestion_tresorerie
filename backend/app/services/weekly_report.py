from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.encaissement import Encaissement
from app.models.sortie_fonds import SortieFonds
from app.models.system_settings import SystemSettings
from app.models.organisation import Organisation
from app.core.tenant_context import set_current_tenant_id
from app.services.mailer import send_in_thread, send_weekly_report_email
from app.services.system_settings_service import get_system_settings

logger = logging.getLogger("onec_cpk_api.weekly_report")
WEEKLY_REPORT_LOCK_KEY = 2026030501


async def _get_system_settings(db: AsyncSession, tenant_id: int) -> SystemSettings | None:
    return await get_system_settings(db, tenant_id)


def _to_float(value: Decimal | int | float | None) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _resolve_timezone() -> ZoneInfo:
    tz_name = (settings.weekly_report_timezone or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(tz_name)
    except Exception:
        logger.warning("Invalid WEEKLY_REPORT_TIMEZONE=%s; fallback to UTC", tz_name)
        return ZoneInfo("UTC")


def _period_last_week(now: datetime) -> tuple[datetime, datetime]:
    # Define last week as Monday 00:00 -> current Monday 00:00 in the selected timezone.
    this_monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    last_monday = this_monday - timedelta(days=7)
    return last_monday, this_monday


async def _fetch_weekly_stats(db: AsyncSession, start: datetime, end: datetime) -> dict:
    caisse_row = (await db.execute(select(CaisseCentrale).limit(1))).scalar_one_or_none()
    caisse_usd = _to_float(getattr(caisse_row, "solde_usd", 0))
    caisse_cdf = _to_float(getattr(caisse_row, "solde_cdf", 0))

    banque_rows = await db.execute(
        select(CompteBancaire.devise, func.coalesce(func.sum(CompteBancaire.solde_actuel), 0))
        .where(CompteBancaire.is_active.is_(True))
        .group_by(CompteBancaire.devise)
    )
    banque_totals = {row[0]: _to_float(row[1]) for row in banque_rows.all()}

    enc_rows = await db.execute(
        select(Encaissement.devise_perception, func.coalesce(func.sum(Encaissement.montant_paye), 0))
        .where(
            Encaissement.is_deleted.is_(False),
            Encaissement.est_proforma.is_(False),
            ((Encaissement.statut_operation.is_(None)) | (Encaissement.statut_operation == "ACTIVE")),
            Encaissement.date_encaissement >= start,
            Encaissement.date_encaissement < end,
        )
        .group_by(Encaissement.devise_perception)
    )
    encaissements = {row[0]: _to_float(row[1]) for row in enc_rows.all()}

    sort_rows = await db.execute(
        select(SortieFonds.devise, func.coalesce(func.sum(SortieFonds.montant_paye), 0))
        .where(
            SortieFonds.statut == "VALIDE",
            SortieFonds.date_paiement.is_not(None),
            SortieFonds.date_paiement >= start,
            SortieFonds.date_paiement < end,
        )
        .group_by(SortieFonds.devise)
    )
    sorties = {row[0]: _to_float(row[1]) for row in sort_rows.all()}

    return {
        "period_start": start,
        "period_end": end,
        "caisse_usd": caisse_usd,
        "caisse_cdf": caisse_cdf,
        "banques_usd": banque_totals.get("USD", 0.0),
        "banques_cdf": banque_totals.get("CDF", 0.0),
        "entrees_usd": encaissements.get("USD", 0.0),
        "entrees_cdf": encaissements.get("CDF", 0.0),
        "sorties_usd": sorties.get("USD", 0.0),
        "sorties_cdf": sorties.get("CDF", 0.0),
    }


def _build_weekly_html(stats: dict, generated_at: datetime, tenant_name: str) -> str:
    period_start = stats["period_start"].strftime("%d/%m/%Y")
    period_end = (stats["period_end"] - timedelta(seconds=1)).strftime("%d/%m/%Y")
    date_str = generated_at.strftime("%d/%m/%Y")
    return f"""
    <html>
      <body style="font-family: 'Segoe UI', Arial, sans-serif; background: #f5f7fa; color: #1f2937; padding: 24px;">
        <div style="max-width: 680px; margin: 0 auto; background: #ffffff; border-radius: 12px; overflow: hidden; border: 1px solid #e5e7eb;">
          <div style="background: #0b5d43; color: #fff; padding: 20px 24px;">
            <h2 style="margin: 0; font-size: 18px;">{tenant_name} - Rapport Hebdomadaire</h2>
            <p style="margin: 4px 0 0; opacity: 0.85; font-size: 12px;">Généré le {date_str}</p>
          </div>
          <div style="padding: 20px 24px;">
            <p style="margin-top: 0;">Bonjour Monsieur le Secrétaire Exécutif,</p>
            <p style="margin-bottom: 16px;">Voici l'état de la trésorerie pour la période du <strong>{period_start}</strong> au <strong>{period_end}</strong> :</p>

            <table style="width: 100%; border-collapse: collapse; margin-bottom: 16px;">
              <tr style="background: #f8fafc;">
                <td style="padding: 10px; border: 1px solid #e5e7eb;"><strong>Caisse USD</strong></td>
                <td style="padding: 10px; border: 1px solid #e5e7eb; text-align: right;">{stats["caisse_usd"]:,.2f} $</td>
              </tr>
              <tr>
                <td style="padding: 10px; border: 1px solid #e5e7eb;"><strong>Caisse CDF</strong></td>
                <td style="padding: 10px; border: 1px solid #e5e7eb; text-align: right;">{stats["caisse_cdf"]:,.2f} FC</td>
              </tr>
              <tr style="background: #f8fafc;">
                <td style="padding: 10px; border: 1px solid #e5e7eb;"><strong>Total Banques USD</strong></td>
                <td style="padding: 10px; border: 1px solid #e5e7eb; text-align: right;">{stats["banques_usd"]:,.2f} $</td>
              </tr>
              <tr>
                <td style="padding: 10px; border: 1px solid #e5e7eb;"><strong>Total Banques CDF</strong></td>
                <td style="padding: 10px; border: 1px solid #e5e7eb; text-align: right;">{stats["banques_cdf"]:,.2f} FC</td>
              </tr>
            </table>

            <div style="display: grid; gap: 8px;">
              <div style="background: #f0fdf4; padding: 12px; border-radius: 8px; border: 1px solid #bbf7d0;">
                <strong>Entrées semaine USD :</strong> {stats["entrees_usd"]:,.2f} $<br/>
                <strong>Entrées semaine CDF :</strong> {stats["entrees_cdf"]:,.2f} FC
              </div>
              <div style="background: #fff7ed; padding: 12px; border-radius: 8px; border: 1px solid #fed7aa;">
                <strong>Sorties semaine USD :</strong> {stats["sorties_usd"]:,.2f} $<br/>
                <strong>Sorties semaine CDF :</strong> {stats["sorties_cdf"]:,.2f} FC
              </div>
            </div>

            <p style="margin-top: 16px; font-size: 12px; color: #6b7280;">
              Le détail complet (Journal, PV de clôture et synthèses) est disponible sur votre portail de gestion.
            </p>
          </div>
          <div style="font-size: 10px; color: #9ca3af; text-align: center; padding: 12px; border-top: 1px solid #e5e7eb;">
            Envoi automatique - Système de Gestion {tenant_name}
          </div>
        </div>
      </body>
    </html>
    """.strip()


def _build_weekly_text(stats: dict, generated_at: datetime, tenant_name: str) -> str:
    period_start = stats["period_start"].strftime("%d/%m/%Y")
    period_end = (stats["period_end"] - timedelta(seconds=1)).strftime("%d/%m/%Y")
    date_str = generated_at.strftime("%d/%m/%Y")
    return (
        f"{tenant_name} - Rapport Hebdomadaire\n"
        f"Généré le {date_str}\n\n"
        f"Période : {period_start} au {period_end}\n"
        f"Caisse USD : {stats['caisse_usd']:,.2f} $\n"
        f"Caisse CDF : {stats['caisse_cdf']:,.2f} FC\n"
        f"Total Banques USD : {stats['banques_usd']:,.2f} $\n"
        f"Total Banques CDF : {stats['banques_cdf']:,.2f} FC\n\n"
        f"Entrées semaine USD : {stats['entrees_usd']:,.2f} $\n"
        f"Entrées semaine CDF : {stats['entrees_cdf']:,.2f} FC\n"
        f"Sorties semaine USD : {stats['sorties_usd']:,.2f} $\n"
        f"Sorties semaine CDF : {stats['sorties_cdf']:,.2f} FC\n"
    )


async def send_weekly_report(db: AsyncSession, *, tenant_id: int) -> None:
    tz = _resolve_timezone()
    now = datetime.now(tz)
    start, end = _period_last_week(now)
    stats = await _fetch_weekly_stats(db, start, end)
    org = await db.get(Organisation, tenant_id)
    tenant_name = (getattr(org, "nom", None) or "ONEC").strip() or "ONEC"

    ns = await _get_system_settings(db, tenant_id)

    smtp_host = (settings.smtp_host or (ns.smtp_host if ns else None) or "smtp.gmail.com").strip()
    smtp_port = int(settings.smtp_port or (ns.smtp_port if ns else None) or 465)
    smtp_user = (settings.smtp_user or (ns.email_expediteur if ns else "") or "").strip()
    smtp_password = (settings.smtp_password or (ns.smtp_password if ns else "") or "").strip()

    recipient = (settings.weekly_report_to or (ns.email_president if ns else "") or (ns.email_tresorier if ns else "")).strip()
    cc_emails = (settings.weekly_report_cc or (ns.emails_bureau_cc if ns else "") or "").strip()

    if not recipient:
        logger.warning("Weekly report skipped: no recipient configured (WEEKLY_REPORT_TO).")
        return
    if not smtp_user or not smtp_password:
        logger.warning("Weekly report skipped: SMTP credentials missing.")
        return

    subject = f"Rapport hebdomadaire trésorerie - {now.strftime('%d/%m/%Y')}"
    html_body = _build_weekly_html(stats, now, tenant_name)
    text_body = _build_weekly_text(stats, now, tenant_name)

    success = await send_in_thread(
        send_weekly_report_email,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_user=smtp_user,
        smtp_password=smtp_password,
        sender=smtp_user,
        recipient=recipient,
        cc_emails=cc_emails or None,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
    )
    if ns is None:
        ns = SystemSettings(organisation_id=tenant_id, updated_at=now)
        db.add(ns)
    ns.last_weekly_report_sent_at = now
    ns.last_weekly_report_status = "success" if success else "failed"
    ns.last_weekly_report_error = "" if success else "Erreur SMTP. Vérifier les logs."
    if success:
        ns.last_weekly_report_success_at = now
    else:
        ns.last_weekly_report_failure_at = now
    ns.updated_at = now
    await db.commit()


async def run_weekly_report() -> None:
    async with SessionLocal() as db:
        locked = await db.scalar(text("SELECT pg_try_advisory_lock(:lock_key)"), {"lock_key": WEEKLY_REPORT_LOCK_KEY})
        if not locked:
            logger.info("Weekly report skipped: another worker owns the scheduler lock.")
            return
        try:
            org_res = await db.execute(select(Organisation.id).order_by(Organisation.id))
            org_ids = [row[0] for row in org_res.all()]
            for org_id in org_ids:
                try:
                    set_current_tenant_id(org_id)
                    await send_weekly_report(db, tenant_id=org_id)
                except Exception:
                    logger.exception("Weekly report failed for organisation_id=%s", org_id)
                finally:
                    set_current_tenant_id(None)
        finally:
            await db.execute(text("SELECT pg_advisory_unlock(:lock_key)"), {"lock_key": WEEKLY_REPORT_LOCK_KEY})
            await db.commit()
