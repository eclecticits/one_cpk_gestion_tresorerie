"""Add system events and SaaS metrics view.

Revision ID: 20260310_saas_metrics
Revises: 20260310_merge_tenant_heads
Create Date: 2026-03-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260310_saas_metrics"
down_revision = "20260310_merge_tenant_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organisation_id", sa.Integer(), nullable=True),
        sa.Column("level", sa.String(length=20), nullable=False, server_default="info"),
        sa.Column("code", sa.String(length=60), nullable=False, server_default=""),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_system_events_organisation_id", "system_events", ["organisation_id"])
    op.create_index("ix_system_events_created_at", "system_events", ["created_at"])

    op.execute(
        """
        CREATE MATERIALIZED VIEW saas_platform_metrics AS
        SELECT
            o.id AS org_id,
            o.nom AS org_nom,
            o.slug AS slug,
            o.plan_type AS plan_type,
            o.status_abonnement AS status_abonnement,
            o.date_expiration_abonnement AS date_expiration_abonnement,
            (SELECT COUNT(*) FROM users u WHERE u.organisation_id = o.id) AS total_users,
            COALESCE(
                SUM(e.montant_paye) FILTER (WHERE e.created_at > NOW() - INTERVAL '30 days'),
                0
            ) AS volume_encaisse_30j,
            (
                SELECT COUNT(*)
                FROM payment_transactions pt
                JOIN encaissements ee ON ee.id = pt.encaissement_id
                WHERE ee.organisation_id = o.id
                  AND pt.status = 'FAILED'
                  AND pt.created_at > NOW() - INTERVAL '24 hours'
            ) AS echecs_paiement_24h,
            MAX(e.created_at) AS derniere_activite
        FROM organisations o
        LEFT JOIN encaissements e ON o.id = e.organisation_id
        GROUP BY o.id
        """
    )
    op.execute("CREATE UNIQUE INDEX idx_saas_platform_metrics_org_id ON saas_platform_metrics(org_id)")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS saas_platform_metrics")
    op.drop_index("ix_system_events_created_at", table_name="system_events")
    op.drop_index("ix_system_events_organisation_id", table_name="system_events")
    op.drop_table("system_events")
