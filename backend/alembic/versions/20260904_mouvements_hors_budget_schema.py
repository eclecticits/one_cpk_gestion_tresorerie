"""Schema safe pour mouvements hors budget et fonds de tiers.

Phase A uniquement :
- ajoute les colonnes de classification sans reclasser l'historique ;
- crée les tables de suivi et d'imputation avec foreign keys réelles ;
- ajoute une contrainte de cohérence nature/impact pour les lignes renseignées.

Le backfill historique et le passage en NOT NULL appartiennent à une phase
séparée, après preflight validé.

Revision ID: 20260904_hors_budget_schema
Revises: 20260903_validateur_dash
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260904_hors_budget_schema"
down_revision = "20260903_validateur_dash"
branch_labels = None
depends_on = None


NATURE_CHECK = """
(
    nature_mouvement IS NULL
    AND impact_budgetaire IS NULL
)
OR (
    nature_mouvement = 'BUDGETAIRE'
    AND impact_budgetaire IS TRUE
)
OR (
    nature_mouvement IN ('HORS_BUDGET_A_REGULARISER','FONDS_DE_TIERS','TRANSFERT_INTERNE')
    AND impact_budgetaire IS FALSE
)
"""


def upgrade() -> None:
    op.add_column("encaissements", sa.Column("nature_mouvement", sa.String(length=40), nullable=True))
    op.add_column("encaissements", sa.Column("impact_budgetaire", sa.Boolean(), nullable=True))
    op.add_column("encaissements", sa.Column("hors_budget_status", sa.String(length=40), nullable=True))
    op.create_index("ix_encaissements_nature_mouvement", "encaissements", ["nature_mouvement"])
    op.create_index("ix_encaissements_impact_budgetaire", "encaissements", ["impact_budgetaire"])
    op.create_index("ix_encaissements_hors_budget_status", "encaissements", ["hors_budget_status"])
    op.create_check_constraint("ck_encaissements_nature_impact", "encaissements", NATURE_CHECK)
    op.create_check_constraint(
        "ck_encaissements_hors_budget_status",
        "encaissements",
        """
        hors_budget_status IS NULL
        OR hors_budget_status IN ('A_REGULARISER','PARTIELLEMENT_AFFECTE','AFFECTE_BUDGET','MAINTENU_HORS_BUDGET','ANNULE')
        """,
    )

    op.add_column("sorties_fonds", sa.Column("nature_mouvement", sa.String(length=40), nullable=True))
    op.add_column("sorties_fonds", sa.Column("impact_budgetaire", sa.Boolean(), nullable=True))
    op.add_column("sorties_fonds", sa.Column("hors_budget_status", sa.String(length=40), nullable=True))
    op.create_index("ix_sorties_fonds_nature_mouvement", "sorties_fonds", ["nature_mouvement"])
    op.create_index("ix_sorties_fonds_impact_budgetaire", "sorties_fonds", ["impact_budgetaire"])
    op.create_index("ix_sorties_fonds_hors_budget_status", "sorties_fonds", ["hors_budget_status"])
    op.create_check_constraint("ck_sorties_fonds_nature_impact", "sorties_fonds", NATURE_CHECK)
    op.create_check_constraint(
        "ck_sorties_fonds_hors_budget_status",
        "sorties_fonds",
        """
        hors_budget_status IS NULL
        OR hors_budget_status IN ('A_REGULARISER','PARTIELLEMENT_AFFECTE','AFFECTE_BUDGET','MAINTENU_HORS_BUDGET','ANNULE')
        """,
    )

    op.create_table(
        "fonds_tiers_operations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("encaissement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("statut", sa.String(length=40), nullable=False),
        sa.Column("tiers_concerne", sa.String(length=255), nullable=False),
        sa.Column("payeur_origine", sa.String(length=255), nullable=True),
        sa.Column("beneficiaire_reel", sa.String(length=255), nullable=True),
        sa.Column("motif", sa.Text(), nullable=True),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column("piece_justificative", sa.String(length=200), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("annulee_le", sa.DateTime(timezone=True), nullable=True),
        sa.Column("annulee_par_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("motif_annulation", sa.Text(), nullable=True),
        sa.CheckConstraint("statut IN ('OUVERT','PARTIELLEMENT_REMBOURSE','REGULARISE','ANNULE')", name="ck_fonds_tiers_statut"),
        sa.ForeignKeyConstraint(["encaissement_id"], ["encaissements.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "encaissement_id", name="uq_fonds_tiers_org_encaissement"),
    )
    op.create_index("ix_fonds_tiers_operations_organisation_id", "fonds_tiers_operations", ["organisation_id"])
    op.create_index("ix_fonds_tiers_operations_encaissement_id", "fonds_tiers_operations", ["encaissement_id"])
    op.create_index("ix_fonds_tiers_operations_statut", "fonds_tiers_operations", ["statut"])
    op.create_index("ix_fonds_tiers_org_statut", "fonds_tiers_operations", ["organisation_id", "statut"])

    op.add_column("sorties_fonds", sa.Column("fonds_tiers_operation_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_sorties_fonds_fonds_tiers_operation_id", "sorties_fonds", ["fonds_tiers_operation_id"])
    op.create_foreign_key(
        "fk_sorties_fonds_fonds_tiers_operation_id",
        "sorties_fonds",
        "fonds_tiers_operations",
        ["fonds_tiers_operation_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "mouvement_budget_imputations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("encaissement_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payment_history_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sortie_fonds_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("retour_caisse_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("budget_poste_id", sa.Integer(), nullable=False),
        sa.Column("sens", sa.String(length=30), nullable=False),
        sa.Column("montant_mouvement", sa.Numeric(14, 2), nullable=False),
        sa.Column("devise_mouvement", sa.String(length=3), nullable=False),
        sa.Column("montant_budget", sa.Numeric(14, 2), nullable=False),
        sa.Column("exchange_rate_snapshot", sa.Numeric(12, 4), nullable=True),
        sa.Column("statut", sa.String(length=20), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("annulee_le", sa.DateTime(timezone=True), nullable=True),
        sa.Column("annulee_par_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(
            "(encaissement_id IS NOT NULL)::int + (payment_history_id IS NOT NULL)::int + (sortie_fonds_id IS NOT NULL)::int + (retour_caisse_id IS NOT NULL)::int = 1",
            name="ck_mbi_exactly_one_source",
        ),
        sa.CheckConstraint("sens IN ('RECETTE_REALISEE','DEPENSE_PAYEE','RETOUR_DEPENSE')", name="ck_mbi_sens"),
        sa.CheckConstraint("statut IN ('ACTIVE','ANNULEE')", name="ck_mbi_statut"),
        sa.CheckConstraint("devise_mouvement IN ('USD','CDF')", name="ck_mbi_devise"),
        sa.CheckConstraint("montant_mouvement > 0", name="ck_mbi_montant_mouvement_positif"),
        sa.CheckConstraint("montant_budget >= 0", name="ck_mbi_montant_budget_nonneg"),
        sa.ForeignKeyConstraint(["budget_poste_id"], ["budget_postes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["encaissement_id"], ["encaissements.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["payment_history_id"], ["payment_history.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["retour_caisse_id"], ["retours_caisse.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sortie_fonds_id"], ["sorties_fonds.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mbi_org_poste_statut", "mouvement_budget_imputations", ["organisation_id", "budget_poste_id", "statut"])
    op.create_index("ix_mbi_encaissement", "mouvement_budget_imputations", ["encaissement_id"])
    op.create_index("ix_mbi_payment_history", "mouvement_budget_imputations", ["payment_history_id"])
    op.create_index("ix_mbi_sortie", "mouvement_budget_imputations", ["sortie_fonds_id"])
    op.create_index("ix_mbi_retour", "mouvement_budget_imputations", ["retour_caisse_id"])

    op.create_table(
        "regularisations_budgetaires",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("encaissement_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sortie_fonds_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ancien_nature_mouvement", sa.String(length=40), nullable=False),
        sa.Column("nouveau_nature_mouvement", sa.String(length=40), nullable=False),
        sa.Column("montant_mouvement", sa.Numeric(14, 2), nullable=False),
        sa.Column("devise_mouvement", sa.String(length=3), nullable=False),
        sa.Column("montant_budget", sa.Numeric(14, 2), nullable=False),
        sa.Column("exchange_rate_snapshot", sa.Numeric(12, 4), nullable=True),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("(encaissement_id IS NOT NULL)::int + (sortie_fonds_id IS NOT NULL)::int = 1", name="ck_reg_budget_exactly_one_source"),
        sa.CheckConstraint("devise_mouvement IN ('USD','CDF')", name="ck_reg_budget_devise"),
        sa.CheckConstraint("montant_mouvement > 0", name="ck_reg_budget_montant_mouvement_positif"),
        sa.CheckConstraint("montant_budget >= 0", name="ck_reg_budget_montant_budget_nonneg"),
        sa.ForeignKeyConstraint(["encaissement_id"], ["encaissements.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sortie_fonds_id"], ["sorties_fonds.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "idempotency_key", name="uq_reg_budget_org_idempotency"),
    )
    op.create_index("ix_reg_budget_encaissement", "regularisations_budgetaires", ["encaissement_id"])
    op.create_index("ix_reg_budget_sortie", "regularisations_budgetaires", ["sortie_fonds_id"])
    op.create_index("ix_reg_budget_org_created", "regularisations_budgetaires", ["organisation_id", "created_at"])

    op.add_column("mouvement_budget_imputations", sa.Column("regularisation_budgetaire_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_mouvement_budget_imputations_regularisation_budgetaire_id", "mouvement_budget_imputations", ["regularisation_budgetaire_id"])
    op.create_foreign_key(
        "fk_mbi_regularisation_budgetaire_id",
        "mouvement_budget_imputations",
        "regularisations_budgetaires",
        ["regularisation_budgetaire_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_mbi_regularisation_budgetaire_id", "mouvement_budget_imputations", type_="foreignkey")
    op.drop_index("ix_mouvement_budget_imputations_regularisation_budgetaire_id", table_name="mouvement_budget_imputations")
    op.drop_column("mouvement_budget_imputations", "regularisation_budgetaire_id")

    op.drop_index("ix_reg_budget_org_created", table_name="regularisations_budgetaires")
    op.drop_index("ix_reg_budget_sortie", table_name="regularisations_budgetaires")
    op.drop_index("ix_reg_budget_encaissement", table_name="regularisations_budgetaires")
    op.drop_table("regularisations_budgetaires")

    op.drop_index("ix_mbi_retour", table_name="mouvement_budget_imputations")
    op.drop_index("ix_mbi_sortie", table_name="mouvement_budget_imputations")
    op.drop_index("ix_mbi_payment_history", table_name="mouvement_budget_imputations")
    op.drop_index("ix_mbi_encaissement", table_name="mouvement_budget_imputations")
    op.drop_index("ix_mbi_org_poste_statut", table_name="mouvement_budget_imputations")
    op.drop_table("mouvement_budget_imputations")

    op.drop_constraint("fk_sorties_fonds_fonds_tiers_operation_id", "sorties_fonds", type_="foreignkey")
    op.drop_index("ix_sorties_fonds_fonds_tiers_operation_id", table_name="sorties_fonds")
    op.drop_column("sorties_fonds", "fonds_tiers_operation_id")

    op.drop_index("ix_fonds_tiers_org_statut", table_name="fonds_tiers_operations")
    op.drop_index("ix_fonds_tiers_operations_statut", table_name="fonds_tiers_operations")
    op.drop_index("ix_fonds_tiers_operations_encaissement_id", table_name="fonds_tiers_operations")
    op.drop_index("ix_fonds_tiers_operations_organisation_id", table_name="fonds_tiers_operations")
    op.drop_table("fonds_tiers_operations")

    op.drop_constraint("ck_sorties_fonds_hors_budget_status", "sorties_fonds", type_="check")
    op.drop_constraint("ck_sorties_fonds_nature_impact", "sorties_fonds", type_="check")
    op.drop_index("ix_sorties_fonds_hors_budget_status", table_name="sorties_fonds")
    op.drop_index("ix_sorties_fonds_impact_budgetaire", table_name="sorties_fonds")
    op.drop_index("ix_sorties_fonds_nature_mouvement", table_name="sorties_fonds")
    op.drop_column("sorties_fonds", "hors_budget_status")
    op.drop_column("sorties_fonds", "impact_budgetaire")
    op.drop_column("sorties_fonds", "nature_mouvement")

    op.drop_constraint("ck_encaissements_hors_budget_status", "encaissements", type_="check")
    op.drop_constraint("ck_encaissements_nature_impact", "encaissements", type_="check")
    op.drop_index("ix_encaissements_hors_budget_status", table_name="encaissements")
    op.drop_index("ix_encaissements_impact_budgetaire", table_name="encaissements")
    op.drop_index("ix_encaissements_nature_mouvement", table_name="encaissements")
    op.drop_column("encaissements", "hors_budget_status")
    op.drop_column("encaissements", "impact_budgetaire")
    op.drop_column("encaissements", "nature_mouvement")
