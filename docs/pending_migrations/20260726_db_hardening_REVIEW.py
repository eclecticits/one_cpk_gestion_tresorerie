"""[À VALIDER — NE PAS EXÉCUTER AUTOMATIQUEMENT] Durcissement DB : CHECK >= 0, immuabilité audit, montant SaaS en Numeric

═══════════════════════════════════════════════════════════════════════════════
  FICHIER DE REVUE — volontairement placé HORS de backend/alembic/versions/
  pour qu'il NE SOIT PAS ramassé par `alembic upgrade head` (l'entrypoint du
  conteneur exécute cette commande au démarrage).

  POUR L'APPLIQUER, APRÈS VALIDATION ET SAUVEGARDE :
    1. Faire une sauvegarde vérifiée de la base (pg_dump).
    2. Lancer d'abord les PRÉ-VÉRIFICATIONS ci-dessous ; corriger toute donnée
       hors-contrainte AVANT d'appliquer.
    3. Déplacer ce fichier dans backend/alembic/versions/ (retirer _REVIEW).
    4. `alembic upgrade head` (ou laisser l'entrypoint le faire au prochain boot).

  Tête actuelle au moment de la rédaction : 20260725_grant_authorize_disb
═══════════════════════════════════════════════════════════════════════════════

PRÉ-VÉRIFICATIONS (doivent renvoyer 0 ligne, sinon corriger d'abord) :

  -- DB-06 : montants négatifs existants
  SELECT id, montant_prevu, montant_engage, montant_paye FROM budget_postes
    WHERE montant_prevu < 0 OR montant_engage < 0 OR montant_paye < 0;
  SELECT id, montant_total FROM requisitions WHERE montant_total < 0;

  -- DB-05 : valeurs non convertibles (ne devrait rien renvoyer)
  SELECT id, amount FROM transactions WHERE amount IS NULL;

  -- DB-07 : aucune donnée requise ; vérifier qu'AUCUN traitement applicatif ne
  --         fait UPDATE/DELETE sur audit_logs (vérifié : append-only côté code).

Revision ID: 20260726_db_hardening
Revises: 20260725_grant_authorize_disb
Create Date: 2026-07-26
"""

from __future__ import annotations

from alembic import op


revision = "20260726_db_hardening"
down_revision = "20260725_grant_authorize_disb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── DB-06 : non-négativité des montants cœur (NOT VALID : n'échoue pas sur
    #    l'historique ; à VALIDATE plus tard une fois les données nettoyées). ──
    op.execute(
        """
        ALTER TABLE budget_postes
          ADD CONSTRAINT ck_budget_postes_montant_prevu_nonneg  CHECK (montant_prevu  >= 0) NOT VALID,
          ADD CONSTRAINT ck_budget_postes_montant_engage_nonneg CHECK (montant_engage >= 0) NOT VALID,
          ADD CONSTRAINT ck_budget_postes_montant_paye_nonneg   CHECK (montant_paye   >= 0) NOT VALID;
        """
    )
    op.execute(
        """
        ALTER TABLE requisitions
          ADD CONSTRAINT ck_requisitions_montant_total_nonneg CHECK (montant_total >= 0) NOT VALID;
        """
    )

    # ── DB-05 : montant de facturation SaaS en Numeric (évite les arrondis
    #    binaires du type Float). Conversion sûre (élargissement). ──
    op.execute(
        "ALTER TABLE transactions ALTER COLUMN amount TYPE numeric(15,2) USING amount::numeric(15,2);"
    )

    # ── DB-07 : journal d'audit append-only. Trigger refusant UPDATE/DELETE.
    #    (Vérifié : aucun code applicatif ne mute audit_logs.) ──
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_audit_log_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs est append-only : UPDATE/DELETE interdit (%).', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_immutable ON audit_logs;")
    op.execute(
        """
        CREATE TRIGGER trg_audit_logs_immutable
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_immutable ON audit_logs;")
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_log_mutation();")

    # Le type d'origine était double precision (Float).
    op.execute(
        "ALTER TABLE transactions ALTER COLUMN amount TYPE double precision USING amount::double precision;"
    )

    op.execute(
        "ALTER TABLE requisitions DROP CONSTRAINT IF EXISTS ck_requisitions_montant_total_nonneg;"
    )
    op.execute(
        """
        ALTER TABLE budget_postes
          DROP CONSTRAINT IF EXISTS ck_budget_postes_montant_paye_nonneg,
          DROP CONSTRAINT IF EXISTS ck_budget_postes_montant_engage_nonneg,
          DROP CONSTRAINT IF EXISTS ck_budget_postes_montant_prevu_nonneg;
        """
    )
