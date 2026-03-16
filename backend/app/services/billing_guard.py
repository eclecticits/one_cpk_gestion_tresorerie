from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal
from app.models.organisation import Organisation
from app.models.subscription import Subscription


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def enforce_subscription_status(db: AsyncSession) -> int:
    now = _utcnow()
    res = await db.execute(
        select(Subscription).where(
            Subscription.status.in_(["ACTIVE", "TRIAL"]),
            Subscription.current_period_end.is_not(None),
            Subscription.current_period_end < now,
        )
    )
    subs = res.scalars().all()
    if not subs:
        return 0

    affected = 0
    for sub in subs:
        sub.status = "SUSPENDED"
        sub.updated_at = now
        org_res = await db.execute(select(Organisation).where(Organisation.id == sub.organisation_id))
        org = org_res.scalar_one_or_none()
        if org:
            org.status_abonnement = "SUSPENDED"
            org.updated_at = now
        affected += 1

    await db.commit()
    return affected


async def run_billing_guard() -> None:
    async with SessionLocal() as session:
        await enforce_subscription_status(session)
