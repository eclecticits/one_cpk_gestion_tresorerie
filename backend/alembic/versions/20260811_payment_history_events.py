"""payment history financial event snapshots

Revision ID: 20260811_payment_history_events
Revises: 20260808_req_date
Create Date: 2026-08-11 01:20:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260811_payment_history_events"
down_revision = "20260808_req_date"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("payment_history") as batch:
        batch.add_column(sa.Column("devise", sa.String(length=3), nullable=False, server_default="USD"))
        batch.add_column(sa.Column("canal", sa.String(length=20), nullable=False, server_default="CAISSE"))
        batch.add_column(sa.Column("compte_bancaire_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("budget_poste_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("taux_change_applique", sa.Numeric(18, 8), nullable=False, server_default="1"))
        batch.add_column(sa.Column("date_paiement", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
        batch.add_column(sa.Column("statut", sa.String(length=20), nullable=False, server_default="ACTIF"))
        batch.add_column(sa.Column("statut_comptabilisation", sa.String(length=40), nullable=False, server_default="NON_APPLICABLE"))
        batch.add_column(sa.Column("message_comptabilisation", sa.Text(), nullable=True))
        batch.add_column(sa.Column("annule_le", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("annule_par_id", postgresql.UUID(as_uuid=True), nullable=True))
        batch.add_column(sa.Column("motif_annulation", sa.Text(), nullable=True))
        batch.add_column(sa.Column("annulation_ip", sa.String(length=64), nullable=True))

    op.execute(
        """
        UPDATE payment_history ph
        SET
            devise = COALESCE(e.devise_perception, 'USD'),
            canal = COALESCE(e.canal, 'CAISSE'),
            compte_bancaire_id = e.compte_bancaire_id,
            budget_poste_id = e.budget_poste_id,
            taux_change_applique = COALESCE(e.taux_change_applique, 1),
            date_paiement = COALESCE(e.date_paiement, ph.created_at, now())
        FROM encaissements e
        WHERE e.id = ph.encaissement_id
        """
    )

    with op.batch_alter_table("payment_history") as batch:
        batch.create_check_constraint("ck_payment_history_devise", "devise IN ('USD','CDF')")
        batch.create_check_constraint("ck_payment_history_canal", "canal IN ('CAISSE','BANQUE')")
        batch.create_check_constraint("ck_payment_history_statut", "statut IN ('ACTIF','ANNULE')")
        batch.create_check_constraint(
            "ck_payment_history_statut_compta",
            "statut_comptabilisation IN ('NON_APPLICABLE','EN_ATTENTE','COMPTABILISE')",
        )

    op.create_index("ix_payment_history_statut", "payment_history", ["statut"])
    op.create_index("ix_payment_history_date_paiement", "payment_history", ["date_paiement"])


def downgrade() -> None:
    op.drop_index("ix_payment_history_date_paiement", table_name="payment_history")
    op.drop_index("ix_payment_history_statut", table_name="payment_history")
    with op.batch_alter_table("payment_history") as batch:
        batch.drop_constraint("ck_payment_history_statut_compta", type_="check")
        batch.drop_constraint("ck_payment_history_statut", type_="check")
        batch.drop_constraint("ck_payment_history_canal", type_="check")
        batch.drop_constraint("ck_payment_history_devise", type_="check")
        batch.drop_column("annulation_ip")
        batch.drop_column("motif_annulation")
        batch.drop_column("annule_par_id")
        batch.drop_column("annule_le")
        batch.drop_column("message_comptabilisation")
        batch.drop_column("statut_comptabilisation")
        batch.drop_column("statut")
        batch.drop_column("date_paiement")
        batch.drop_column("taux_change_applique")
        batch.drop_column("budget_poste_id")
        batch.drop_column("compte_bancaire_id")
        batch.drop_column("canal")
        batch.drop_column("devise")
