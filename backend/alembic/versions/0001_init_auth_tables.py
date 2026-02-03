"""Initialisation des tables d'authentification

Revision ID: 0001_init_auth_tables
Revises:
Create Date: 2026-01-21

"""

from __future__ import annotations

from alembic import op

revision = "0001_init_auth_tables"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Ce projet peut tourner sur :
      - une base Postgres vierge (aucune table), OU
      - une base importée où `public.users` existe déjà.

    Les mots de passe d'auth legacy ne peuvent pas être migrés tels quels :
    on ajoute donc `hashed_password` pour la nouvelle authentification de l'application.
    """

    # 1) S'assurer que la table users existe (ou la compléter si elle existe déjà)
    op.execute(
        """
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema='public' AND table_name='users'
  ) THEN
    -- Cas 1 : base vierge -> création de la table users
    CREATE TABLE public.users (
      id uuid PRIMARY KEY,
      email varchar(320) NOT NULL UNIQUE,
      nom varchar(120),
      prenom varchar(120),
      hashed_password varchar(255),
      role varchar(50) NOT NULL DEFAULT 'reception',
      active boolean NOT NULL DEFAULT true,
      must_change_password boolean NOT NULL DEFAULT false,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now()
    );
  ELSE
    -- Cas 2 : table users existe déjà (ex: base importée)
    -- On ajoute uniquement les colonnes manquantes nécessaires à la nouvelle auth.

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema='public' AND table_name='users' AND column_name='hashed_password'
    ) THEN
      ALTER TABLE public.users ADD COLUMN hashed_password varchar(255);
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema='public' AND table_name='users' AND column_name='must_change_password'
    ) THEN
      ALTER TABLE public.users ADD COLUMN must_change_password boolean NOT NULL DEFAULT false;
    END IF;

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema='public' AND table_name='users' AND column_name='active'
    ) THEN
      ALTER TABLE public.users ADD COLUMN active boolean NOT NULL DEFAULT true;
    END IF;
  END IF;
END $$;
"""
    )

    # Index sur email (séparé dans un op.execute() à cause de asyncpg)
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_email ON public.users(email);")

    # 2) Créer la table refresh_tokens (une seule commande SQL par op.execute)
    op.execute(
        """
CREATE TABLE IF NOT EXISTS public.refresh_tokens (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES public.users(id),
  jti varchar(128) NOT NULL,
  token_hash varchar(64) NOT NULL UNIQUE,
  revoked boolean NOT NULL DEFAULT false,
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
"""
    )

    # 3) Index sur refresh_tokens (un index = une commande)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_refresh_tokens_user_id ON public.refresh_tokens(user_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_refresh_tokens_jti ON public.refresh_tokens(jti);"
    )


def downgrade() -> None:
    """
    Retour arrière :
    - On supprime refresh_tokens et ses index.
    - On ne supprime pas users car elle peut pré-exister (base importée).
    """
    op.execute("DROP TABLE IF EXISTS public.refresh_tokens;")
    op.execute("DROP INDEX IF EXISTS ix_refresh_tokens_user_id;")
    op.execute("DROP INDEX IF EXISTS ix_refresh_tokens_jti;")
    op.execute("DROP INDEX IF EXISTS ix_users_email;")
