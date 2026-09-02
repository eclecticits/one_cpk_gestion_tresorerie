"""add requisition source fields for fund outflows

Revision ID: 20260908_req_sources
Revises: 20260907_ft_client_optional
"""

from alembic import op
import sqlalchemy as sa


revision = "20260908_req_sources"
down_revision = "20260907_ft_client_optional"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "requisitions",
        sa.Column(
            "nature_requisition",
            sa.String(length=30),
            nullable=False,
            server_default="BUDGETAIRE",
        ),
    )
    op.add_column("requisitions", sa.Column("beneficiaire", sa.String(length=200), nullable=True))
    op.add_column(
        "requisitions",
        sa.Column("tiers_organisation_id", sa.Integer(), nullable=True),
    )
    op.add_column("requisitions", sa.Column("tiers_nom_libre", sa.String(length=255), nullable=True))
    op.create_foreign_key(
        "fk_requisitions_tiers_organisation",
        "requisitions",
        "organisations",
        ["tiers_organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_requisitions_nature",
        "requisitions",
        "nature_requisition IN ('BUDGETAIRE','HORS_BUDGET','FONDS_DE_TIERS')",
    )
    op.create_check_constraint(
        "ck_requisitions_fonds_tiers_identity",
        "requisitions",
        """
        nature_requisition <> 'FONDS_DE_TIERS'
        OR (
            (tiers_organisation_id IS NOT NULL AND tiers_nom_libre IS NULL)
            OR (
                tiers_organisation_id IS NULL
                AND tiers_nom_libre IS NOT NULL
                AND length(trim(tiers_nom_libre)) > 0
            )
        )
        """,
    )
    op.create_index("ix_requisitions_org_nature_status", "requisitions", ["organisation_id", "nature_requisition", "status"])
    # La clé étrangère est en RESTRICT : sans index, toute suppression d'une
    # organisation impose un scan complet de `requisitions` pour la vérifier.
    op.create_index("ix_requisitions_tiers_organisation_id", "requisitions", ["tiers_organisation_id"])

    op.add_column(
        "ordres_decaissement",
        sa.Column("montant_usd_snapshot", sa.Numeric(14, 2), nullable=True),
    )
    # Backfill : le contrôle anti-fractionnement somme ce champ sur 24h. Sans
    # reprise, les ordres directs déjà en base comptent pour zéro et le plafond
    # de 100 USD se contourne en s'appuyant sur eux. Seul l'USD est repris : le
    # CDF demanderait le taux en vigueur au moment de l'ordre, que l'on n'a pas.
    op.execute(
        """
        UPDATE ordres_decaissement
        SET montant_usd_snapshot = montant
        WHERE requisition_id IS NULL
          AND montant_usd_snapshot IS NULL
          AND upper(devise) = 'USD'
        """
    )


def downgrade() -> None:
    op.drop_column("ordres_decaissement", "montant_usd_snapshot")
    op.drop_index("ix_requisitions_tiers_organisation_id", table_name="requisitions")
    op.drop_index("ix_requisitions_org_nature_status", table_name="requisitions")
    op.drop_constraint("ck_requisitions_fonds_tiers_identity", "requisitions", type_="check")
    op.drop_constraint("ck_requisitions_nature", "requisitions", type_="check")
    op.drop_constraint("fk_requisitions_tiers_organisation", "requisitions", type_="foreignkey")
    op.drop_column("requisitions", "tiers_nom_libre")
    op.drop_column("requisitions", "tiers_organisation_id")
    op.drop_column("requisitions", "beneficiaire")
    op.drop_column("requisitions", "nature_requisition")
