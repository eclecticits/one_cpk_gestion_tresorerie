"""Recettes à identifier : un versement reçu en banque dont le payeur est inconnu.

- nature `A_IDENTIFIER` (sans impact budgétaire) et ses statuts de suivi
  (`A_IDENTIFIER`, `PARTIELLEMENT_IDENTIFIE`, `IDENTIFIE`) ;
- une recette à identifier n'a pas de client : la contrainte de référence
  client l'admet, comme un fonds de tiers ;
- `payment_history.identification_source_id` : le versement d'une note tiré
  d'une recette à identifier, et le statut `TRANSFERE` du versement d'origine
  une fois entièrement déplacé ;
- compte 4718 « Recettes à identifier » dans les plans déjà provisionnés, que
  le mapping par défaut de la rubrique `RECETTE_A_IDENTIFIER` désigne ;
- droit `treso.encaissements.identifier`, accordé à l'administrateur, aux
  comptables (comptable, chef comptable) et au trésorier — pas au caissier,
  qui saisit sans reclasser.

Revision ID: 20261006_recettes_identifier
Revises: 20261004_nd_creance_lines
Create Date: 2026-10-06
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql


revision = "20261006_recettes_identifier"
down_revision = "20261004_nd_creance_lines"
branch_labels = None
depends_on = None


TYPES_EXPERT = "('expert_comptable','sec')"


def _nature_check(natures_hors_budget: str) -> str:
    return f"""
    (nature_mouvement IS NULL AND impact_budgetaire IS NULL)
    OR (nature_mouvement = 'BUDGETAIRE' AND impact_budgetaire IS TRUE)
    OR (nature_mouvement IN {natures_hors_budget} AND impact_budgetaire IS FALSE)
    """


def _statut_check(statuts: str) -> str:
    return f"hors_budget_status IS NULL OR hors_budget_status IN {statuts}"


def _client_ref(natures_sans_client: str) -> str:
    return (
        f"(nature_mouvement IN {natures_sans_client}) OR "
        f"(type_client IN {TYPES_EXPERT} AND expert_comptable_id IS NOT NULL) OR "
        f"(type_client NOT IN {TYPES_EXPERT} AND client_nom IS NOT NULL AND length(trim(client_nom)) > 0)"
    )


NATURES = "('HORS_BUDGET_A_REGULARISER','FONDS_DE_TIERS','TRANSFERT_INTERNE','A_IDENTIFIER')"
ANCIENNES_NATURES = "('HORS_BUDGET_A_REGULARISER','FONDS_DE_TIERS','TRANSFERT_INTERNE')"
STATUTS = (
    "('A_REGULARISER','PARTIELLEMENT_AFFECTE','AFFECTE_BUDGET','MAINTENU_HORS_BUDGET','ANNULE',"
    "'A_IDENTIFIER','PARTIELLEMENT_IDENTIFIE','IDENTIFIE')"
)
ANCIENS_STATUTS = "('A_REGULARISER','PARTIELLEMENT_AFFECTE','AFFECTE_BUDGET','MAINTENU_HORS_BUDGET','ANNULE')"


PERMISSION = "treso.encaissements.identifier"
DESCRIPTION = "Trésorerie — Encaissements : identifier une recette reçue en banque sans payeur connu"
ROLES = ("admin", "comptable", "chef_comptable", "tresorier")

SEMER_PERMISSION = """
    INSERT INTO permissions (code, description, created_at)
    VALUES (:code, :description, now())
    ON CONFLICT (code) DO UPDATE SET description = EXCLUDED.description
"""
ACCORDER = """
    INSERT INTO role_permissions (role_id, permission_id)
    SELECT r.id, p.id
    FROM roles r, permissions p
    WHERE r.code = :role AND p.code = :code
    ON CONFLICT DO NOTHING
"""

# Les plans provisionnés portent tous 4713 : c'est le repère d'un plan de
# démarrage. 4718 se range sous 47 quand le plan en a un (SYSCOHADA).
SEMER_COMPTE = """
    INSERT INTO compta_comptes (
        organisation_id, referentiel_id, numero, libelle, classe, parent_id,
        is_collectif, is_auxiliaire, nature, sens_normal, actif,
        analytique_obligatoire, lettrable, created_at, updated_at
    )
    SELECT c.organisation_id, c.referentiel_id, '4718', 'Recettes à identifier (compte d''attente)', '4',
           (SELECT p.id FROM compta_comptes p
             WHERE p.referentiel_id = c.referentiel_id AND p.numero = '47' LIMIT 1),
           false, false, 'PASSIF', 'CREDIT', true, false, true, now(), now()
    FROM compta_comptes c
    WHERE c.numero = '4713'
      AND NOT EXISTS (
          SELECT 1 FROM compta_comptes x
          WHERE x.referentiel_id = c.referentiel_id AND x.organisation_id = c.organisation_id AND x.numero = '4718'
      )
"""


def upgrade() -> None:
    op.drop_constraint("ck_encaissements_nature_impact", "encaissements", type_="check")
    op.create_check_constraint("ck_encaissements_nature_impact", "encaissements", _nature_check(NATURES))
    op.drop_constraint("ck_encaissements_hors_budget_status", "encaissements", type_="check")
    op.create_check_constraint("ck_encaissements_hors_budget_status", "encaissements", _statut_check(STATUTS))
    op.drop_constraint("ck_encaissements_client_ref", "encaissements", type_="check")
    op.create_check_constraint(
        "ck_encaissements_client_ref", "encaissements", _client_ref("('FONDS_DE_TIERS','A_IDENTIFIER')")
    )

    op.add_column(
        "payment_history",
        sa.Column(
            "identification_source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("encaissements.id", ondelete="RESTRICT", name="fk_payment_history_identification_source"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_payment_history_identification_source_id", "payment_history", ["identification_source_id"]
    )
    op.drop_constraint("ck_payment_history_statut", "payment_history", type_="check")
    op.create_check_constraint(
        "ck_payment_history_statut", "payment_history", "statut IN ('ACTIF','ANNULE','TRANSFERE')"
    )

    bind = op.get_bind()
    bind.execute(text(SEMER_COMPTE))
    bind.execute(text(SEMER_PERMISSION), {"code": PERMISSION, "description": DESCRIPTION})
    for role in ROLES:
        bind.execute(text(ACCORDER), {"role": role, "code": PERMISSION})


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code = :code)"),
        {"code": PERMISSION},
    )
    bind.execute(text("DELETE FROM permissions WHERE code = :code"), {"code": PERMISSION})
    # Le compte 4718 reste : des écritures peuvent le mouvementer.

    op.drop_constraint("ck_payment_history_statut", "payment_history", type_="check")
    op.create_check_constraint("ck_payment_history_statut", "payment_history", "statut IN ('ACTIF','ANNULE')")
    op.drop_index("ix_payment_history_identification_source_id", table_name="payment_history")
    op.drop_column("payment_history", "identification_source_id")

    op.drop_constraint("ck_encaissements_client_ref", "encaissements", type_="check")
    op.create_check_constraint("ck_encaissements_client_ref", "encaissements", _client_ref("('FONDS_DE_TIERS')"))
    op.drop_constraint("ck_encaissements_hors_budget_status", "encaissements", type_="check")
    op.create_check_constraint(
        "ck_encaissements_hors_budget_status", "encaissements", _statut_check(ANCIENS_STATUTS)
    )
    op.drop_constraint("ck_encaissements_nature_impact", "encaissements", type_="check")
    op.create_check_constraint("ck_encaissements_nature_impact", "encaissements", _nature_check(ANCIENNES_NATURES))
