"""ensure soft delete columns exist

Revision ID: 20260216_fix_softdel
Revises: 20260216_import_src
Create Date: 2026-02-16
"""

from alembic import op


revision = "20260216_fix_softdel"
down_revision = "20260216_import_src"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE budget_lignes ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT false;")
    op.execute("ALTER TABLE budget_lignes ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;")
    op.execute("ALTER TABLE budget_lignes ADD COLUMN IF NOT EXISTS deleted_by UUID;")
    op.execute("CREATE INDEX IF NOT EXISTS ix_budget_lignes_is_deleted ON budget_lignes (is_deleted);")

    op.execute("ALTER TABLE requisitions ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT false;")
    op.execute("ALTER TABLE requisitions ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;")
    op.execute("ALTER TABLE requisitions ADD COLUMN IF NOT EXISTS deleted_by UUID;")
    op.execute("CREATE INDEX IF NOT EXISTS ix_requisitions_is_deleted ON requisitions (is_deleted);")

    op.execute("ALTER TABLE encaissements ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT false;")
    op.execute("ALTER TABLE encaissements ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;")
    op.execute("ALTER TABLE encaissements ADD COLUMN IF NOT EXISTS deleted_by UUID;")
    op.execute("CREATE INDEX IF NOT EXISTS ix_encaissements_is_deleted ON encaissements (is_deleted);")


def downgrade() -> None:
    # Downgrade is intentionally no-op to avoid data loss in production.
    pass
