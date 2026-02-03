"""Tables experts_comptables, encaissements, payment_history et historiques

Revision ID: 0003_experts_encaissements
Revises: 0002_baseline_business_tables
Create Date: 2026-01-23

"""

from __future__ import annotations

from alembic import op

revision = "0003_experts_encaissements"
down_revision = "0002_baseline_business_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Création des tables métier principales pour la gestion trésorerie.
    
    Important (asyncpg): UNE SEULE commande SQL par op.execute()
    """

    # -------------------------------------------------------------------------
    # 1) EXPERTS COMPTABLES
    # -------------------------------------------------------------------------
    op.execute(
        """
CREATE TABLE IF NOT EXISTS public.experts_comptables (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  numero_ordre varchar(50) NOT NULL UNIQUE,
  nom_denomination varchar(300) NOT NULL,
  type_ec varchar(10) NOT NULL DEFAULT 'EC',
  categorie_personne varchar(50),
  statut_professionnel varchar(50),
  sexe varchar(1),
  telephone varchar(50),
  email varchar(200),
  nif varchar(50),
  cabinet_attache varchar(200),
  nom_employeur varchar(200),
  raison_sociale varchar(300),
  associe_gerant varchar(200),
  import_id uuid,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);
"""
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_experts_comptables_numero_ordre ON public.experts_comptables(numero_ordre);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_experts_comptables_type_ec ON public.experts_comptables(type_ec);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_experts_comptables_active ON public.experts_comptables(active);")

    # -------------------------------------------------------------------------
    # 2) HISTORIQUE CHANGEMENTS DE CATÉGORIE
    # -------------------------------------------------------------------------
    op.execute(
        """
CREATE TABLE IF NOT EXISTS public.category_changes_history (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  expert_id uuid NOT NULL,
  numero_ordre varchar(50) NOT NULL,
  old_category varchar(50),
  new_category varchar(50) NOT NULL,
  changed_by uuid,
  reason text,
  old_data jsonb,
  new_data jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
"""
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_category_changes_history_expert_id ON public.category_changes_history(expert_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_category_changes_history_created_at ON public.category_changes_history(created_at);")

    # -------------------------------------------------------------------------
    # 3) HISTORIQUE DES IMPORTS
    # -------------------------------------------------------------------------
    op.execute(
        """
CREATE TABLE IF NOT EXISTS public.imports_history (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  filename varchar(300) NOT NULL,
  category varchar(50) NOT NULL,
  imported_by uuid,
  rows_imported integer NOT NULL DEFAULT 0,
  status varchar(20) NOT NULL DEFAULT 'success',
  file_data jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
"""
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_imports_history_category ON public.imports_history(category);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_imports_history_created_at ON public.imports_history(created_at);")

    # -------------------------------------------------------------------------
    # 4) ENCAISSEMENTS
    # -------------------------------------------------------------------------
    op.execute(
        """
CREATE TABLE IF NOT EXISTS public.encaissements (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  numero_recu varchar(50) NOT NULL UNIQUE,
  type_client varchar(50) NOT NULL,
  expert_comptable_id uuid,
  client_nom varchar(300),
  type_operation varchar(100) NOT NULL,
  description text,
  montant numeric(15,2) NOT NULL DEFAULT 0,
  montant_total numeric(15,2) NOT NULL DEFAULT 0,
  montant_paye numeric(15,2) NOT NULL DEFAULT 0,
  statut_paiement varchar(20) NOT NULL DEFAULT 'non_paye',
  mode_paiement varchar(30) NOT NULL DEFAULT 'cash',
  reference varchar(100),
  date_encaissement timestamptz NOT NULL DEFAULT now(),
  created_by uuid,
  created_at timestamptz NOT NULL DEFAULT now()
);
"""
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_encaissements_numero_recu ON public.encaissements(numero_recu);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_encaissements_type_client ON public.encaissements(type_client);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_encaissements_statut_paiement ON public.encaissements(statut_paiement);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_encaissements_date_encaissement ON public.encaissements(date_encaissement);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_encaissements_expert_comptable_id ON public.encaissements(expert_comptable_id);")

    # -------------------------------------------------------------------------
    # 5) HISTORIQUE DES PAIEMENTS
    # -------------------------------------------------------------------------
    op.execute(
        """
CREATE TABLE IF NOT EXISTS public.payment_history (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  encaissement_id uuid NOT NULL,
  montant numeric(15,2) NOT NULL,
  mode_paiement varchar(30) NOT NULL DEFAULT 'cash',
  reference varchar(100),
  notes text,
  created_by uuid,
  created_at timestamptz NOT NULL DEFAULT now()
);
"""
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_payment_history_encaissement_id ON public.payment_history(encaissement_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_payment_history_created_at ON public.payment_history(created_at);")

    # -------------------------------------------------------------------------
    # 6) CONTRAINTES FK (ajoutées séparément pour flexibilité)
    # -------------------------------------------------------------------------
    # FK: category_changes_history.expert_id -> experts_comptables.id
    op.execute(
        """
DO $$ BEGIN
  ALTER TABLE public.category_changes_history 
    ADD CONSTRAINT fk_category_changes_expert 
    FOREIGN KEY (expert_id) REFERENCES public.experts_comptables(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
"""
    )

    # FK: payment_history.encaissement_id -> encaissements.id
    op.execute(
        """
DO $$ BEGIN
  ALTER TABLE public.payment_history 
    ADD CONSTRAINT fk_payment_history_encaissement 
    FOREIGN KEY (encaissement_id) REFERENCES public.encaissements(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
"""
    )

    # FK: encaissements.expert_comptable_id -> experts_comptables.id
    op.execute(
        """
DO $$ BEGIN
  ALTER TABLE public.encaissements 
    ADD CONSTRAINT fk_encaissements_expert 
    FOREIGN KEY (expert_comptable_id) REFERENCES public.experts_comptables(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
"""
    )


def downgrade() -> None:
    """
    Suppression des tables métier.
    """
    # D'abord supprimer les FK
    op.execute("ALTER TABLE IF EXISTS public.encaissements DROP CONSTRAINT IF EXISTS fk_encaissements_expert;")
    op.execute("ALTER TABLE IF EXISTS public.payment_history DROP CONSTRAINT IF EXISTS fk_payment_history_encaissement;")
    op.execute("ALTER TABLE IF EXISTS public.category_changes_history DROP CONSTRAINT IF EXISTS fk_category_changes_expert;")

    # Supprimer les index
    op.execute("DROP INDEX IF EXISTS ix_payment_history_created_at;")
    op.execute("DROP INDEX IF EXISTS ix_payment_history_encaissement_id;")
    op.execute("DROP INDEX IF EXISTS ix_encaissements_expert_comptable_id;")
    op.execute("DROP INDEX IF EXISTS ix_encaissements_date_encaissement;")
    op.execute("DROP INDEX IF EXISTS ix_encaissements_statut_paiement;")
    op.execute("DROP INDEX IF EXISTS ix_encaissements_type_client;")
    op.execute("DROP INDEX IF EXISTS ix_encaissements_numero_recu;")
    op.execute("DROP INDEX IF EXISTS ix_imports_history_created_at;")
    op.execute("DROP INDEX IF EXISTS ix_imports_history_category;")
    op.execute("DROP INDEX IF EXISTS ix_category_changes_history_created_at;")
    op.execute("DROP INDEX IF EXISTS ix_category_changes_history_expert_id;")
    op.execute("DROP INDEX IF EXISTS ix_experts_comptables_active;")
    op.execute("DROP INDEX IF EXISTS ix_experts_comptables_type_ec;")
    op.execute("DROP INDEX IF EXISTS ix_experts_comptables_numero_ordre;")

    # Supprimer les tables
    op.execute("DROP TABLE IF EXISTS public.payment_history;")
    op.execute("DROP TABLE IF EXISTS public.encaissements;")
    op.execute("DROP TABLE IF EXISTS public.imports_history;")
    op.execute("DROP TABLE IF EXISTS public.category_changes_history;")
    op.execute("DROP TABLE IF EXISTS public.experts_comptables;")
