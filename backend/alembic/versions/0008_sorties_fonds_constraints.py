"""add sorties_fonds constraints

Revision ID: 0008_sorties_fonds_constraints
Revises: 0007_sorties_fonds_table
Create Date: 2026-01-30
"""

from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "0008_sorties_fonds_constraints"
down_revision = "0007_sorties_fonds_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # FK: sorties_fonds.requisition_id -> requisitions.id
    op.execute(
        """
DO $$ BEGIN
  ALTER TABLE public.sorties_fonds
    ADD CONSTRAINT fk_sorties_fonds_requisition
    FOREIGN KEY (requisition_id) REFERENCES public.requisitions(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
"""
    )

    # FK: sorties_fonds.created_by -> users.id
    op.execute(
        """
DO $$ BEGIN
  ALTER TABLE public.sorties_fonds
    ADD CONSTRAINT fk_sorties_fonds_created_by
    FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
"""
    )

    # Checks
    op.execute(
        """
DO $$ BEGIN
  ALTER TABLE public.sorties_fonds
    ADD CONSTRAINT ck_sorties_fonds_montant_paye_nonneg
    CHECK (montant_paye >= 0) NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
"""
    )
    op.execute(
        """
DO $$ BEGIN
  ALTER TABLE public.sorties_fonds
    ADD CONSTRAINT ck_sorties_fonds_mode_paiement
    CHECK (mode_paiement IN ('cash','mobile_money','virement')) NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
"""
    )


def downgrade() -> None:
    op.execute("ALTER TABLE IF EXISTS public.sorties_fonds DROP CONSTRAINT IF EXISTS ck_sorties_fonds_mode_paiement;")
    op.execute("ALTER TABLE IF EXISTS public.sorties_fonds DROP CONSTRAINT IF EXISTS ck_sorties_fonds_montant_paye_nonneg;")
    op.execute("ALTER TABLE IF EXISTS public.sorties_fonds DROP CONSTRAINT IF EXISTS fk_sorties_fonds_created_by;")
    op.execute("ALTER TABLE IF EXISTS public.sorties_fonds DROP CONSTRAINT IF EXISTS fk_sorties_fonds_requisition;")
