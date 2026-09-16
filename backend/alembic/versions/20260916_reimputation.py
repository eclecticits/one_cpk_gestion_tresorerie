"""Droit de ré-imputer une réquisition sur un autre poste budgétaire.

Corriger l'imputation d'une réquisition déjà validée et payée déplace de
l'argent d'un poste à l'autre : engagement, réalisé et imputations figées du
paiement. C'est une correction de dernier recours, pas un acte de gestion
courante.

Le code est accordé au seul rôle `admin` : corriger une imputation est un acte
d'administration de dernier recours, pas une opération de gestion courante.
L'administrateur et le super-admin y accédaient déjà par le court-circuit de
`has_permission`, ici comme dans l'interface ; l'accorder explicitement rend la
capacité lisible dans la matrice des permissions au lieu de la laisser dépendre
d'un raccourci, et permet de la retirer sans toucher au code.

Aucun autre rôle ne le reçoit. Un trésorier, un comptable ou un caissier ne
l'obtiennent que par attribution délibérée — jamais par héritage.

Revision ID: 20260916_reimputation
Revises: 20260915_tableau_audit
Create Date: 2026-09-16
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "20260916_reimputation"
down_revision = "20260915_tableau_audit"
branch_labels = None
depends_on = None


CODE = "treso.requisitions.reimputer"
DESCRIPTION = "Trésorerie — Réquisitions : corriger le poste budgétaire, même après paiement"

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
