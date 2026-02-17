"""ensure audit_logs columns exist

Revision ID: 20260216_fix_audit
Revises: 20260216_fix_softdel
Create Date: 2026-02-16
"""

from alembic import op


revision = "20260216_fix_audit"
down_revision = "20260216_fix_softdel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS entity_type VARCHAR(50);")
    op.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS entity_id VARCHAR(100);")
    op.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS action VARCHAR(30);")
    op.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS field_name VARCHAR(50);")
    op.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS old_value TEXT;")
    op.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS new_value TEXT;")
    op.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS user_id UUID;")
    op.execute("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;")
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_logs_entity_type ON audit_logs (entity_type);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_logs_entity_id ON audit_logs (entity_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_audit_logs_user_id ON audit_logs (user_id);")


def downgrade() -> None:
    # no-op to avoid data loss
    pass
