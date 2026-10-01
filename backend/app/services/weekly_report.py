from __future__ import annotations

import html
import logging
import smtplib
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import NoReturn
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
from app.services.mailer import (
    AUTOMATIC_MESSAGE_NOTICE,
    _tenant_portal_url,
    send_in_thread,
    send_weekly_report_email,
)
from app.services.email_config import normalize_smtp_password
from app.services.system_settings_service import get_system_settings

logger = logging.getLogger("onec_cpk_api.weekly_report")
WEEKLY_REPORT_LOCK_KEY = 2026030501
MONTHLY_TREASURY_REPORT_LOCK_KEY = 2026100101


@dataclass(frozen=True)
class ReportKind:
    """Ce qui distingue le rapport hebdomadaire du mensuel ; le reste est commun."""

    key: str  # préfixe des colonnes de statut : last_<key>_report_*
    title: str
    period_word: str
    subject: str
    lock_key: int


WEEKLY = ReportKind("weekly", "Rapport Hebdomadaire", "semaine", "Rapport hebdomadaire trésorerie", WEEKLY_REPORT_LOCK_KEY)
MONTHLY = ReportKind("monthly", "Rapport Mensuel", "du mois", "Rapport mensuel trésorerie", MONTHLY_TREASURY_REPORT_LOCK_KEY)


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


def _period_last_month(now: datetime) -> tuple[datetime, datetime]:
    # Le mois écoulé : du 1er du mois précédent 00:00 au 1er du mois courant 00:00.
    this_first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_first = (this_first - timedelta(days=1)).replace(day=1)
    return last_first, this_first


def _period(kind: ReportKind, now: datetime) -> tuple[datetime, datetime]:
    return _period_last_month(now) if kind is MONTHLY else _period_last_week(now)


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


def _build_weekly_html(
    stats: dict,
    generated_at: datetime,
    tenant_name: str,
    tenant_url: str | None = None,
    kind: ReportKind = WEEKLY,
) -> str:
    period_start = stats["period_start"].strftime("%d/%m/%Y")
    period_end = (stats["period_end"] - timedelta(seconds=1)).strftime("%d/%m/%Y")
    date_str = generated_at.strftime("%d/%m/%Y")
    # Lien vers l'espace du tenant, pour vérifier les chiffres sur place. Absent
    # si TENANT_BASE_DOMAIN n'est pas réglé : mieux vaut pas de lien qu'un faux.
    tenant_link_block = (
        f"""
            <div style="margin-top: 16px; padding: 14px 16px; border: 1px solid #d9eee7; border-radius: 10px; background: #f2fbf8;">
              <div style="font-size: 13px; color: #58736c; font-weight: 700; margin-bottom: 8px;">Pour toute vérification</div>
              <a href="{html.escape(tenant_url)}" style="display: inline-block; padding: 10px 16px; border-radius: 8px; background: #0b5d43; color: #ffffff; text-decoration: none; font-weight: 700;">
                Accéder à l'espace {html.escape(tenant_name)}
              </a>
              <div style="margin-top: 8px; font-size: 12px; color: #6b7f79;">{html.escape(tenant_url)}</div>
            </div>"""
        if tenant_url
        else ""
    )
    return f"""
    <html>
      <body style="font-family: 'Segoe UI', Arial, sans-serif; background: #f5f7fa; color: #1f2937; padding: 24px;">
        <div style="max-width: 680px; margin: 0 auto; background: #ffffff; border-radius: 12px; overflow: hidden; border: 1px solid #e5e7eb;">
          <div style="background: #0b5d43; color: #fff; padding: 20px 24px;">
            <h2 style="margin: 0; font-size: 18px;">{tenant_name} - {kind.title}</h2>
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
                <strong>Entrées {kind.period_word} USD :</strong> {stats["entrees_usd"]:,.2f} $<br/>
                <strong>Entrées {kind.period_word} CDF :</strong> {stats["entrees_cdf"]:,.2f} FC
              </div>
              <div style="background: #fff7ed; padding: 12px; border-radius: 8px; border: 1px solid #fed7aa;">
                <strong>Sorties {kind.period_word} USD :</strong> {stats["sorties_usd"]:,.2f} $<br/>
                <strong>Sorties {kind.period_word} CDF :</strong> {stats["sorties_cdf"]:,.2f} FC
              </div>
            </div>

            <p style="margin-top: 16px; font-size: 12px; color: #6b7280;">
              Le détail complet (Journal, PV de clôture et synthèses) est disponible sur votre portail de gestion.
            </p>
{tenant_link_block}
          </div>
          <div style="font-size: 10px; color: #9ca3af; text-align: center; padding: 12px; border-top: 1px solid #e5e7eb;">
            {tenant_name} · ONEC Smart<br/>
            {AUTOMATIC_MESSAGE_NOTICE}
          </div>
        </div>
      </body>
    </html>
    """.strip()


def _build_weekly_text(
    stats: dict,
    generated_at: datetime,
    tenant_name: str,
    tenant_url: str | None = None,
    kind: ReportKind = WEEKLY,
) -> str:
    period_start = stats["period_start"].strftime("%d/%m/%Y")
    period_end = (stats["period_end"] - timedelta(seconds=1)).strftime("%d/%m/%Y")
    date_str = generated_at.strftime("%d/%m/%Y")
    body = (
        f"{tenant_name} - {kind.title}\n"
        f"Généré le {date_str}\n\n"
        f"Période : {period_start} au {period_end}\n"
        f"Caisse USD : {stats['caisse_usd']:,.2f} $\n"
        f"Caisse CDF : {stats['caisse_cdf']:,.2f} FC\n"
        f"Total Banques USD : {stats['banques_usd']:,.2f} $\n"
        f"Total Banques CDF : {stats['banques_cdf']:,.2f} FC\n\n"
        f"Entrées {kind.period_word} USD : {stats['entrees_usd']:,.2f} $\n"
        f"Entrées {kind.period_word} CDF : {stats['entrees_cdf']:,.2f} FC\n"
        f"Sorties {kind.period_word} USD : {stats['sorties_usd']:,.2f} $\n"
        f"Sorties {kind.period_word} CDF : {stats['sorties_cdf']:,.2f} FC\n"
    )
    if tenant_url:
        body += f"\nPour toute vérification : {tenant_url}\n"
    return body


async def send_weekly_report(db: AsyncSession, *, tenant_id: int) -> None:
    await send_treasury_report(db, tenant_id=tenant_id, kind=WEEKLY)


async def send_monthly_treasury_report(db: AsyncSession, *, tenant_id: int) -> None:
    await send_treasury_report(db, tenant_id=tenant_id, kind=MONTHLY)


async def send_treasury_report(db: AsyncSession, *, tenant_id: int, kind: ReportKind) -> None:
    tz = _resolve_timezone()
    now = datetime.now(tz)
    start, end = _period(kind, now)
    stats = await _fetch_weekly_stats(db, start, end)
    org = await db.get(Organisation, tenant_id)
    tenant_name = (getattr(org, "nom", None) or "ONEC").strip() or "ONEC"
    tenant_url = _tenant_portal_url(getattr(org, "slug", None))

    ns = await _get_system_settings(db, tenant_id)

    smtp_host = (settings.smtp_host or (ns.smtp_host if ns else None) or "smtp.gmail.com").strip()
    smtp_port = int(settings.smtp_port or (ns.smtp_port if ns else None) or 465)
    smtp_user = (settings.smtp_user or (ns.email_expediteur if ns else "") or "").strip()
    smtp_password = normalize_smtp_password(
        settings.smtp_password or (ns.smtp_password if ns else ""),
        host=smtp_host,
    )

    recipient = (settings.weekly_report_to or (ns.email_president if ns else "") or (ns.email_tresorier if ns else "")).strip()
    cc_emails = (settings.weekly_report_cc or (ns.emails_bureau_cc if ns else "") or "").strip()

    if not recipient:
        logger.warning("%s report skipped: no recipient configured (WEEKLY_REPORT_TO).", kind.key)
        await _fail(
            db, ns, tenant_id, now, kind,
            "Aucun destinataire : renseignez l'e-mail du président ou du trésorier "
            "(ou WEEKLY_REPORT_TO).",
        )
    if not smtp_user or not smtp_password:
        logger.warning("%s report skipped: SMTP credentials missing.", kind.key)
        await _fail(
            db, ns, tenant_id, now, kind,
            "Identifiants SMTP manquants : renseignez l'e-mail expéditeur et le mot de passe SMTP.",
        )

    subject = f"{kind.subject} - {now.strftime('%d/%m/%Y')}"
    html_body = _build_weekly_html(stats, now, tenant_name, tenant_url, kind)
    text_body = _build_weekly_text(stats, now, tenant_name, tenant_url, kind)

    try:
        await send_in_thread(
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
    except Exception as exc:
        await _fail(db, ns, tenant_id, now, kind, f"Erreur SMTP : {_describe_smtp_error(exc)}")
    await _record_outcome(db, ns, tenant_id, now, kind, error=None)


class TreasuryReportNotSent(RuntimeError):
    """Le rapport n'est pas parti ; le message dit pourquoi, en clair."""


def _describe_smtp_error(exc: Exception) -> str:
    # `str()` d'une SMTPResponseException rend un tuple avec des octets
    # (« (535, b'5.7.8 Username...') ») : on en tire le code et le texte.
    if isinstance(exc, smtplib.SMTPResponseException):
        detail = exc.smtp_error
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", errors="replace")
        return f"{exc.smtp_code} {detail}".strip()
    return str(exc) or exc.__class__.__name__


async def _record_outcome(
    db: AsyncSession,
    ns: SystemSettings | None,
    tenant_id: int,
    now: datetime,
    kind: ReportKind,
    *,
    error: str | None,
) -> None:
    """Inscrit l'issue de la tentative dans les paramètres de l'organisation."""
    if ns is None:
        ns = SystemSettings(organisation_id=tenant_id, updated_at=now)
        db.add(ns)
    prefix = f"last_{kind.key}_report"
    setattr(ns, f"{prefix}_sent_at", now)
    setattr(ns, f"{prefix}_status", "failed" if error else "success")
    setattr(ns, f"{prefix}_error", error or "")
    setattr(ns, f"{prefix}_failure_at" if error else f"{prefix}_success_at", now)
    ns.updated_at = now
    await db.commit()


async def _fail(
    db: AsyncSession,
    ns: SystemSettings | None,
    tenant_id: int,
    now: datetime,
    kind: ReportKind,
    error: str,
) -> NoReturn:
    """Inscrit l'échec puis lève `TreasuryReportNotSent`.

    Un abandon (destinataire ou identifiants absents) compte comme un échec :
    sans cela, il ne laissait de trace que dans le journal du serveur, l'écran
    gardait le statut de l'envoi précédent et « Envoyer maintenant » annonçait
    un rapport envoyé.
    """
    await _record_outcome(db, ns, tenant_id, now, kind, error=error)
    raise TreasuryReportNotSent(error)


async def _already_sent_for_period(db: AsyncSession, tenant_id: int, kind: ReportKind) -> bool:
    """Vrai si la période en cours a déjà reçu son rapport.

    Le verrou consultatif écarte les déclenchements simultanés, pas un
    déclenchement tardif : un worker dont la boucle était occupée peut tenter sa
    chance après que le premier a rendu le verrou, et renvoyer le même rapport.
    """
    ns = await _get_system_settings(db, tenant_id)
    success_at = getattr(ns, f"last_{kind.key}_report_success_at", None) if ns else None
    if success_at is None:
        return False
    _, current_period_start = _period(kind, datetime.now(_resolve_timezone()))
    return success_at >= current_period_start


async def _run_scheduled(kind: ReportKind) -> None:
    async with SessionLocal() as db:
        locked = await db.scalar(text("SELECT pg_try_advisory_lock(:lock_key)"), {"lock_key": kind.lock_key})
        if not locked:
            logger.info("%s report skipped: another worker owns the scheduler lock.", kind.key)
            return
        try:
            org_res = await db.execute(select(Organisation.id).order_by(Organisation.id))
            org_ids = [row[0] for row in org_res.all()]
            for org_id in org_ids:
                try:
                    set_current_tenant_id(org_id)
                    if await _already_sent_for_period(db, org_id, kind):
                        logger.info("%s report already sent for organisation_id=%s", kind.key, org_id)
                        continue
                    await send_treasury_report(db, tenant_id=org_id, kind=kind)
                except TreasuryReportNotSent as exc:
                    logger.warning("%s report not sent for organisation_id=%s: %s", kind.key, org_id, exc)
                except Exception:
                    logger.exception("%s report failed for organisation_id=%s", kind.key, org_id)
                finally:
                    set_current_tenant_id(None)
        finally:
            await db.execute(text("SELECT pg_advisory_unlock(:lock_key)"), {"lock_key": kind.lock_key})
            await db.commit()


async def run_weekly_report() -> None:
    await _run_scheduled(WEEKLY)


async def run_monthly_treasury_report() -> None:
    await _run_scheduled(MONTHLY)
