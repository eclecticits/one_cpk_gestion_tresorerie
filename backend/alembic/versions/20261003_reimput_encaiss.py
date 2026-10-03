"""Droit de ré-imputer un encaissement sur un autre poste de recette.

Corriger le poste d'un encaissement déjà payé déplace du réalisé d'un poste de
recette à l'autre : imputations des versements, compteurs, brouillons
comptables. Comme pour les réquisitions (20260916_reimputation), c'est une
correction de dernier recours, accordée au seul rôle `admin` ; un trésorier ou
un caissier ne l'obtient que par attribution délibérée.

Revision ID: 20261003_reimput_encaiss
Revises: 20261001_monthly_treasury_st
Create Date: 2026-10-03
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "20261003_reimput_encaiss"
down_revision = "20261001_monthly_treasury_st"
branch_labels = None
depends_on = None


CODE = "treso.encaissements.reimputer"
DESCRIPTION = "Trésorerie — Encaissements : corriger le poste de recette, même après paiement"

SEMER = """
    INSERT INTO permissions (code, description, created_at)
    VALUES (:code, :description, now())
    ON CONFLICT (code) DO UPDATE SET description = EXCLUDED.description
"""

# `ON CONFLICT DO NOTHING` : rejouer la migration ne doit pas échouer sur une
# attribution déjà faite, ni écraser un retrait décidé depuis.
ACCORDER = """
    INSERT INTO role_permissions (role_id, permission_id)
    SELECT r.id, p.id
    FROM roles r, permissions p
    WHERE r.code = :role AND p.code = :code
    ON CONFLICT DO NOTHING
"""

ROLE = "admin"


def instructions() -> list[tuple[str, dict]]:
    """Le SQL de la migration, pour qu'il puisse être éprouvé plutôt que recopié."""
    return [
        (SEMER, {"code": CODE, "description": DESCRIPTION}),
        (ACCORDER, {"role": ROLE, "code": CODE}),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    for requete, params in instructions():
        bind.execute(text(requete), params)


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code = :code)"),
        {"code": CODE},
    )
    bind.execute(text("DELETE FROM permissions WHERE code = :code"), {"code": CODE})
