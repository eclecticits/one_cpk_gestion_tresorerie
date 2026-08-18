"""Indexes de performance : listage tenant + FK non indexees

Revision ID: 20260818_perf_indexes
Revises: 20260816_hr_agent_phase2
Create Date: 2026-08-18 00:00:00.000000

Ajoute uniquement des index (aucune colonne/table modifiee ou supprimee) pour
couvrir les requetes de listage les plus frequentes des endpoints
requisitions/encaissements/sorties_fonds/ordres_decaissement (filtre
organisation_id + tri par date par defaut) et des cles etrangeres non
indexees mais utilisees en JOIN/WHERE (payment_history.encaissement_id,
participants_transport.remboursement_id, budget_audit_logs.exercice_id /
budget_poste_id, encaissements.expert_comptable_id).

Ces index sont crees par CREATE INDEX classique (non CONCURRENTLY) car
l'environnement Alembic de ce projet (alembic/env.py) execute chaque
migration dans une transaction (context.begin_transaction()), incompatible
avec CONCURRENTLY. Sur une table volumineuse en production, prevoir une
fenetre de maintenance : CREATE INDEX pose un verrou SHARE qui bloque les
ecritures (INSERT/UPDATE/DELETE) sur la table le temps de la construction.
"""

from __future__ import annotations

from alembic import op


revision = "20260818_perf_indexes"
down_revision = "20260816_hr_agent_phase2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_requisitions_org_deleted_created",
        "requisitions",
        ["organisation_id", "is_deleted", "created_at"],
    )
    op.create_index(
        "ix_encaissements_org_deleted_date",
        "encaissements",
        ["organisation_id", "is_deleted", "date_encaissement"],
    )
    op.create_index(
        "ix_encaissements_expert_comptable_id",
        "encaissements",
        ["expert_comptable_id"],
    )
    op.create_index(
        "ix_sorties_fonds_org_date_paiement",
        "sorties_fonds",
        ["organisation_id", "date_paiement"],
    )
    op.create_index(
        "ix_ordres_decaissement_org_created",
        "ordres_decaissement",
        ["organisation_id", "created_at"],
    )
    op.create_index(
        "ix_payment_history_encaissement_created",
        "payment_history",
        ["encaissement_id", "created_at"],
    )
    op.create_index(
        "ix_participants_transport_remboursement_id",
        "participants_transport",
        ["remboursement_id"],
    )
    op.create_index(
        "ix_budget_audit_logs_org_exercice_created",
        "budget_audit_logs",
        ["organisation_id", "exercice_id", "created_at"],
    )
    op.create_index(
        "ix_budget_audit_logs_budget_poste_id",
        "budget_audit_logs",
        ["budget_poste_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_budget_audit_logs_budget_poste_id", table_name="budget_audit_logs")
    op.drop_index("ix_budget_audit_logs_org_exercice_created", table_name="budget_audit_logs")
    op.drop_index("ix_participants_transport_remboursement_id", table_name="participants_transport")
    op.drop_index("ix_payment_history_encaissement_created", table_name="payment_history")
    op.drop_index("ix_ordres_decaissement_org_created", table_name="ordres_decaissement")
    op.drop_index("ix_sorties_fonds_org_date_paiement", table_name="sorties_fonds")
    op.drop_index("ix_encaissements_expert_comptable_id", table_name="encaissements")
    op.drop_index("ix_encaissements_org_deleted_date", table_name="encaissements")
    op.drop_index("ix_requisitions_org_deleted_created", table_name="requisitions")
