from __future__ import annotations

from pydantic import BaseModel


class OrganisationSettingsPublicOut(BaseModel):
    organisation_id: int
    max_users: int
    storage_quota_mb: int
    is_ai_enabled: bool
    is_mobile_money_enabled: bool
    is_audit_logs_enabled: bool
    fiscal_year_start: int
    currency_code: str
