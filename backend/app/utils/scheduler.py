from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.services.weekly_report import run_weekly_report, _resolve_timezone as _weekly_tz
from app.services.monthly_report import run_monthly_report, _resolve_timezone as _monthly_tz
from app.services.billing_guard import run_billing_guard

logger = logging.getLogger("onec_cpk_api.scheduler")

_scheduler: AsyncIOScheduler | None = None


def start_weekly_report_scheduler() -> None:
    global _scheduler
    if not settings.weekly_report_enabled:
        logger.info("Weekly report scheduler disabled (WEEKLY_REPORT_ENABLED=false).")
        return

    if _scheduler and _scheduler.running:
        return

    tz = _weekly_tz()
    trigger = CronTrigger(
        day_of_week=settings.weekly_report_day_of_week,
        hour=settings.weekly_report_hour,
        minute=settings.weekly_report_minute,
        timezone=tz,
    )

    scheduler = AsyncIOScheduler(timezone=tz)
    scheduler.add_job(
        run_weekly_report,
        trigger,
        id="weekly_report_job",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    job = scheduler.get_job("weekly_report_job")
    next_run = job.next_run_time.isoformat() if job and job.next_run_time else "unknown"
    logger.info(
        "Weekly report scheduler started: %s %02d:%02d (%s). Next run: %s",
        settings.weekly_report_day_of_week,
        settings.weekly_report_hour,
        settings.weekly_report_minute,
        tz.key,
        next_run,
    )


def start_monthly_report_scheduler() -> None:
    global _scheduler
    if not settings.monthly_report_enabled:
        logger.info("Monthly report scheduler disabled (MONTHLY_REPORT_ENABLED=false).")
        return

    if _scheduler and _scheduler.running:
        pass

    tz = _monthly_tz()
    trigger = CronTrigger(
        day=settings.monthly_report_day_of_month,
        hour=settings.monthly_report_hour,
        minute=settings.monthly_report_minute,
        timezone=tz,
    )

    if _scheduler is None:
        scheduler = AsyncIOScheduler(timezone=tz)
        _scheduler = scheduler
    else:
        scheduler = _scheduler

    scheduler.add_job(
        run_monthly_report,
        trigger,
        id="monthly_report_job",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    if not scheduler.running:
        scheduler.start()

    job = scheduler.get_job("monthly_report_job")
    next_run = job.next_run_time.isoformat() if job and job.next_run_time else "unknown"
    logger.info(
        "Monthly report scheduler started: day=%s %02d:%02d (%s). Next run: %s",
        settings.monthly_report_day_of_month,
        settings.monthly_report_hour,
        settings.monthly_report_minute,
        tz.key,
        next_run,
    )


def start_billing_guard_scheduler() -> None:
    global _scheduler
    if not settings.billing_guard_enabled:
        logger.info("Billing guard scheduler disabled (BILLING_GUARD_ENABLED=false).")
        return

    tz = settings.billing_guard_timezone or "UTC"
    trigger = CronTrigger(
        hour=settings.billing_guard_hour,
        minute=settings.billing_guard_minute,
        timezone=tz,
    )

    if _scheduler is None:
        scheduler = AsyncIOScheduler(timezone=tz)
        _scheduler = scheduler
    else:
        scheduler = _scheduler

    scheduler.add_job(
        run_billing_guard,
        trigger,
        id="billing_guard_job",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    if not scheduler.running:
        scheduler.start()

    job = scheduler.get_job("billing_guard_job")
    next_run = job.next_run_time.isoformat() if job and job.next_run_time else "unknown"
    logger.info(
        "Billing guard scheduler started: %02d:%02d (%s). Next run: %s",
        settings.billing_guard_hour,
        settings.billing_guard_minute,
        tz,
        next_run,
    )


def stop_schedulers() -> None:
    """Arrete l'ordonnanceur s'il tourne dans ce processus.

    Les trois ordonnanceurs partagent une seule instance APScheduler (`_scheduler`),
    ce qui rend l'arret unique lui aussi. Sans lui, un conteneur worker qui
    redemarre laissait un ordonnanceur et son pool de threads derriere lui.
    """
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None


def _hote_des_ordonnanceurs() -> str:
    return "exports-worker" if settings.schedulers_in_worker else "backend"


def get_weekly_report_status() -> dict:
    tz = _weekly_tz()
    running = bool(_scheduler and _scheduler.running)
    job = _scheduler.get_job("weekly_report_job") if running else None
    next_run = job.next_run_time.isoformat() if job and job.next_run_time else None
    return {
        "enabled": settings.weekly_report_enabled,
        # `running` ne vaut que pour CE processus. Quand les ordonnanceurs sont
        # portes par le worker, l'API ne peut pas savoir s'ils tournent : elle
        # le dit (`host`), plutot que de repondre « arrete » — une reponse
        # fausse est pire qu'une reponse qui s'avoue incomplete.
        "host": _hote_des_ordonnanceurs(),
        "running": running,
        "timezone": tz.key,
        "next_run": next_run,
        "schedule": {
            "day_of_week": settings.weekly_report_day_of_week,
            "hour": settings.weekly_report_hour,
            "minute": settings.weekly_report_minute,
        },
    }


def get_monthly_report_status() -> dict:
    tz = _monthly_tz()
    running = bool(_scheduler and _scheduler.running)
    job = _scheduler.get_job("monthly_report_job") if running else None
    next_run = job.next_run_time.isoformat() if job and job.next_run_time else None
    return {
        "enabled": settings.monthly_report_enabled,
        # `running` ne vaut que pour CE processus. Quand les ordonnanceurs sont
        # portes par le worker, l'API ne peut pas savoir s'ils tournent : elle
        # le dit (`host`), plutot que de repondre « arrete » — une reponse
        # fausse est pire qu'une reponse qui s'avoue incomplete.
        "host": _hote_des_ordonnanceurs(),
        "running": running,
        "timezone": tz.key,
        "next_run": next_run,
        "schedule": {
            "day_of_month": settings.monthly_report_day_of_month,
            "hour": settings.monthly_report_hour,
            "minute": settings.monthly_report_minute,
        },
    }
