"""Le Tableau tient son propre journal, et son propre assistant.

Le module consignait ses actes dans `secretariat_audit_logs` sous
`agent_type='tableau'`. Il ne dépend plus du Secrétariat : il lui faut donc son
journal. Les entrées déjà écrites sont déplacées, pas dupliquées — sans quoi la
même correction se lirait deux fois, à deux endroits, et l'écran du Secrétariat
continuerait d'afficher des actes qui ne le regardent plus.

Deux droits naissent avec ce lot, et chacun est repris de celui qui l'ouvrait
avant, pour que personne ne perde ce qu'il faisait déjà :
  - `tableau.view_audit_logs` ← `secretariat.view_audit_logs` (ceux qui lisaient
    le journal du Secrétariat y voyaient les actes du Tableau) ;
  - `tableau.use_assistant` ← `secretariat.use_agent_manager` (l'assistant
    affiché sur l'écran du Tableau était celui du Secrétariat).

Revision ID: 20260915_tableau_audit
Revises: 20260915_tableau_module
Create Date: 2026-09-15
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql


revision = "20260915_tableau_audit"
down_revision = "20260915_tableau_module"
branch_labels = None
depends_on = None


NOUVEAUX_DROITS: list[tuple[str, str, str]] = [
    # (code, description, code dont il hérite les attributions)
    ("tableau.view_audit_logs", "Tableau : consulter le journal des actions", "secretariat.view_audit_logs"),
    ("tableau.use_assistant", "Tableau : utiliser l'assistant", "secretariat.use_agent_manager"),
]

REPRISE_ENTREES = """
    INSERT INTO tableau_audit_logs
        (organisation_id, user_id, action, target_type, target_id, status, metadata_json, created_at)
    SELECT organisation_id, user_id, action, target_type, target_id, status, metadata_json, created_at
      FROM secretariat_audit_logs
     WHERE agent_type = 'tableau'
"""

PURGE_ENTREES = "DELETE FROM secretariat_audit_logs WHERE agent_type = 'tableau'"

SEMER_DROIT = """
    INSERT INTO permissions (code, description, created_at)
    VALUES (:code, :description, now())
    ON CONFLICT (code) DO UPDATE SET description = EXCLUDED.description
"""

HERITER_DROIT = """
    INSERT INTO role_permissions (role_id, permission_id)
    SELECT rp.role_id, cible.id
      FROM role_permissions rp
      JOIN permissions source ON source.id = rp.permission_id AND source.code = :source
      JOIN permissions cible ON cible.code = :code
     WHERE NOT EXISTS (
         SELECT 1 FROM role_permissions deja
          WHERE deja.role_id = rp.role_id AND deja.permission_id = cible.id
     )
"""


def instructions() -> list[tuple[str, dict]]:
    """Le SQL de la migration, pour qu'il puisse être éprouvé plutôt que recopié."""
    pas: list[tuple[str, dict]] = [(REPRISE_ENTREES, {}), (PURGE_ENTREES, {})]
    for code, description, source in NOUVEAUX_DROITS:
        pas.append((SEMER_DROIT, {"code": code, "description": description}))
        pas.append((HERITER_DROIT, {"code": code, "source": source}))
    return pas


def upgrade() -> None:
    op.create_table(
        "tableau_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("target_type", sa.String(60), nullable=True),
        sa.Column("target_id", sa.String(80), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="success"),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_tableau_audit_logs_organisation_id", "tableau_audit_logs", ["organisation_id"])
    op.create_index("ix_tableau_audit_logs_user_id", "tableau_audit_logs", ["user_id"])
    op.create_index("ix_tableau_audit_logs_action", "tableau_audit_logs", ["action"])
    op.create_index("ix_tableau_audit_logs_status", "tableau_audit_logs", ["status"])
    op.create_index("ix_tableau_audit_logs_created_at", "tableau_audit_logs", ["created_at"])

    bind = op.get_bind()
    for requete, params in instructions():
        bind.execute(text(requete), params)


def downgrade() -> None:
    bind = op.get_bind()
    # Les entrées retournent d'où elles venaient : le journal du module disparaît
    # avec lui, il ne doit pas emporter l'historique.
    bind.execute(text("""
        INSERT INTO secretariat_audit_logs
            (organisation_id, user_id, agent_type, action, target_type, target_id, status, metadata_json, created_at)
        SELECT organisation_id, user_id, 'tableau', action, target_type, target_id, status, metadata_json, created_at
          FROM tableau_audit_logs
    """))
    for code, _description, _source in NOUVEAUX_DROITS:
        bind.execute(
            text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code = :code)"),
            {"code": code},
        )
        bind.execute(text("DELETE FROM permissions WHERE code = :code"), {"code": code})

    op.drop_table("tableau_audit_logs")
