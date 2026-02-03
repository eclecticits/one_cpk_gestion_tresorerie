"""Tables métier de base (baseline)

Revision ID: 0002_baseline_business_tables
Revises: 0001_init_auth_tables
Create Date: 2026-01-22

"""

from __future__ import annotations

from alembic import op

revision = "0002_baseline_business_tables"
down_revision = "0001_init_auth_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Création des tables de base nécessaires pour rendre l'application utilisable
    sur une base Postgres vide.

    Important (asyncpg) :
    - UNE SEULE commande SQL par op.execute()
    - Donc : CREATE TABLE séparé des CREATE INDEX / CREATE UNIQUE INDEX
    """

    # -------------------------------------------------------------------------
    # 1) RUBRIQUES
    # -------------------------------------------------------------------------
    op.execute(
        """
CREATE TABLE IF NOT EXISTS public.rubriques (
  id uuid PRIMARY KEY,
  code varchar(50) NOT NULL UNIQUE,
  libelle varchar(200) NOT NULL,
  description text,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);
"""
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_rubriques_code ON public.rubriques(code);")

    # -------------------------------------------------------------------------
    # 2) PERMISSIONS D'ACCÈS AUX MENUS (par utilisateur)
    # -------------------------------------------------------------------------
    op.execute(
        """
CREATE TABLE IF NOT EXISTS public.user_menu_permissions (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES public.users(id),
  menu_name varchar(80) NOT NULL,
  can_access boolean NOT NULL DEFAULT true,
  created_by uuid REFERENCES public.users(id),
  created_at timestamptz NOT NULL DEFAULT now()
);
"""
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_menu_permissions_user_id ON public.user_menu_permissions(user_id);"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_menu_permissions_user_menu ON public.user_menu_permissions(user_id, menu_name);"
    )

    # -------------------------------------------------------------------------
    # 3) RÔLES UTILISATEURS (plusieurs rôles possibles par user)
    # -------------------------------------------------------------------------
    op.execute(
        """
CREATE TABLE IF NOT EXISTS public.user_roles (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES public.users(id),
  role varchar(80) NOT NULL,
  created_by uuid REFERENCES public.users(id),
  created_at timestamptz NOT NULL DEFAULT now()
);
"""
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_roles_user_id ON public.user_roles(user_id);")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_roles_user_role ON public.user_roles(user_id, role);"
    )

    # -------------------------------------------------------------------------
    # 4) PARAMÈTRES D'IMPRESSION (en-tête/pied, coordonnées, banque, etc.)
    # -------------------------------------------------------------------------
    op.execute(
        """
CREATE TABLE IF NOT EXISTS public.print_settings (
  id uuid PRIMARY KEY,
  organization_name varchar(200) NOT NULL DEFAULT '',
  organization_subtitle varchar(200) NOT NULL DEFAULT '',
  header_text varchar(300) NOT NULL DEFAULT '',
  address varchar(300) NOT NULL DEFAULT '',
  phone varchar(100) NOT NULL DEFAULT '',
  email varchar(200) NOT NULL DEFAULT '',
  website varchar(200) NOT NULL DEFAULT '',
  bank_name varchar(200) NOT NULL DEFAULT '',
  bank_account varchar(200) NOT NULL DEFAULT '',
  mobile_money_name varchar(200) NOT NULL DEFAULT '',
  mobile_money_number varchar(100) NOT NULL DEFAULT '',
  footer_text text NOT NULL DEFAULT '',
  show_header_logo boolean NOT NULL DEFAULT true,
  show_footer_signature boolean NOT NULL DEFAULT true,
  updated_by uuid,
  updated_at timestamptz NOT NULL DEFAULT now()
);
"""
    )

    # -------------------------------------------------------------------------
    # 5) APPROBATEURS DE RÉQUISITIONS (qui peut approuver)
    # -------------------------------------------------------------------------
    op.execute(
        """
CREATE TABLE IF NOT EXISTS public.requisition_approvers (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES public.users(id),
  active boolean NOT NULL DEFAULT true,
  notes text,
  added_by uuid REFERENCES public.users(id),
  added_at timestamptz NOT NULL DEFAULT now()
);
"""
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_requisition_approvers_user_id ON public.requisition_approvers(user_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_requisition_approvers_active ON public.requisition_approvers(active);"
    )


def downgrade() -> None:
    """
    Retour arrière :
    - On supprime les tables métier de base.
    - On ne touche pas aux tables d'authentification (users, refresh_tokens).
    """

    # Pour éviter des erreurs, on supprime d'abord les index explicites (bonne pratique)
    op.execute("DROP INDEX IF EXISTS ix_requisition_approvers_active;")
    op.execute("DROP INDEX IF EXISTS uq_requisition_approvers_user_id;")
    op.execute("DROP INDEX IF EXISTS uq_user_roles_user_role;")
    op.execute("DROP INDEX IF EXISTS ix_user_roles_user_id;")
    op.execute("DROP INDEX IF EXISTS uq_user_menu_permissions_user_menu;")
    op.execute("DROP INDEX IF EXISTS ix_user_menu_permissions_user_id;")
    op.execute("DROP INDEX IF EXISTS ix_rubriques_code;")

    # Puis on supprime les tables
    op.execute("DROP TABLE IF EXISTS public.requisition_approvers;")
    op.execute("DROP TABLE IF EXISTS public.print_settings;")
    op.execute("DROP TABLE IF EXISTS public.user_roles;")
    op.execute("DROP TABLE IF EXISTS public.user_menu_permissions;")
    op.execute("DROP TABLE IF EXISTS public.rubriques;")
