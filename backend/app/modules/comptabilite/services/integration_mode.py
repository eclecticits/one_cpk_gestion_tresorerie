from __future__ import annotations

from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organisation_settings import OrganisationSettings
from app.modules.comptabilite.models import ComptaSociete

AccountingIntegrationMode = Literal["disabled", "manual", "automatic"]

VALID_ACCOUNTING_INTEGRATION_MODES: set[str] = {"disabled", "manual", "automatic"}

STATUT_NON_COMPTABILISEE = "NON_COMPTABILISEE"
STATUT_A_COMPTABILISER_MANUELLEMENT = "A_COMPTABILISER_MANUELLEMENT"
STATUT_COMPTABILISEE = "COMPTABILISEE"
STATUT_ERREUR_COMPTABLE = "ERREUR_COMPTABLE"


def normalize_accounting_integration_mode(value: str | None) -> AccountingIntegrationMode:
    normalized = (value or "manual").strip().lower()
    if normalized in VALID_ACCOUNTING_INTEGRATION_MODES:
        return normalized  # type: ignore[return-value]
    return "manual"


async def get_accounting_integration_mode(
    db: AsyncSession,
    organisation_id: int,
    *,
    require_societe_for_automatic: bool = True,
) -> AccountingIntegrationMode:
    res = await db.execute(
        select(OrganisationSettings.accounting_integration_mode).where(
            OrganisationSettings.organisation_id == organisation_id
        )
    )
    configured = normalize_accounting_integration_mode(res.scalar_one_or_none())
    if not require_societe_for_automatic or configured == "disabled":
        return configured

    societe_res = await db.execute(
        select(ComptaSociete.id)
        .where(ComptaSociete.organisation_id == organisation_id, ComptaSociete.is_default.is_(True))
        .limit(1)
    )
    if societe_res.scalar_one_or_none() is None:
        return "disabled"
    return configured


async def is_accounting_automatic(db: AsyncSession, organisation_id: int) -> bool:
    return await get_accounting_integration_mode(db, organisation_id) == "automatic"


def status_for_recorded_operation(mode: AccountingIntegrationMode) -> str:
    if mode == "manual":
        return STATUT_A_COMPTABILISER_MANUELLEMENT
    return STATUT_NON_COMPTABILISEE
