"""Validate encaissements constraints with pre-check

Revision ID: 0005_validate_enc_constraints
Revises: 0004_encaissements_constraints
Create Date: 2026-01-27
"""

from __future__ import annotations

from alembic import op

revision = "0005_validate_enc_constraints"
down_revision = "0004_encaissements_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Pre-check violations and validate constraints.
    op.execute(
        """
DO $$
DECLARE
  v_type_client integer;
  v_statut_paiement integer;
  v_mode_paiement integer;
  v_montant integer;
  v_montant_total integer;
  v_montant_paye integer;
  v_client_ref integer;
BEGIN
  SELECT COUNT(*) INTO v_type_client
  FROM public.encaissements
  WHERE type_client NOT IN ('expert_comptable','client_externe','banque_institution','partenaire','organisation','autre');

  SELECT COUNT(*) INTO v_statut_paiement
  FROM public.encaissements
  WHERE statut_paiement NOT IN ('non_paye','partiel','complet','avance');

  SELECT COUNT(*) INTO v_mode_paiement
  FROM public.encaissements
  WHERE mode_paiement NOT IN ('cash','mobile_money','virement');

  SELECT COUNT(*) INTO v_montant
  FROM public.encaissements
  WHERE montant < 0;

  SELECT COUNT(*) INTO v_montant_total
  FROM public.encaissements
  WHERE montant_total < 0;

  SELECT COUNT(*) INTO v_montant_paye
  FROM public.encaissements
  WHERE montant_paye < 0;

  SELECT COUNT(*) INTO v_client_ref
  FROM public.encaissements
  WHERE (type_client = 'expert_comptable' AND expert_comptable_id IS NULL)
     OR (type_client <> 'expert_comptable' AND (client_nom IS NULL OR length(trim(client_nom)) = 0));

  RAISE NOTICE 'Encaissements constraint pre-checks -> type_client: %, statut_paiement: %, mode_paiement: %, montant: %, montant_total: %, montant_paye: %, client_ref: %',
    v_type_client, v_statut_paiement, v_mode_paiement, v_montant, v_montant_total, v_montant_paye, v_client_ref;
END $$;
"""
    )

    op.execute("ALTER TABLE public.encaissements VALIDATE CONSTRAINT ck_encaissements_type_client;")
    op.execute("ALTER TABLE public.encaissements VALIDATE CONSTRAINT ck_encaissements_statut_paiement;")
    op.execute("ALTER TABLE public.encaissements VALIDATE CONSTRAINT ck_encaissements_mode_paiement;")
    op.execute("ALTER TABLE public.encaissements VALIDATE CONSTRAINT ck_encaissements_montant_nonneg;")
    op.execute("ALTER TABLE public.encaissements VALIDATE CONSTRAINT ck_encaissements_montant_total_nonneg;")
    op.execute("ALTER TABLE public.encaissements VALIDATE CONSTRAINT ck_encaissements_montant_paye_nonneg;")
    op.execute("ALTER TABLE public.encaissements VALIDATE CONSTRAINT ck_encaissements_client_ref;")


def downgrade() -> None:
    # VALIDATE cannot be undone; keep as no-op.
    pass
