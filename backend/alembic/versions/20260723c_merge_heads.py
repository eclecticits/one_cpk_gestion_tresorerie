"""Merge des 6 têtes de révision restantes en une seule.

Regroupe les branches historiques jamais mergées (deux 0005 issues de 0004,
le split sur 20260325_org_theme_settings, la branche service_admin_canon) avec
la nouvelle chaîne des garde-fous financiers / snapshots historiques
(20260723b_hist_doc_snap).

Objectif : `alembic upgrade head` doit redevenir non ambigu sur une base
neuve et en CI. Cette révision ne modifie aucune donnée ni aucun schéma :
c'est un simple point de convergence.

Revision ID: 20260723c_merge_heads
Create Date: 2026-07-23
"""

from alembic import op  # noqa: F401  (importé pour cohérence avec les autres révisions)


revision = "20260723c_merge_heads"
down_revision = (
    "0005_requisitions_tables",
    "0005_validate_enc_constraints",
    "20260325_services_tenant_scope",
    "20260326_org_theme_text_color",
    "20260504_service_admin_canon",
    "20260723b_hist_doc_snap",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Merge pur : rien à appliquer."""


def downgrade() -> None:
    """Merge pur : rien à défaire."""
