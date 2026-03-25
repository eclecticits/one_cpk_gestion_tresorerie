"""Scope services by organisation.

Revision ID: 20260325_services_tenant_scope
Revises: 20260325_org_theme_settings
Create Date: 2026-03-25
"""

from alembic import op
import sqlalchemy as sa


revision = "20260325_services_tenant_scope"
down_revision = "20260325_org_theme_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("services", sa.Column("organisation_id", sa.Integer(), nullable=True))
    op.create_index("ix_services_organisation_id", "services", ["organisation_id"])
    op.create_foreign_key(
        "fk_services_organisation_id",
        "services",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.execute(
        """
        UPDATE services s
        SET organisation_id = src.org_id
        FROM (
            SELECT service_id, max(organisation_id) AS org_id
            FROM (
                SELECT service_id, organisation_id FROM requisitions WHERE service_id IS NOT NULL
                UNION ALL
                SELECT service_id, organisation_id FROM encaissements WHERE service_id IS NOT NULL
                UNION ALL
                SELECT service_id, organisation_id FROM sorties_fonds WHERE service_id IS NOT NULL
                UNION ALL
                SELECT sr.service_id, bp.organisation_id
                FROM service_rubriques sr
                JOIN budget_postes bp ON bp.id = sr.budget_poste_id
            ) t
            GROUP BY service_id
        ) src
        WHERE s.id = src.service_id;
        """
    )
    op.execute(
        """
        UPDATE services s
        SET organisation_id = u.organisation_id
        FROM users u
        WHERE s.organisation_id IS NULL
          AND s.responsable_id = u.id
          AND u.organisation_id IS NOT NULL;
        """
    )
    op.execute(
        """
        UPDATE services
        SET organisation_id = (SELECT min(id) FROM organisations)
        WHERE organisation_id IS NULL;
        """
    )

    op.alter_column("services", "organisation_id", nullable=False)

    op.drop_constraint("services_code_key", "services", type_="unique")
    op.drop_index("ix_services_code", table_name="services")
    op.create_unique_constraint("uq_services_org_code", "services", ["organisation_id", "code"])


def downgrade() -> None:
    op.drop_constraint("uq_services_org_code", "services", type_="unique")
    op.create_index("ix_services_code", "services", ["code"])
    op.create_unique_constraint("services_code_key", "services", ["code"])

    op.drop_constraint("fk_services_organisation_id", "services", type_="foreignkey")
    op.drop_index("ix_services_organisation_id", table_name="services")
    op.drop_column("services", "organisation_id")
