from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import anyio
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.organisation import Organisation
from app.models.plan import Plan
from app.models.saas_invoice import SaaSInvoice
from app.models.saas_transaction import Transaction
from app.models.subscription import Subscription
from app.models.user import User
from app.services import saas_invoicing
from app.services.mailer import send_in_thread, send_saas_invoice_email, send_subscription_renewal_alert_email


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _upload_root() -> str:
    default_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "uploads"))
    return os.path.abspath(settings.upload_dir) if settings.upload_dir else default_root


def _format_date(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).strftime("%d/%m/%Y")


def _smtp_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_port and settings.smtp_user and settings.smtp_password)


async def _admin_recipients(db: AsyncSession, org: Organisation) -> list[str]:
    res = await db.execute(
        select(User.email).where(
            User.organisation_id == org.id,
            User.active.is_(True),
            func.lower(User.role) == "admin",
        )
    )
    emails = [str(email).strip().lower() for email in res.scalars().all() if email]
    if org.email_contact:
        emails.append(org.email_contact.strip().lower())
    return list(dict.fromkeys(email for email in emails if email))


async def _next_invoice_number(db: AsyncSession, org: Organisation, paid_at: datetime) -> str:
    prefix = f"SAAS-{paid_at:%Y%m}-{org.id:04d}"
    for _ in range(10):
        number = f"{prefix}-{uuid.uuid4().hex[:6].upper()}"
        res = await db.execute(select(SaaSInvoice.id).where(SaaSInvoice.invoice_number == number))
        if res.scalar_one_or_none() is None:
            return number
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def _generate_invoice_pdf(
    *,
    invoice: SaaSInvoice,
    org: Organisation,
    transaction: Transaction,
    plan_name: str | None,
) -> str:
    target_dir = os.path.join(_upload_root(), "saas-invoices", str(org.id))
    os.makedirs(target_dir, exist_ok=True)
    path = os.path.join(target_dir, f"{invoice.invoice_number}.pdf")

    c = canvas.Canvas(path, pagesize=A4)
    width, height = A4
    y = height - 2 * cm

    c.setFont("Helvetica-Bold", 16)
    c.drawString(2 * cm, y, "Note de débit SaaS")
    c.setFont("Helvetica", 10)
    c.drawRightString(width - 2 * cm, y, invoice.invoice_number)
    y -= 1.2 * cm

    c.setFont("Helvetica-Bold", 10)
    c.drawString(2 * cm, y, "Plateforme")
    c.setFont("Helvetica", 10)
    c.drawString(2 * cm, y - 0.45 * cm, "ONE CPK SaaS")
    c.drawString(2 * cm, y - 0.9 * cm, "Revenu plateforme - abonnement tenant")

    c.setFont("Helvetica-Bold", 10)
    c.drawString(11 * cm, y, "Client")
    c.setFont("Helvetica", 10)
    c.drawString(11 * cm, y - 0.45 * cm, org.nom)
    c.drawString(11 * cm, y - 0.9 * cm, f"Tenant : {org.slug}")
    y -= 2.2 * cm

    c.setFont("Helvetica-Bold", 10)
    c.drawString(2 * cm, y, "Date note de débit")
    c.drawString(6 * cm, y, "Date paiement")
    c.drawString(10 * cm, y, "Periode")
    c.setFont("Helvetica", 10)
    c.drawString(2 * cm, y - 0.45 * cm, _format_date(invoice.issue_date) or "-")
    c.drawString(6 * cm, y - 0.45 * cm, _format_date(invoice.paid_at) or "-")
    c.drawString(
        10 * cm,
        y - 0.45 * cm,
        f"{_format_date(invoice.period_start) or '-'} au {_format_date(invoice.period_end) or '-'}",
    )
    y -= 1.6 * cm

    c.setFont("Helvetica-Bold", 10)
    c.drawString(2 * cm, y, "Description")
    c.drawRightString(width - 2 * cm, y, "Montant")
    y -= 0.4 * cm
    c.line(2 * cm, y, width - 2 * cm, y)
    y -= 0.6 * cm

    description = f"Abonnement SaaS {plan_name or org.plan_type or ''}".strip()
    c.setFont("Helvetica", 10)
    c.drawString(2 * cm, y, description)
    c.drawRightString(width - 2 * cm, y, f"{float(invoice.amount):,.2f} {invoice.currency}")
    y -= 0.8 * cm
    c.line(2 * cm, y, width - 2 * cm, y)
    y -= 0.7 * cm

    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(width - 2 * cm, y, f"Total paye : {float(invoice.amount):,.2f} {invoice.currency}")
    y -= 1.0 * cm

    c.setFont("Helvetica", 9)
    c.drawString(2 * cm, y, f"Transaction : {transaction.id}")
    c.drawString(2 * cm, y - 0.4 * cm, f"Reference agregrateur : {transaction.external_reference or '-'}")
    c.drawString(2 * cm, y - 0.8 * cm, "Flux : abonnement SaaS -> compte bancaire de la plateforme")

    c.setFont("Helvetica", 8)
    c.drawCentredString(width / 2, 1.5 * cm, "Document genere automatiquement apres paiement de l'abonnement SaaS.")
    c.showPage()
    c.save()
    return path


async def _deliver_invoice_email(
    db: AsyncSession,
    *,
    invoice: SaaSInvoice,
    org: Organisation,
    period_end: datetime | None,
) -> bool:
    """Envoie la facture aux administrateurs du tenant et horodate l'envoi."""
    recipients = await _admin_recipients(db, org)
    if not recipients or not _smtp_configured():
        return False
    sent = await send_in_thread(
        send_saas_invoice_email,
        smtp_host=settings.smtp_host or "",
        smtp_port=int(settings.smtp_port or 465),
        smtp_user=settings.smtp_user or "",
        smtp_password=settings.smtp_password or "",
        sender=settings.smtp_user or "",
        recipients=recipients,
        invoice_number=invoice.invoice_number,
        organisation_name=org.nom,
        amount=float(invoice.amount),
        currency=invoice.currency,
        period_end=_format_date(period_end),
        attachment_path=invoice.pdf_path,
    )
    if sent:
        invoice.sent_at = _utcnow()
        invoice.recipient_email = ", ".join(recipients)
    return bool(sent)


async def create_and_send_saas_invoice(
    db: AsyncSession,
    *,
    transaction: Transaction,
    org: Organisation,
    subscription: Subscription | None,
    period_start: datetime | None,
    period_end: datetime | None,
    plan_name: str | None,
) -> SaaSInvoice:
    res = await db.execute(select(SaaSInvoice).where(SaaSInvoice.transaction_id == transaction.id))
    existing = res.scalar_one_or_none()
    if existing:
        return existing

    now = _utcnow()

    # Une facture avait pu etre emise en amont depuis la console : le paiement
    # en ligne la solde, il n'en cree pas une seconde. Sans ce rattrapage, le
    # tenant recevrait deux pieces pour une seule dette, et la facture emise
    # resterait indefiniment « en attente ».
    open_invoice = await saas_invoicing.find_open_invoice(db, organisation_id=org.id)
    if open_invoice is not None:
        open_invoice.transaction_id = transaction.id
        open_invoice.subscription_id = open_invoice.subscription_id or (subscription.id if subscription else None)
        open_invoice.period_start = open_invoice.period_start or period_start
        open_invoice.period_end = open_invoice.period_end or period_end
        await saas_invoicing.mark_invoice_paid(
            db,
            open_invoice,
            method="ONLINE",
            reference=transaction.external_reference or transaction.id,
            paid_at=now,
            recorded_by=None,
            org=org,
        )
        await _deliver_invoice_email(
            db,
            invoice=open_invoice,
            org=org,
            period_end=open_invoice.period_end,
        )
        if subscription:
            subscription.renewal_alert_sent_at = None
            subscription.renewal_alert_period_end = None
        return open_invoice

    invoice = SaaSInvoice(
        invoice_number=await _next_invoice_number(db, org, now),
        organisation_id=org.id,
        subscription_id=subscription.id if subscription else None,
        transaction_id=transaction.id,
        status="PAID",
        amount=Decimal(str(transaction.amount)),
        currency=transaction.currency,
        issue_date=now,
        paid_at=now,
        period_start=period_start,
        period_end=period_end,
        metadata_json={
            "flow": transaction.flow,
            "beneficiary_type": transaction.beneficiary_type,
            "provider": transaction.provider,
            "provider_ref": transaction.external_reference,
        },
    )
    db.add(invoice)
    await db.flush()

    # Tracé reportlab + écriture disque : synchrone, donc confié à un thread
    # pour ne pas figer la boucle d'événements.
    pdf_path = await anyio.to_thread.run_sync(
        lambda: _generate_invoice_pdf(
            invoice=invoice, org=org, transaction=transaction, plan_name=plan_name
        )
    )
    invoice.pdf_path = pdf_path

    await _deliver_invoice_email(db, invoice=invoice, org=org, period_end=period_end)

    if subscription:
        subscription.renewal_alert_sent_at = None
        subscription.renewal_alert_period_end = None
    invoice.updated_at = _utcnow()
    return invoice


async def send_renewal_alerts(db: AsyncSession, *, days_before: int = 10) -> int:
    if not _smtp_configured():
        return 0

    now = _utcnow()
    limit = now + timedelta(days=days_before)
    res = await db.execute(
        select(Subscription, Organisation, Plan)
        .join(Organisation, Organisation.id == Subscription.organisation_id)
        .join(Plan, Plan.id == Subscription.plan_id, isouter=True)
        .where(
            Subscription.status == "ACTIVE",
            Subscription.current_period_end.is_not(None),
            Subscription.current_period_end > now,
            Subscription.current_period_end <= limit,
        )
    )
    rows = res.all()
    sent_count = 0
    for subscription, org, plan in rows:
        if (
            subscription.renewal_alert_sent_at is not None
            and subscription.renewal_alert_period_end == subscription.current_period_end
        ):
            continue
        recipients = await _admin_recipients(db, org)
        if not recipients:
            continue
        expires_at = subscription.current_period_end
        days_left = max(0, (expires_at.date() - now.date()).days)
        sent = await send_in_thread(
            send_subscription_renewal_alert_email,
            smtp_host=settings.smtp_host or "",
            smtp_port=int(settings.smtp_port or 465),
            smtp_user=settings.smtp_user or "",
            smtp_password=settings.smtp_password or "",
            sender=settings.smtp_user or "",
            recipients=recipients,
            organisation_name=org.nom,
            plan_name=plan.name if plan else org.plan_type,
            expires_at=_format_date(expires_at) or "",
            days_left=days_left,
        )
        if sent:
            subscription.renewal_alert_sent_at = _utcnow()
            subscription.renewal_alert_period_end = subscription.current_period_end
            subscription.updated_at = _utcnow()
            sent_count += 1
    return sent_count
