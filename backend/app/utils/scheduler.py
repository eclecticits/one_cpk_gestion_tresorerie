from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.services.weekly_report import run_weekly_report, _resolve_timezone

logger = logging.getLogger("onec_cpk_api.scheduler")

_scheduler: AsyncIOScheduler | None = None


def start_weekly_report_scheduler() -> None:
    global _scheduler
    if not settings.weekly_report_enabled:
        logger.info("Weekly report scheduler disabled (WEEKLY_REPORT_ENABLED=false).")
        return

    if _scheduler and _scheduler.running:
        return

    tz = _resolve_timezone()
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


def get_weekly_report_status() -> dict:
    tz = _resolve_timezone()
    running = bool(_scheduler and _scheduler.running)
    job = _scheduler.get_job("weekly_report_job") if running else None
    next_run = job.next_run_time.isoformat() if job and job.next_run_time else None
    return {
        "enabled": settings.weekly_report_enabled,
        "running": running,
        "timezone": tz.key,
        "next_run": next_run,
        "schedule": {
            "day_of_week": settings.weekly_report_day_of_week,
            "hour": settings.weekly_report_hour,
            "minute": settings.weekly_report_minute,
        },
    }
