"""Add encaissements/payment_history constraints

Revision ID: 0004_encaissements_constraints
Revises: 0003_experts_encaissements
Create Date: 2026-01-27
"""

from __future__ import annotations

from alembic import op

revision = "0004_encaissements_constraints"
down_revision = "0003_experts_encaissements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Encaissements: enums + amounts + client/expert consistency
    op.execute(
        """
DO $$ BEGIN
  ALTER TABLE public.encaissements
    ADD CONSTRAINT ck_encaissements_type_client
    CHECK (type_client IN ('expert_comptable','client_externe','banque_institution','partenaire','organisation','autre')) NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
"""
    )
    op.execute(
        """
DO $$ BEGIN
  ALTER TABLE public.encaissements
    ADD CONSTRAINT ck_encaissements_statut_paiement
    CHECK (statut_paiement IN ('non_paye','partiel','complet','avance')) NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
"""
    )
    op.execute(
        """
DO $$ BEGIN
  ALTER TABLE public.encaissements
    ADD CONSTRAINT ck_encaissements_mode_paiement
    CHECK (mode_paiement IN ('cash','mobile_money','virement')) NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
"""
    )
    op.execute(
        """
DO $$ BEGIN
  ALTER TABLE public.encaissements
    ADD CONSTRAINT ck_encaissements_montant_nonneg
    CHECK (montant >= 0) NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
"""
    )
    op.execute(
        """
DO $$ BEGIN
  ALTER TABLE public.encaissements
    ADD CONSTRAINT ck_encaissements_montant_total_nonneg
    CHECK (montant_total >= 0) NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
"""
    )
    op.execute(
        """
DO $$ BEGIN
  ALTER TABLE public.encaissements
    ADD CONSTRAINT ck_encaissements_montant_paye_nonneg
    CHECK (montant_paye >= 0) NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
"""
    )
    op.execute(
        """
DO $$ BEGIN
  ALTER TABLE public.encaissements
    ADD CONSTRAINT ck_encaissements_client_ref
    CHECK (
      (type_client = 'expert_comptable' AND expert_comptable_id IS NOT NULL)
      OR (type_client <> 'expert_comptable' AND client_nom IS NOT NULL AND length(trim(client_nom)) > 0)
    ) NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
"""
    )

    # Payment history: amounts + mode
    op.execute(
        """
DO $$ BEGIN
  ALTER TABLE public.payment_history
    ADD CONSTRAINT ck_payment_history_montant_positive
    CHECK (montant > 0) NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
"""
    )
    op.execute(
        """
DO $$ BEGIN
  ALTER TABLE public.payment_history
    ADD CONSTRAINT ck_payment_history_mode_paiement
    CHECK (mode_paiement IN ('cash','mobile_money','virement')) NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
"""
    )


def downgrade() -> None:
    op.execute("ALTER TABLE IF EXISTS public.encaissements DROP CONSTRAINT IF EXISTS ck_encaissements_client_ref;")
    op.execute("ALTER TABLE IF EXISTS public.encaissements DROP CONSTRAINT IF EXISTS ck_encaissements_montant_paye_nonneg;")
    op.execute("ALTER TABLE IF EXISTS public.encaissements DROP CONSTRAINT IF EXISTS ck_encaissements_montant_total_nonneg;")
    op.execute("ALTER TABLE IF EXISTS public.encaissements DROP CONSTRAINT IF EXISTS ck_encaissements_montant_nonneg;")
    op.execute("ALTER TABLE IF EXISTS public.encaissements DROP CONSTRAINT IF EXISTS ck_encaissements_mode_paiement;")
    op.execute("ALTER TABLE IF EXISTS public.encaissements DROP CONSTRAINT IF EXISTS ck_encaissements_statut_paiement;")
    op.execute("ALTER TABLE IF EXISTS public.encaissements DROP CONSTRAINT IF EXISTS ck_encaissements_type_client;")

    op.execute("ALTER TABLE IF EXISTS public.payment_history DROP CONSTRAINT IF EXISTS ck_payment_history_mode_paiement;")
    op.execute("ALTER TABLE IF EXISTS public.payment_history DROP CONSTRAINT IF EXISTS ck_payment_history_montant_positive;")
