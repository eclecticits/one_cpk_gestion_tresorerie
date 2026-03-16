from __future__ import annotations

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organisation import Organisation
from app.models.payment_transaction import PaymentTransaction


async def get_global_treasury_stats(db: AsyncSession) -> list[dict]:
    stmt = (
        select(
            Organisation.id.label("organisation_id"),
            Organisation.nom.label("organisation_name"),
            Organisation.slug.label("organisation_slug"),
            Organisation.is_active.label("organisation_active"),
            func.coalesce(
                func.sum(
                    case(
                        (PaymentTransaction.status == "SUCCESS", PaymentTransaction.amount),
                        else_=0,
                    )
                ),
                0,
            ).label("total_encaisse"),
            func.coalesce(
                func.sum(
                    case(
                        (PaymentTransaction.status == "SUCCESS", 1),
                        else_=0,
                    )
                ),
                0,
            ).label("success_tx"),
        )
        .outerjoin(PaymentTransaction, PaymentTransaction.organisation_id == Organisation.id)
        .group_by(Organisation.id)
        .order_by(Organisation.nom.asc())
    )
    res = await db.execute(stmt)
    rows = res.all()
    payload = []
    for row in rows:
        payload.append(
            {
                "organisation_id": row.organisation_id,
                "organisation_name": row.organisation_name,
                "organisation_slug": row.organisation_slug,
                "total_encaisse": float(row.total_encaisse or 0),
                "success_tx": int(row.success_tx or 0),
                "is_active": bool(row.organisation_active),
            }
        )
    return payload
