"""Seed initial organisations.

Revision ID: 20260323_seed_initial_organisations
Revises: 20260322_org_icon_order
Create Date: 2026-03-23
"""

from alembic import op


revision = "20260323_seed_initial_organisations"
down_revision = "20260322_org_icon_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO organisations (nom, slug, icon, sort_order, is_active)
        VALUES ('Kinshasa', 'kinshasa', '🏢', 1, TRUE)
        ON CONFLICT (slug) DO UPDATE
        SET icon = EXCLUDED.icon,
            sort_order = EXCLUDED.sort_order,
            is_active = TRUE;

        INSERT INTO organisations (nom, slug, icon, sort_order, is_active)
        VALUES ('Haut-Katanga', 'haut-katanga', '🏭', 2, TRUE)
        ON CONFLICT (slug) DO NOTHING;

        INSERT INTO organisations (nom, slug, icon, sort_order, is_active)
        VALUES ('Sud-Kivu', 'sud-kivu', '🌋', 3, TRUE)
        ON CONFLICT (slug) DO NOTHING;
        """
    )


def downgrade() -> None:
    # Pas de suppression pour éviter de casser les FKs ou des données existantes.
    pass
