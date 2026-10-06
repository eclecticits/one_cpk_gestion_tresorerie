"""Rembourser une recette à identifier par réquisition puis sortie de fonds.

- réquisition de nature `RECETTE_A_IDENTIFIER`, qui désigne la recette
  (`recette_a_identifier_id`) et en réserve le montant pendant son circuit ;
- sortie de fonds de nature `A_IDENTIFIER`, qui la rembourse
  (`sorties_fonds.recette_a_identifier_id`) ;
- statut `REMBOURSEE` d'une recette entièrement rendue sans rien identifier.

Revision ID: 20261006_remb_recette_ident
Revises: 20261006_recettes_identifier
Create Date: 2026-10-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261006_remb_recette_ident"
down_revision = "20261006_recettes_identifier"
branch_labels = None
depends_on = None


def _nature_check(natures_hors_budget: str) -> str:
    return f"""
    (nature_mouvement IS NULL AND impact_budgetaire IS NULL)
    OR (nature_mouvement = 'BUDGETAIRE' AND impact_budgetaire IS TRUE)
    OR (nature_mouvement IN {natures_hors_budget} AND impact_budgetaire IS FALSE)
    """


NATURES_SORTIE = "('HORS_BUDGET_A_REGULARISER','FONDS_DE_TIERS','TRANSFERT_INTERNE','A_IDENTIFIER')"
ANCIENNES_NATURES_SORTIE = "('HORS_BUDGET_A_REGULARISER','FONDS_DE_TIERS','TRANSFERT_INTERNE')"

NATURES_REQUISITION = "('BUDGETAIRE','HORS_BUDGET','FONDS_DE_TIERS','RECETTE_A_IDENTIFIER')"
ANCIENNES_NATURES_REQUISITION = "('BUDGETAIRE','HORS_BUDGET','FONDS_DE_TIERS')"

STATUTS_ENCAISSEMENT = (
    "('A_REGULARISER','PARTIELLEMENT_AFFECTE','AFFECTE_BUDGET','MAINTENU_HORS_BUDGET','ANNULE',"
    "'A_IDENTIFIER','PARTIELLEMENT_IDENTIFIE','IDENTIFIE','REMBOURSEE')"
)
ANCIENS_STATUTS_ENCAISSEMENT = (
    "('A_REGULARISER','PARTIELLEMENT_AFFECTE','AFFECTE_BUDGET','MAINTENU_HORS_BUDGET','ANNULE',"
    "'A_IDENTIFIER','PARTIELLEMENT_IDENTIFIE','IDENTIFIE')"
)


def _colonne_recette(table: str) -> None:
    op.add_column(
        table,
        sa.Column(
            "recette_a_identifier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("encaissements.id", ondelete="RESTRICT", name=f"fk_{table}_recette_a_identifier"),
            nullable=True,
        ),
    )
    op.create_index(f"ix_{table}_recette_a_identifier_id", table, ["recette_a_identifier_id"])


def upgrade() -> None:
    _colonne_recette("requisitions")
    _colonne_recette("sorties_fonds")

    op.drop_constraint("ck_requisitions_nature", "requisitions", type_="check")
    op.create_check_constraint(
        "ck_requisitions_nature", "requisitions", f"nature_requisition IN {NATURES_REQUISITION}"
    )
    op.create_check_constraint(
        "ck_requisitions_recette_a_identifier",
        "requisitions",
        "nature_requisition <> 'RECETTE_A_IDENTIFIER' OR recette_a_identifier_id IS NOT NULL",
    )

    op.drop_constraint("ck_sorties_fonds_nature_impact", "sorties_fonds", type_="check")
    op.create_check_constraint("ck_sorties_fonds_nature_impact", "sorties_fonds", _nature_check(NATURES_SORTIE))

    op.drop_constraint("ck_encaissements_hors_budget_status", "encaissements", type_="check")
    op.create_check_constraint(
        "ck_encaissements_hors_budget_status",
        "encaissements",
        f"hors_budget_status IS NULL OR hors_budget_status IN {STATUTS_ENCAISSEMENT}",
    )


def downgrade() -> None:
    op.drop_constraint("ck_encaissements_hors_budget_status", "encaissements", type_="check")
    op.create_check_constraint(
        "ck_encaissements_hors_budget_status",
        "encaissements",
        f"hors_budget_status IS NULL OR hors_budget_status IN {ANCIENS_STATUTS_ENCAISSEMENT}",
    )
    op.drop_constraint("ck_sorties_fonds_nature_impact", "sorties_fonds", type_="check")
    op.create_check_constraint(
        "ck_sorties_fonds_nature_impact", "sorties_fonds", _nature_check(ANCIENNES_NATURES_SORTIE)
    )
    op.drop_constraint("ck_requisitions_recette_a_identifier", "requisitions", type_="check")
    op.drop_constraint("ck_requisitions_nature", "requisitions", type_="check")
    op.create_check_constraint(
        "ck_requisitions_nature", "requisitions", f"nature_requisition IN {ANCIENNES_NATURES_REQUISITION}"
    )
    for table in ("sorties_fonds", "requisitions"):
        op.drop_index(f"ix_{table}_recette_a_identifier_id", table_name=table)
        op.drop_column(table, "recette_a_identifier_id")
