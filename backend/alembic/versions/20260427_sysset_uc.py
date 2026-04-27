"""Deduplicate system settings per organisation.

Revision ID: 20260427_sysset_uc
Revises: 20260424_lig_req_snap
Create Date: 2026-04-27
"""

from alembic import op
import sqlalchemy as sa


revision = "20260427_sysset_uc"
down_revision = "20260424_lig_req_snap"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                organisation_id,
                ROW_NUMBER() OVER (
                    PARTITION BY organisation_id
                    ORDER BY
                        CASE WHEN COALESCE(email_expediteur, '') <> '' THEN 1 ELSE 0 END DESC,
                        CASE WHEN COALESCE(smtp_password, '') <> '' THEN 1 ELSE 0 END DESC,
                        CASE WHEN COALESCE(email_validation_1, '') <> '' THEN 1 ELSE 0 END DESC,
                        CASE WHEN COALESCE(email_validation_final, '') <> '' THEN 1 ELSE 0 END DESC,
                        CASE WHEN COALESCE(email_president, '') <> '' THEN 1 ELSE 0 END DESC,
                        CASE WHEN COALESCE(email_tresorier, '') <> '' THEN 1 ELSE 0 END DESC,
                        updated_at DESC,
                        id DESC
                ) AS rn
            FROM system_settings
        )
        DELETE FROM system_settings s
        USING ranked r
        WHERE s.id = r.id
          AND r.rn > 1
        """
    )
    op.create_unique_constraint("uq_system_settings_org", "system_settings", ["organisation_id"])


def downgrade() -> None:
    op.drop_constraint("uq_system_settings_org", "system_settings", type_="unique")
