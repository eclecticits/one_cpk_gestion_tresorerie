"""add services module and service_id links

Revision ID: 20260220_services_module
Revises: 20260217_budget_postes
Create Date: 2026-02-20
"""

from alembic import op
import sqlalchemy as sa

revision = "20260220_services_module"
down_revision = "20260217_budget_postes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "services",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(length=20), nullable=False, unique=True),
        sa.Column("libelle", sa.String(length=150), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_index("ix_services_code", "services", ["code"])

    op.add_column("requisitions", sa.Column("service_id", sa.Integer(), nullable=True))
    op.add_column("encaissements", sa.Column("service_id", sa.Integer(), nullable=True))
    op.add_column("sorties_fonds", sa.Column("service_id", sa.Integer(), nullable=True))

    op.create_foreign_key("fk_requisitions_service_id", "requisitions", "services", ["service_id"], ["id"])
    op.create_foreign_key("fk_encaissements_service_id", "encaissements", "services", ["service_id"], ["id"])
    op.create_foreign_key("fk_sorties_fonds_service_id", "sorties_fonds", "services", ["service_id"], ["id"])

    op.create_index("ix_requisitions_service_id", "requisitions", ["service_id"])
    op.create_index("ix_encaissements_service_id", "encaissements", ["service_id"])
    op.create_index("ix_sorties_fonds_service_id", "sorties_fonds", ["service_id"])

    services_table = sa.table(
        "services",
        sa.column("code", sa.String),
        sa.column("libelle", sa.String),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(
        services_table,
        [
            {"code": "BUR", "libelle": "Bureau du Conseil Provincial", "is_active": True},
            {"code": "FORCO", "libelle": "Commission Formation Continue", "is_active": True},
            {"code": "STAG", "libelle": "Commission de Stage & Examens", "is_active": True},
            {"code": "OE", "libelle": "Commission Tableau & Organisation de l'Expertise", "is_active": True},
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_sorties_fonds_service_id", table_name="sorties_fonds")
    op.drop_index("ix_encaissements_service_id", table_name="encaissements")
    op.drop_index("ix_requisitions_service_id", table_name="requisitions")

    op.drop_constraint("fk_sorties_fonds_service_id", "sorties_fonds", type_="foreignkey")
    op.drop_constraint("fk_encaissements_service_id", "encaissements", type_="foreignkey")
    op.drop_constraint("fk_requisitions_service_id", "requisitions", type_="foreignkey")

    op.drop_column("sorties_fonds", "service_id")
    op.drop_column("encaissements", "service_id")
    op.drop_column("requisitions", "service_id")

    op.drop_index("ix_services_code", table_name="services")
    op.drop_table("services")
