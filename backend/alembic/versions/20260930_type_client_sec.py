"""Type de client « sec » : la société d'expertise comptable à part

Revision ID: 20260930_type_client_sec
Revises: 20260929_fonds_tiers_multi

Une SEC est une personne morale inscrite au Tableau, pas un expert-comptable :
la ranger sous « expert_comptable » mêlait les deux dans les filtres et les
totaux par type de client. Elle garde le référentiel des experts
(expert_comptable_id), seul son type change.

Reclassement : les encaissements « expert_comptable » dont l'expert est une SEC
(type_ec = 'SEC') passent en « sec ».

Create Date: 2026-09-30
"""

from __future__ import annotations

from alembic import op


revision = "20260930_type_client_sec"
down_revision = "20260929_fonds_tiers_multi"
branch_labels = None
depends_on = None


TYPES = "('expert_comptable','sec','personne_physique','personne_morale','partenaire','autre')"
ANCIENS_TYPES = "('expert_comptable','personne_physique','personne_morale','partenaire','autre')"
TYPES_EXPERT = "('expert_comptable','sec')"


def _client_ref(types_expert: str) -> str:
    return (
        "(nature_mouvement = 'FONDS_DE_TIERS') OR "
        f"(type_client IN {types_expert} AND expert_comptable_id IS NOT NULL) OR "
        f"(type_client NOT IN {types_expert} AND client_nom IS NOT NULL AND length(trim(client_nom)) > 0)"
    )


def _poser_contraintes(types: str, types_expert: str) -> None:
    op.drop_constraint("ck_encaissements_type_client", "encaissements", type_="check")
    op.create_check_constraint("ck_encaissements_type_client", "encaissements", f"type_client IN {types}")
    op.drop_constraint("ck_encaissements_client_ref", "encaissements", type_="check")
    op.create_check_constraint("ck_encaissements_client_ref", "encaissements", _client_ref(types_expert))
    op.drop_constraint("ck_clients_type_client", "clients", type_="check")
    op.create_check_constraint(
        "ck_clients_type_client", "clients", f"type_client IS NULL OR type_client IN {types}"
    )


def upgrade() -> None:
    _poser_contraintes(TYPES, TYPES_EXPERT)
    op.execute(
        "UPDATE encaissements SET type_client = 'sec' "
        "WHERE type_client = 'expert_comptable' AND expert_comptable_id IN "
        "(SELECT id FROM experts_comptables WHERE type_ec = 'SEC')"
    )


def downgrade() -> None:
    op.execute("UPDATE encaissements SET type_client = 'expert_comptable' WHERE type_client = 'sec'")
    op.execute("UPDATE clients SET type_client = NULL WHERE type_client = 'sec'")
    _poser_contraintes(ANCIENS_TYPES, "('expert_comptable')")
