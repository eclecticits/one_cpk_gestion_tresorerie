"""Add organisation scoping to budgets and payments.

Revision ID: 20260312_budget_payments_tenant
Revises: 20260311_reconciliation_fields
Create Date: 2026-03-12 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260312_budget_payments_tenant"
down_revision = "20260311_reconciliation_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("budget_exercices", sa.Column("organisation_id", sa.Integer(), nullable=True))
    op.add_column("budget_postes", sa.Column("organisation_id", sa.Integer(), nullable=True))
    op.add_column("budget_audit_logs", sa.Column("organisation_id", sa.Integer(), nullable=True))
    op.add_column("payment_transactions", sa.Column("organisation_id", sa.Integer(), nullable=True))
    op.add_column("payment_history", sa.Column("organisation_id", sa.Integer(), nullable=True))

    op.create_index("ix_budget_exercices_organisation_id", "budget_exercices", ["organisation_id"])
    op.create_index("ix_budget_postes_organisation_id", "budget_postes", ["organisation_id"])
    op.create_index("ix_budget_audit_logs_organisation_id", "budget_audit_logs", ["organisation_id"])
    op.create_index("ix_payment_transactions_organisation_id", "payment_transactions", ["organisation_id"])
    op.create_index("ix_payment_history_organisation_id", "payment_history", ["organisation_id"])

    op.create_foreign_key(
        "fk_budget_exercices_organisation_id",
        "budget_exercices",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_budget_postes_organisation_id",
        "budget_postes",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_budget_audit_logs_organisation_id",
        "budget_audit_logs",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_payment_transactions_organisation_id",
        "payment_transactions",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_payment_history_organisation_id",
        "payment_history",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.execute("UPDATE budget_exercices SET organisation_id = 1 WHERE organisation_id IS NULL")
    op.execute(
        """
        UPDATE budget_postes bp
        SET organisation_id = be.organisation_id
        FROM budget_exercices be
        WHERE bp.exercice_id = be.id AND bp.organisation_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE budget_audit_logs bal
        SET organisation_id = bp.organisation_id
        FROM budget_postes bp
        WHERE bal.budget_poste_id = bp.id AND bal.organisation_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE budget_audit_logs bal
        SET organisation_id = be.organisation_id
        FROM budget_exercices be
        WHERE bal.exercice_id = be.id AND bal.organisation_id IS NULL
        """
    )
    op.execute("UPDATE budget_audit_logs SET organisation_id = 1 WHERE organisation_id IS NULL")

    op.execute(
        """
        UPDATE payment_transactions pt
        SET organisation_id = e.organisation_id
        FROM encaissements e
        WHERE pt.encaissement_id = e.id AND pt.organisation_id IS NULL
        """
    )
    op.execute("UPDATE payment_transactions SET organisation_id = 1 WHERE organisation_id IS NULL")
    op.execute(
        """
        UPDATE payment_history ph
        SET organisation_id = e.organisation_id
        FROM encaissements e
        WHERE ph.encaissement_id = e.id AND ph.organisation_id IS NULL
        """
    )
    op.execute("UPDATE payment_history SET organisation_id = 1 WHERE organisation_id IS NULL")

    op.drop_constraint("uq_budget_exercices_annee", "budget_exercices", type_="unique")
    op.create_unique_constraint(
        "uq_budget_exercices_org_annee",
        "budget_exercices",
        ["organisation_id", "annee"],
    )

    op.alter_column("budget_exercices", "organisation_id", nullable=False)
    op.alter_column("budget_postes", "organisation_id", nullable=False)
    op.alter_column("budget_audit_logs", "organisation_id", nullable=False)
    op.alter_column("payment_transactions", "organisation_id", nullable=False)
    op.alter_column("payment_history", "organisation_id", nullable=False)


def downgrade() -> None:
    op.drop_constraint("fk_payment_history_organisation_id", "payment_history", type_="foreignkey")
    op.drop_constraint("fk_payment_transactions_organisation_id", "payment_transactions", type_="foreignkey")
    op.drop_constraint("fk_budget_audit_logs_organisation_id", "budget_audit_logs", type_="foreignkey")
    op.drop_constraint("fk_budget_postes_organisation_id", "budget_postes", type_="foreignkey")
    op.drop_constraint("fk_budget_exercices_organisation_id", "budget_exercices", type_="foreignkey")

    op.drop_index("ix_payment_history_organisation_id", table_name="payment_history")
    op.drop_index("ix_payment_transactions_organisation_id", table_name="payment_transactions")
    op.drop_index("ix_budget_audit_logs_organisation_id", table_name="budget_audit_logs")
    op.drop_index("ix_budget_postes_organisation_id", table_name="budget_postes")
    op.drop_index("ix_budget_exercices_organisation_id", table_name="budget_exercices")

    op.drop_constraint("uq_budget_exercices_org_annee", "budget_exercices", type_="unique")
    op.create_unique_constraint("uq_budget_exercices_annee", "budget_exercices", ["annee"])

    op.drop_column("payment_history", "organisation_id")
    op.drop_column("payment_transactions", "organisation_id")
    op.drop_column("budget_audit_logs", "organisation_id")
    op.drop_column("budget_postes", "organisation_id")
    op.drop_column("budget_exercices", "organisation_id")
