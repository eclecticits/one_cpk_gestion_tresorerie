"""index trigramme pour la recherche partielle des numéros

Revision ID: 20261028d_numero_trigram
Revises: 20261028c_annexe_versions
Create Date: 2026-10-28
"""

from alembic import op


revision = "20261028d_numero_trigram"
down_revision = "20261028c_annexe_versions"
branch_labels = None
depends_on = None


INDEXES = {
    "ix_sorties_reference_numero_trgm": ("sorties_fonds", "reference_numero"),
    "ix_sorties_reference_trgm": ("sorties_fonds", "reference"),
    "ix_retours_reference_numero_trgm": ("retours_caisse", "reference_numero"),
    "ix_retours_reference_trgm": ("retours_caisse", "reference"),
    "ix_transferts_reference_trgm": ("transferts_internes", "reference"),
}


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for index, (table, column) in INDEXES.items():
        op.execute(
            f"CREATE INDEX {index} ON {table} USING gin ({column} gin_trgm_ops) "
            f"WHERE {column} IS NOT NULL"
        )


def downgrade() -> None:
    for index in reversed(INDEXES):
        op.execute(f"DROP INDEX IF EXISTS {index}")
