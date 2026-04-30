"""Scope member functions by service.

Revision ID: 20260430_memfuncsvc
Revises: 20260430_member_clean
Create Date: 2026-04-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260430_memfuncsvc"
down_revision = "20260430_member_clean"
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
    (9, "Autre"),
]


def _canonical_sql(column_name: str) -> str:
    return f"""regexp_replace(lower(translate(btrim({column_name}),
        'àáâäãåèéêëìíîïòóôöõùúûüýÿçñÀÁÂÄÃÅÈÉÊËÌÍÎÏÒÓÔÖÕÙÚÛÜÝÇÑ',
        'aaaaaaeeeeiiiiooooouuuuyycnAAAAAAEEEEIIIIOOOOOUUUUYCN'
    )), '[^a-z0-9]+', '', 'g')"""


def upgrade() -> None:
    op.add_column("service_member_functions", sa.Column("service_id", sa.Integer(), nullable=True))
    op.create_index("ix_service_member_functions_service_id", "service_member_functions", ["service_id"])
    op.create_foreign_key(
        "fk_service_member_functions_service_id",
        "service_member_functions",
        "services",
        ["service_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("uq_service_member_functions_org_label", "service_member_functions", type_="unique")

    op.execute(
        """
        INSERT INTO service_member_functions (label, sort_order, is_default, is_active, organisation_id, service_id, created_at, updated_at)
        SELECT smf.label, smf.sort_order, smf.is_default, smf.is_active, smf.organisation_id, s.id, NOW(), NOW()
        FROM service_member_functions smf
        JOIN services s ON s.organisation_id = smf.organisation_id
        WHERE smf.service_id IS NULL
        """
    )

    op.execute(
        """
        UPDATE commission_members cm
        SET function_id = scoped.id
        FROM services s,
             service_member_functions original,
             service_member_functions scoped
        WHERE cm.service_id = s.id
          AND original.id = cm.function_id
          AND original.service_id IS NULL
          AND scoped.organisation_id = s.organisation_id
          AND scoped.service_id = cm.service_id
          AND scoped.label = original.label
        """
    )

    op.execute("DELETE FROM service_member_functions WHERE service_id IS NULL")

    canonical_service = _canonical_sql("smf.label")
    for sort_order, label in DEFAULT_FUNCTIONS:
        escaped = label.replace("'", "''")
        canonical_default = _canonical_sql(f"'{escaped}'")
        op.execute(
            f"""
            INSERT INTO service_member_functions (label, sort_order, is_default, is_active, organisation_id, service_id, created_at, updated_at)
            SELECT '{escaped}', {sort_order}, TRUE, TRUE, s.organisation_id, s.id, NOW(), NOW()
            FROM services s
            WHERE NOT EXISTS (
                SELECT 1
                FROM service_member_functions smf
                WHERE smf.organisation_id = s.organisation_id
                  AND smf.service_id = s.id
                  AND {canonical_service} = {canonical_default}
            )
            """
        )
        op.execute(
            f"""
            UPDATE service_member_functions smf
            SET sort_order = {sort_order},
                is_default = TRUE,
                is_active = TRUE,
                updated_at = NOW()
            WHERE {canonical_service} = {canonical_default}
            """
        )

    op.create_unique_constraint(
        "uq_service_member_functions_org_service_label",
        "service_member_functions",
        ["organisation_id", "service_id", "label"],
    )
    op.alter_column("service_member_functions", "service_id", nullable=False)


def downgrade() -> None:
    pass
