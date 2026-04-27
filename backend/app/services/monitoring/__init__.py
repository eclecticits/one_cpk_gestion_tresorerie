from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organisation import Organisation
from app.models.system_settings import SystemSettings
from app.services.mailer import send_monitoring_alert_email
from app.services.email_config import resolve_smtp_config
from app.services.monitoring.events import log_system_event
from app.services.system_settings_service import get_system_settings

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def refresh_platform_metrics(db: AsyncSession) -> None:
    await db.execute(text("REFRESH MATERIALIZED VIEW saas_platform_metrics"))
    await db.commit()


async def fetch_platform_summary(db: AsyncSession) -> dict:
    since = _utcnow() - timedelta(days=1)
    res = await db.execute(
        text(
            """
            SELECT
                COALESCE(SUM(CASE WHEN e.devise_perception = 'USD' THEN e.montant_paye ELSE 0 END), 0) AS total_volume_usd,
                COUNT(DISTINCT e.id) AS total_transactions,
                COALESCE(SUM(CASE WHEN pt.status = 'SUCCESS' THEN 1 ELSE 0 END), 0) AS success_tx,
                COALESCE(SUM(CASE WHEN pt.status IN ('FAILED') THEN 1 ELSE 0 END), 0) AS failed_tx
            FROM encaissements e
            LEFT JOIN payment_transactions pt ON pt.encaissement_id = e.id
            WHERE e.created_at >= :since
              AND e.est_proforma IS FALSE
            """
        ),
        {"since": since},
    )
    row = res.first()
    total_volume_usd = float(row.total_volume_usd or 0) if row else 0.0
    total_transactions = int(row.total_transactions or 0) if row else 0
    success_tx = int(row.success_tx or 0) if row else 0
    failed_tx = int(row.failed_tx or 0) if row else 0
    total_webhook = success_tx + failed_tx
    webhook_success_rate = round((success_tx / total_webhook) * 100, 2) if total_webhook else 100.0

    org_res = await db.execute(
        text(
            """
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(CASE WHEN is_active THEN 1 ELSE 0 END), 0) AS active
            FROM organisations
            """
        )
    )
    org_row = org_res.first()
    total_tenants = int(org_row.total or 0) if org_row else 0
    active_tenants = int(org_row.active or 0) if org_row else 0

    err_res = await db.execute(
        text(
            """
            SELECT COUNT(*) AS errors
            FROM system_events
            WHERE level = 'error' AND created_at >= :since
            """
        ),
        {"since": since},
    )
    err_row = err_res.first()
    api_errors = int(err_row.errors or 0) if err_row else 0

    return {
        "total_volume_usd": total_volume_usd,
        "total_transactions": total_transactions,
        "active_tenants": active_tenants,
        "total_tenants": total_tenants,
        "webhook_success_rate": webhook_success_rate,
        "api_errors": api_errors,
    }


async def fetch_tenant_metrics(db: AsyncSession) -> list[dict]:
    res = await db.execute(text("SELECT * FROM saas_platform_metrics ORDER BY volume_encaisse_30j DESC NULLS LAST"))
    rows = res.mappings().all()
    return [dict(row) for row in rows]


async def fetch_expiring_soon(db: AsyncSession, days: int = 5) -> list[dict]:
    res = await db.execute(
        text(
            """
            SELECT id, nom, slug, plan_type, status_abonnement, date_expiration_abonnement
            FROM organisations
            WHERE date_expiration_abonnement IS NOT NULL
              AND date_expiration_abonnement <= (NOW() + (:days * INTERVAL '1 day'))
            ORDER BY date_expiration_abonnement ASC
            """
        ),
        {"days": int(days)},
    )
    rows = res.mappings().all()
    return [dict(row) for row in rows]


async def detect_anomalies(db: AsyncSession) -> list[dict]:
    res = await db.execute(
        text(
            """
            SELECT organisation_id, COUNT(*) AS pending_count
            FROM requisitions
            WHERE status = 'PENDING_VALIDATION_IMPORT'
              AND created_at < NOW() - INTERVAL '10 days'
            GROUP BY organisation_id
            ORDER BY pending_count DESC
            """
        )
    )
    anomalies = []
    for row in res.mappings().all():
        anomalies.append(
            {
                "type": "stale_requisitions",
                "organisation_id": row["organisation_id"],
                "count": int(row["pending_count"] or 0),
            }
        )
    spike_res = await db.execute(
        text(
            """
            SELECT organisation_id, COUNT(*) AS recent_count
            FROM requisitions
            WHERE created_at >= NOW() - INTERVAL '1 hour'
            GROUP BY organisation_id
            HAVING COUNT(*) >= 100
            ORDER BY recent_count DESC
            """
        )
    )
    for row in spike_res.mappings().all():
        anomalies.append(
            {
                "type": "requisition_spike",
                "organisation_id": row["organisation_id"],
                "count": int(row["recent_count"] or 0),
            }
        )
    return anomalies


async def send_anomaly_alerts(db: AsyncSession) -> int:
    anomalies = await detect_anomalies(db)
    if not anomalies:
        return 0

    now = _utcnow()
    sent = 0
    for anomaly in anomalies:
        org_id = anomaly.get("organisation_id")
        if not org_id:
            continue

        exists_res = await db.execute(
            text(
                """
                SELECT COUNT(*) AS cnt
                FROM system_events
                WHERE organisation_id = :org_id
                  AND code = 'ANOMALY_ALERT'
                  AND created_at >= :since
                  AND metadata->>'type' = :atype
                """
            ),
            {"org_id": org_id, "since": now - timedelta(hours=24), "atype": anomaly.get("type", "")},
        )
        if (exists_res.first().cnt or 0) > 0:
            continue

        org_res = await db.execute(select(Organisation).where(Organisation.id == org_id))
        org = org_res.scalar_one_or_none()
        if org is None:
            continue

        ns = await get_system_settings(db, org_id)
        smtp_cfg = resolve_smtp_config(ns)
        if ns is None or smtp_cfg is None:
            continue

        recipient = (org.email_contact or ns.email_president or ns.email_tresorier or "").strip()
        if not recipient:
            continue

        subject = f"Alerte monitoring SaaS - {org.nom}"
        lines = [
            f"Organisation : {org.nom} ({org.slug})",
            f"Type d'alerte : {anomaly.get('type')}",
            f"Occurrences : {anomaly.get('count')}",
            "Merci de vérifier votre tableau de bord ou de contacter le support.",
        ]
        send_monitoring_alert_email(
            smtp_host=smtp_cfg.host,
            smtp_port=smtp_cfg.port,
            smtp_user=smtp_cfg.user,
            smtp_password=smtp_cfg.password,
            sender=smtp_cfg.sender,
            recipient=recipient,
            cc_emails=ns.emails_bureau_cc or None,
            subject=subject,
            lines=lines,
        )
        await log_system_event(
            db,
            level="warning",
            code="ANOMALY_ALERT",
            message="Anomaly alert email sent",
            organisation_id=org_id,
            metadata={"type": anomaly.get("type"), "count": anomaly.get("count")},
        )
        sent += 1

    return sent
