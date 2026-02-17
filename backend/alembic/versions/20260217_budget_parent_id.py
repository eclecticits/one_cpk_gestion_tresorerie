"""add parent id to budget lignes

Revision ID: 20260217_budget_parent
Revises: 20260216_sortie_sig_cfg
Create Date: 2026-02-17
"""

from alembic import op

revision = "20260217_budget_parent"
down_revision = "20260216_sortie_sig_cfg"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE budget_lignes ADD COLUMN IF NOT EXISTS parent_id INTEGER;")
    op.execute("CREATE INDEX IF NOT EXISTS ix_budget_lignes_parent_id ON budget_lignes (parent_id);")
    op.execute(
        """
        DO $$
        BEGIN
            ALTER TABLE budget_lignes
                ADD CONSTRAINT fk_budget_lignes_parent_id
                FOREIGN KEY (parent_id) REFERENCES budget_lignes (id)
                ON DELETE SET NULL;
        EXCEPTION
            WHEN duplicate_object THEN
                NULL;
        END $$;
        """
    )
    op.execute(
        """
        UPDATE budget_lignes AS child
        SET parent_id = parent.id
        FROM budget_lignes AS parent
        WHERE child.parent_code IS NOT NULL
          AND child.parent_id IS NULL
          AND child.exercice_id = parent.exercice_id
          AND child.parent_code = parent.code
          AND child.id <> parent.id;
        """
    )


def downgrade() -> None:
    # Downgrade is intentionally no-op to avoid data loss in production.
    pass
