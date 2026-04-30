"""Add dynamic service member functions.

Revision ID: 20260430_member_funcs
Revises: 20260428_fin_cancel
Create Date: 2026-04-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260430_member_funcs"
down_revision = "20260428_fin_cancel"
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
    op.create_table(
        "service_member_functions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("label", sa.String(length=150), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("organisation_id", "label", name="uq_service_member_functions_org_label"),
    )
    op.create_index(
        "ix_service_member_functions_organisation_id",
        "service_member_functions",
        ["organisation_id"],
    )

    op.add_column("commission_members", sa.Column("function_id", sa.Integer(), nullable=True))
    op.create_index("ix_commission_members_function_id", "commission_members", ["function_id"])
    op.create_foreign_key(
        "fk_commission_members_function_id",
        "commission_members",
        "service_member_functions",
        ["function_id"],
        ["id"],
        ondelete="SET NULL",
    )

    values_sql = ",\n".join(
        "({}, '{}')".format(sort_order, label.replace("'", "''")) for sort_order, label in DEFAULT_FUNCTIONS
    )
    op.execute(
        f"""
        INSERT INTO service_member_functions (label, sort_order, is_default, is_active, organisation_id, created_at, updated_at)
        SELECT defs.label, defs.sort_order, TRUE, TRUE, org.id, NOW(), NOW()
        FROM organisations org
        CROSS JOIN (
            VALUES
            {values_sql}
        ) AS defs(sort_order, label)
        """
    )

    op.execute(
        """
        INSERT INTO service_member_functions (label, sort_order, is_default, is_active, organisation_id, created_at, updated_at)
        SELECT 'Autre', 999, FALSE, TRUE, s.organisation_id, NOW(), NOW()
        FROM services s
        JOIN commission_members cm ON cm.service_id = s.id
        LEFT JOIN service_member_functions smf
          ON smf.organisation_id = s.organisation_id
         AND LOWER(TRIM(smf.label)) = 'autre'
        WHERE cm.role_type NOT IN ('PRESIDENT', 'DELEGUE', 'ASSISTANT')
          AND smf.id IS NULL
        GROUP BY s.organisation_id
        """
    )

    mapping_cases = """
        CASE cm.role_type
            WHEN 'PRESIDENT' THEN 'Président(e)'
            WHEN 'DELEGUE' THEN 'Vice-président(e)'
            WHEN 'ASSISTANT' THEN 'Assistant(e)'
            ELSE 'Autre'
        END
    """
    op.execute(
        f"""
        UPDATE commission_members AS cm
        SET function_id = smf.id
        FROM services AS s, service_member_functions AS smf
        WHERE cm.service_id = s.id
          AND smf.organisation_id = s.organisation_id
          AND smf.label = {mapping_cases}
          AND cm.function_id IS NULL
        """
    )

    op.alter_column("service_member_functions", "sort_order", server_default=None)
    op.alter_column("service_member_functions", "is_default", server_default=None)
    op.alter_column("service_member_functions", "is_active", server_default=None)


def downgrade() -> None:
    op.drop_constraint("fk_commission_members_function_id", "commission_members", type_="foreignkey")
    op.drop_index("ix_commission_members_function_id", table_name="commission_members")
    op.drop_column("commission_members", "function_id")

    op.drop_index("ix_service_member_functions_organisation_id", table_name="service_member_functions")
    op.drop_table("service_member_functions")
