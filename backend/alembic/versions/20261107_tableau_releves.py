"""Tableau : relevés de situation envoyés aux membres

Revision ID: 20261107_tableau_releves
Revises: 20261106_tableau_sorties

Chaque envoi (e-mail ou WhatsApp) est consigné avec le texte exact reçu par le
membre. Le droit `tableau.notify` naît avec la table et reprend les
attributions de `tableau.correct` : ceux qui tiennent les dossiers peuvent
prévenir les membres de leur situation.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql


revision = "20261107_tableau_releves"
down_revision = "20261106_tableau_sorties"
branch_labels = None
depends_on = None


DROIT = ("tableau.notify", "Tableau : envoyer leur situation aux membres", "tableau.correct")

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


def upgrade() -> None:
    op.create_table(
        "tableau_releves",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("exercice", sa.String(20), nullable=False),
        sa.Column("numero_ordre", sa.String(50), nullable=False),
        sa.Column("nom", sa.String(300), nullable=False),
        sa.Column("categorie", sa.String(50), nullable=True),
        sa.Column("conclusion", sa.String(30), nullable=False),
        sa.Column("canal", sa.String(10), nullable=False),
        sa.Column("destinataire", sa.String(255), nullable=False),
        sa.Column("sujet", sa.String(300), nullable=False),
        sa.Column("corps", sa.Text(), nullable=False),
        sa.Column("empreinte", sa.String(64), nullable=False),
        sa.Column("statut", sa.String(10), nullable=False),
        sa.Column("erreur", sa.Text(), nullable=True),
        sa.Column("envoye_par", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("canal IN ('email', 'whatsapp')", name="ck_tableau_releve_canal"),
        sa.CheckConstraint("statut IN ('envoye', 'echec')", name="ck_tableau_releve_statut"),
    )
    op.create_index("ix_tableau_releves_organisation_id", "tableau_releves", ["organisation_id"])
    op.create_index("ix_tableau_releves_membre", "tableau_releves", ["organisation_id", "exercice", "numero_ordre"])

    bind = op.get_bind()
    code, description, source = DROIT
    bind.execute(text(SEMER_DROIT), {"code": code, "description": description})
    bind.execute(text(HERITER_DROIT), {"code": code, "source": source})


def downgrade() -> None:
    bind = op.get_bind()
    code = DROIT[0]
    bind.execute(
        text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code = :code)"),
        {"code": code},
    )
    bind.execute(text("DELETE FROM permissions WHERE code = :code"), {"code": code})
    op.drop_index("ix_tableau_releves_membre", table_name="tableau_releves")
    op.drop_index("ix_tableau_releves_organisation_id", table_name="tableau_releves")
    op.drop_table("tableau_releves")
