"""Add organisations and tenant scoping.

Revision ID: 20260310_multi_tenant_orgs
Revises: 20260306_enc_mode_card
Create Date: 2026-03-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260310_multi_tenant_orgs"
down_revision = "20260306_enc_mode_card"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organisations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("uuid", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("nom", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("logo_url", sa.Text(), nullable=True),
        sa.Column("email_contact", sa.String(length=255), nullable=True),
        sa.Column("telephone", sa.String(length=50), nullable=True),
        sa.Column("adresse", sa.Text(), nullable=True),
        sa.Column("devise_preferee", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("taux_change_interne", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("plan_type", sa.String(length=50), nullable=False, server_default="FREE"),
        sa.Column("status_abonnement", sa.String(length=20), nullable=False, server_default="TRIAL"),
        sa.Column("date_expiration_abonnement", sa.DateTime(timezone=True), nullable=True),
        sa.Column("limite_utilisateurs", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("uuid"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_organisations_slug", "organisations", ["slug"])

    op.add_column("users", sa.Column("organisation_id", sa.Integer(), nullable=True))
    op.add_column("requisitions", sa.Column("organisation_id", sa.Integer(), nullable=True))
    op.add_column("encaissements", sa.Column("organisation_id", sa.Integer(), nullable=True))
    op.add_column("sorties_fonds", sa.Column("organisation_id", sa.Integer(), nullable=True))
    op.add_column("caisse_centrale", sa.Column("organisation_id", sa.Integer(), nullable=True))
    op.add_column("comptes_bancaires", sa.Column("organisation_id", sa.Integer(), nullable=True))
    op.add_column("print_settings", sa.Column("organisation_id", sa.Integer(), nullable=True))
    op.add_column("audit_logs", sa.Column("organisation_id", sa.Integer(), nullable=True))

    op.create_index("ix_users_organisation_id", "users", ["organisation_id"])
    op.create_index("ix_requisitions_organisation_id", "requisitions", ["organisation_id"])
    op.create_index("ix_encaissements_organisation_id", "encaissements", ["organisation_id"])
    op.create_index("ix_sorties_fonds_organisation_id", "sorties_fonds", ["organisation_id"])
    op.create_index("ix_caisse_centrale_organisation_id", "caisse_centrale", ["organisation_id"])
    op.create_index("ix_comptes_bancaires_organisation_id", "comptes_bancaires", ["organisation_id"])
    op.create_index("ix_print_settings_organisation_id", "print_settings", ["organisation_id"])
    op.create_index("ix_audit_logs_organisation_id", "audit_logs", ["organisation_id"])

    op.create_foreign_key(
        "fk_users_organisation_id",
        "users",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_requisitions_organisation_id",
        "requisitions",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_encaissements_organisation_id",
        "encaissements",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_sorties_fonds_organisation_id",
        "sorties_fonds",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_caisse_centrale_organisation_id",
        "caisse_centrale",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_comptes_bancaires_organisation_id",
        "comptes_bancaires",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_print_settings_organisation_id",
        "print_settings",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_audit_logs_organisation_id",
        "audit_logs",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute(
        """
        INSERT INTO organisations (id, uuid, nom, slug, plan_type, status_abonnement)
        VALUES (1, gen_random_uuid(), 'ONEC', 'onec', 'FREE', 'TRIAL')
        ON CONFLICT (id) DO NOTHING
        """
    )
    op.execute("SELECT setval('organisations_id_seq', (SELECT COALESCE(MAX(id), 1) FROM organisations))")

    for table in (
        "users",
        "requisitions",
        "encaissements",
        "sorties_fonds",
        "caisse_centrale",
        "comptes_bancaires",
        "print_settings",
    ):
        op.execute(f"UPDATE {table} SET organisation_id = 1 WHERE organisation_id IS NULL")

    op.alter_column("users", "organisation_id", nullable=False)
    op.alter_column("requisitions", "organisation_id", nullable=False)
    op.alter_column("encaissements", "organisation_id", nullable=False)
    op.alter_column("sorties_fonds", "organisation_id", nullable=False)
    op.alter_column("caisse_centrale", "organisation_id", nullable=False)
    op.alter_column("comptes_bancaires", "organisation_id", nullable=False)
    op.alter_column("print_settings", "organisation_id", nullable=False)


def downgrade() -> None:
    op.drop_constraint("fk_audit_logs_organisation_id", "audit_logs", type_="foreignkey")
    op.drop_constraint("fk_print_settings_organisation_id", "print_settings", type_="foreignkey")
    op.drop_constraint("fk_comptes_bancaires_organisation_id", "comptes_bancaires", type_="foreignkey")
    op.drop_constraint("fk_caisse_centrale_organisation_id", "caisse_centrale", type_="foreignkey")
    op.drop_constraint("fk_sorties_fonds_organisation_id", "sorties_fonds", type_="foreignkey")
    op.drop_constraint("fk_encaissements_organisation_id", "encaissements", type_="foreignkey")
    op.drop_constraint("fk_requisitions_organisation_id", "requisitions", type_="foreignkey")
    op.drop_constraint("fk_users_organisation_id", "users", type_="foreignkey")

    op.drop_index("ix_audit_logs_organisation_id", table_name="audit_logs")
    op.drop_index("ix_print_settings_organisation_id", table_name="print_settings")
    op.drop_index("ix_comptes_bancaires_organisation_id", table_name="comptes_bancaires")
    op.drop_index("ix_caisse_centrale_organisation_id", table_name="caisse_centrale")
    op.drop_index("ix_sorties_fonds_organisation_id", table_name="sorties_fonds")
    op.drop_index("ix_encaissements_organisation_id", table_name="encaissements")
    op.drop_index("ix_requisitions_organisation_id", table_name="requisitions")
    op.drop_index("ix_users_organisation_id", table_name="users")

    op.drop_column("audit_logs", "organisation_id")
    op.drop_column("print_settings", "organisation_id")
    op.drop_column("comptes_bancaires", "organisation_id")
    op.drop_column("caisse_centrale", "organisation_id")
    op.drop_column("sorties_fonds", "organisation_id")
    op.drop_column("encaissements", "organisation_id")
    op.drop_column("requisitions", "organisation_id")
    op.drop_column("users", "organisation_id")

    op.drop_index("ix_organisations_slug", table_name="organisations")
    op.drop_table("organisations")
