"""Normalize default member functions for all tenants.

Revision ID: 20260430_member_defs
Revises: 20260430_member_funcs
Create Date: 2026-04-30
"""

from __future__ import annotations

from alembic import op


revision = "20260430_member_defs"
down_revision = "20260430_member_funcs"
branch_labels = None
depends_on = None


DEFAULT_FUNCTIONS = [
    (1, "Président(e)"),
    (2, "Vice-président(e)"),
    (3, "Rapporteur"),
    (4, "Rapporteur adjoint"),
    (5, "Trésorier"),
    (6, "Trésorier(e) adjoint"),
    (7, "Secrétaire exécutif"),
    (8, "Assistant(e)"),
]


def upgrade() -> None:
    for sort_order, label in DEFAULT_FUNCTIONS:
        escaped = label.replace("'", "''")
        op.execute(
            f"""
            INSERT INTO service_member_functions (label, sort_order, is_default, is_active, organisation_id, created_at, updated_at)
            SELECT '{escaped}', {sort_order}, TRUE, TRUE, org.id, NOW(), NOW()
            FROM organisations org
            WHERE NOT EXISTS (
                SELECT 1
                FROM service_member_functions smf
                WHERE smf.organisation_id = org.id
                  AND LOWER(BTRIM(smf.label)) = LOWER('{escaped}')
            )
            """
        )
        op.execute(
            f"""
            UPDATE service_member_functions
            SET sort_order = {sort_order},
                is_default = TRUE,
                is_active = TRUE,
                updated_at = NOW()
            WHERE LOWER(BTRIM(label)) = LOWER('{escaped}')
            """
        )

    op.execute(
        """
        UPDATE service_member_functions
        SET is_default = FALSE,
            sort_order = CASE WHEN sort_order <= 8 THEN 999 ELSE sort_order END,
            updated_at = NOW()
        WHERE LOWER(BTRIM(label)) = 'autre'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE service_member_functions
        SET is_default = TRUE,
            sort_order = 9,
            updated_at = NOW()
        WHERE LOWER(BTRIM(label)) = 'autre'
        """
    )
