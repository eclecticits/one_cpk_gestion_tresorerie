"""Corriger le poste d'un encaissement : l'administrateur ne l'a plus d'office.

`treso.encaissements.reimputer` devient une permission à attribution explicite
(`PERMISSIONS_EXPLICITES`, app/core/permissions.py) : le court-circuit `admin`
ne l'ouvre plus, et elle se règle rôle par rôle dans Paramètres → Permissions,
rôle Administrateur compris. On retire donc l'attribution que
`20261003_reimput_encaiss` avait faite au rôle `admin`. Le secrétaire exécutif
et le comptable la gardent (`20261003_reimput_enc_roles`).

Revision ID: 20261003_reimput_explicite
Revises: 20261003_reimput_enc_roles
Create Date: 2026-10-03
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "20261003_reimput_explicite"
down_revision = "20261003_reimput_enc_roles"
branch_labels = None
depends_on = None


CODE = "treso.encaissements.reimputer"
ROLE = "admin"

RETIRER = """
    DELETE FROM role_permissions
    WHERE role_id IN (SELECT id FROM roles WHERE code = :role)
      AND permission_id IN (SELECT id FROM permissions WHERE code = :code)
"""

ACCORDER = """
    INSERT INTO role_permissions (role_id, permission_id)
    SELECT r.id, p.id
    FROM roles r, permissions p
    WHERE r.code = :role AND p.code = :code
    ON CONFLICT DO NOTHING
"""


def upgrade() -> None:
    op.get_bind().execute(text(RETIRER), {"role": ROLE, "code": CODE})


def downgrade() -> None:
    op.get_bind().execute(text(ACCORDER), {"role": ROLE, "code": CODE})
