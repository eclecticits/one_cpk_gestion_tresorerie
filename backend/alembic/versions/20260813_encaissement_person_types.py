"""allow physical and legal person encaissement clients

Revision ID: 20260813_enc_person_types
Revises: 20260811_payment_history_events
Create Date: 2026-08-13 14:30:00.000000
"""

from __future__ import annotations

from alembic import op


revision = "20260813_enc_person_types"
down_revision = "20260811_payment_history_events"
branch_labels = None
depends_on = None


UPGRADED_CHECK = (
    "type_client IN ("
    "'expert_comptable','personne_physique','personne_morale','client_externe',"
    "'banque_institution','partenaire','organisation','autre'"
    ")"
)

LEGACY_CHECK = (
    "type_client IN ("
    "'expert_comptable','client_externe','banque_institution','partenaire',"
    "'organisation','autre'"
    ")"
)


def upgrade() -> None:
    op.drop_constraint("ck_encaissements_type_client", "encaissements", type_="check")
    op.create_check_constraint(
        "ck_encaissements_type_client",
        "encaissements",
        UPGRADED_CHECK,
    )


def downgrade() -> None:
    op.drop_constraint("ck_encaissements_type_client", "encaissements", type_="check")
    op.create_check_constraint(
        "ck_encaissements_type_client",
        "encaissements",
        LEGACY_CHECK,
    )
