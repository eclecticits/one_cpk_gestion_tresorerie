"""Statut du rapport de trésorerie mensuel

Revision ID: 20261001_monthly_treasury_st
Revises: 20260930_type_client_sec

Le rapport hebdomadaire a désormais un pendant mensuel (mois écoulé, envoyé le
1er du mois). Il a ses propres colonnes de statut : les partager avec l'hebdo
ferait qu'un envoi réussi de l'un masque l'échec de l'autre.

Create Date: 2026-10-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20261001_monthly_treasury_st"
down_revision = "20260930_type_client_sec"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column("last_monthly_report_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "system_settings",
        sa.Column("last_monthly_report_status", sa.String(20), nullable=False, server_default="never"),
    )
    op.add_column(
        "system_settings",
        sa.Column("last_monthly_report_error", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "system_settings",
        sa.Column("last_monthly_report_success_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "system_settings",
        sa.Column("last_monthly_report_failure_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "last_monthly_report_failure_at")
    op.drop_column("system_settings", "last_monthly_report_success_at")
    op.drop_column("system_settings", "last_monthly_report_error")
    op.drop_column("system_settings", "last_monthly_report_status")
    op.drop_column("system_settings", "last_monthly_report_sent_at")
