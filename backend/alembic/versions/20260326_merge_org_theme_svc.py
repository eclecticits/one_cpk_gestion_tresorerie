"""Merge org theme text color + services tenant scope.

Revision ID: 20260326_merge_org_theme_svc
Revises: 20260325_services_tenant_scope, 20260326_org_theme_text_color
Create Date: 2026-03-26
"""

from __future__ import annotations

revision = "20260326_merge_org_theme_svc"
down_revision = (
    "20260325_services_tenant_scope",
    "20260326_org_theme_text_color",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
