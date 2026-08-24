"""Facturation SaaS émise : factures créées avant paiement, réglées en ligne ou manuellement.

Jusqu'ici une `saas_invoices` naissait *après coup*, à la réception d'un paiement
en ligne réussi : elle valait reçu, jamais demande de paiement. Son `status`
était donc toujours "PAID" et sa colonne `transaction_id` toujours renseignée.

Cette révision ouvre le cas inverse — l'éditeur émet la facture, le tenant la
règle ensuite — sans rien casser de l'existant :

* `status` accueille désormais DRAFT / ISSUED / PAID / CANCELLED. Les lignes
  déjà en base restent "PAID" et gardent exactement le même sens.
* `line_items` porte le détail facturé (désignation, quantité, prix unitaire).
  Les factures historiques n'en ont pas : le PDF retombe alors sur le libellé
  d'abonnement, comme avant.
* `issuer_snapshot` fige l'identité de l'émetteur au moment de l'émission. Une
  facture est une pièce comptable : elle ne doit pas changer d'en-tête parce que
  l'adresse de la société a été modifiée six mois plus tard.
* `payment_method` / `payment_reference` / `paid_by_user_id` tracent un
  règlement manuel (virement, mobile money, espèces) — qui l'a constaté, sur
  quelle référence.

Aucune donnée n'est réécrite, toutes les colonnes sont nullable : la révision
est rejouable et réversible sans perte pour les factures déjà émises.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260823_saas_invoicing"
down_revision = "20260822_treso_actions"
branch_labels = None
depends_on = None


NEW_COLUMNS = (
    ("due_date", sa.Column("due_date", sa.DateTime(timezone=True), nullable=True)),
    ("line_items", sa.Column("line_items", postgresql.JSONB(astext_type=sa.Text()), nullable=True)),
    ("issuer_snapshot", sa.Column("issuer_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True)),
    ("payment_method", sa.Column("payment_method", sa.String(length=30), nullable=True)),
    ("payment_reference", sa.Column("payment_reference", sa.String(length=160), nullable=True)),
    ("paid_by_user_id", sa.Column("paid_by_user_id", postgresql.UUID(as_uuid=True), nullable=True)),
    ("cancelled_at", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True)),
    ("cancel_reason", sa.Column("cancel_reason", sa.Text(), nullable=True)),
    ("notes", sa.Column("notes", sa.Text(), nullable=True)),
)


def _existing_columns(bind) -> set[str]:
    inspector = sa.inspect(bind)
    return {col["name"] for col in inspector.get_columns("saas_invoices")}


def _existing_indexes(bind) -> set[str]:
    inspector = sa.inspect(bind)
    return {idx["name"] for idx in inspector.get_indexes("saas_invoices")}


def upgrade() -> None:
    bind = op.get_bind()
    present = _existing_columns(bind)
    for name, column in NEW_COLUMNS:
        if name not in present:
            op.add_column("saas_invoices", column)

    # La console liste les factures par statut puis par échéance : sans cet
    # index, l'écran « Factures » balaie toute la table à chaque filtre.
    if "ix_saas_invoices_status_due" not in _existing_indexes(bind):
        op.create_index(
            "ix_saas_invoices_status_due",
            "saas_invoices",
            ["status", "due_date"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "ix_saas_invoices_status_due" in _existing_indexes(bind):
        op.drop_index("ix_saas_invoices_status_due", table_name="saas_invoices")

    present = _existing_columns(bind)
    for name, _column in reversed(NEW_COLUMNS):
        if name in present:
            op.drop_column("saas_invoices", name)
