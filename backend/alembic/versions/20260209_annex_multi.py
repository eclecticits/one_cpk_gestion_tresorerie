"""allow multiple annexes per requisition

Revision ID: 20260209_annex_multi
Revises: 20260209_sortie_motif_annulation
Create Date: 2026-02-09
"""

from alembic import op


revision = "20260209_annex_multi"
down_revision = "20260209_sortie_motif_annulation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            c_name text;
        BEGIN
            SELECT conname INTO c_name
            FROM pg_constraint
            WHERE conrelid = 'requisition_annexes'::regclass
              AND contype = 'u'
              AND conkey = ARRAY[
                (SELECT attnum FROM pg_attribute
                 WHERE attrelid = 'requisition_annexes'::regclass
                   AND attname = 'requisition_id')
              ];
            IF c_name IS NOT NULL THEN
                EXECUTE format('ALTER TABLE requisition_annexes DROP CONSTRAINT %I', c_name);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("requisition_annexes") as batch:
        batch.create_unique_constraint("requisition_annexes_requisition_id_key", ["requisition_id"])
