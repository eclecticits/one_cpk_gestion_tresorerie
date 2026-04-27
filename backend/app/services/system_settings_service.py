from __future__ import annotations

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_settings import SystemSettings


def _settings_priority_query(organisation_id: int):
    return (
        select(SystemSettings)
        .where(SystemSettings.organisation_id == organisation_id)
        .order_by(
            (SystemSettings.email_expediteur != "").desc(),
            (SystemSettings.smtp_password != "").desc(),
            (SystemSettings.email_validation_1 != "").desc(),
            (SystemSettings.email_validation_final != "").desc(),
            (SystemSettings.email_president != "").desc(),
            (SystemSettings.email_tresorier != "").desc(),
            (SystemSettings.whatsapp_api_url != "").desc(),
            SystemSettings.updated_at.desc(),
            SystemSettings.id.desc(),
        )
    )


async def get_system_settings(db: AsyncSession, organisation_id: int) -> SystemSettings | None:
    result = await db.execute(_settings_priority_query(organisation_id).limit(1))
    return result.scalar_one_or_none()


async def consolidate_system_settings(db: AsyncSession, organisation_id: int) -> SystemSettings | None:
    result = await db.execute(_settings_priority_query(organisation_id))
    rows = list(result.scalars().all())
    if not rows:
        return None

    primary = rows[0]
    duplicates = rows[1:]
    if not duplicates:
        return primary

    string_fields = (
        "email_expediteur",
        "email_president",
        "emails_bureau_cc",
        "email_tresorier",
        "emails_bureau_sortie_cc",
        "email_validation_1",
        "email_validation_final",
        "smtp_password",
        "smtp_host",
        "whatsapp_api_url",
        "whatsapp_api_key",
        "whatsapp_agents",
        "last_weekly_report_status",
        "last_weekly_report_error",
    )
    int_fields = ("max_caisse_amount", "smtp_port")
    datetime_fields = (
        "last_weekly_report_sent_at",
        "last_weekly_report_success_at",
        "last_weekly_report_failure_at",
        "updated_at",
    )

    for duplicate in duplicates:
        for field in string_fields:
            primary_value = getattr(primary, field, "") or ""
            duplicate_value = getattr(duplicate, field, "") or ""
            if not primary_value and duplicate_value:
                setattr(primary, field, duplicate_value)
        for field in int_fields:
            primary_value = getattr(primary, field, None)
            duplicate_value = getattr(duplicate, field, None)
            if (primary_value is None or primary_value == 0) and duplicate_value not in (None, 0):
                setattr(primary, field, duplicate_value)
        for field in datetime_fields:
            primary_value = getattr(primary, field, None)
            duplicate_value = getattr(duplicate, field, None)
            if primary_value is None and duplicate_value is not None:
                setattr(primary, field, duplicate_value)

    for duplicate in duplicates:
        await db.delete(duplicate)

    await db.commit()
    await db.refresh(primary)
    return primary
