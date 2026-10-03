"""Corriger le poste d'un encaissement : les mêmes rôles qu'annuler.

`20261003_reimput_encaiss` a créé `treso.encaissements.reimputer` et ne l'a
accordé qu'à `admin`. Décision : ce droit suit celui d'annuler un encaissement
(`20260902_annul_secr_compta`) — il appartient à l'**administrateur**, au
**secrétaire exécutif** et au **comptable**. Pas au caissier, qui saisit : celui
qui saisit ne défait pas, et corriger l'imputation d'un encaissement payé, c'est
en défaire une partie. Pas au trésorier non plus, qui valide.

`admin` le porte déjà ; seuls les deux autres rôles sont complétés ici. Les
rôles sont globaux : l'attribution vaut pour toutes les organisations.

Revision ID: 20261003_reimput_enc_roles
Revises: 20261003_reimput_encaiss
Create Date: 2026-10-03
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "20261003_reimput_enc_roles"
down_revision = "20261003_reimput_encaiss"
branch_labels = None
depends_on = None


CODE = "treso.encaissements.reimputer"
# Les rôles qui annulent un encaissement (cf. 20260902_annul_secr_compta).
ROLES = ("secretaire_executif", "comptable")

# `ON CONFLICT DO NOTHING` : rejouer la migration ne doit pas échouer sur une
# attribution déjà faite, ni écraser un retrait décidé depuis.
ACCORDER = """
    INSERT INTO role_permissions (role_id, permission_id)
    SELECT r.id, p.id
    FROM roles r, permissions p
    WHERE r.code = :role AND p.code = :code
    ON CONFLICT DO NOTHING
"""

RETIRER = """
    DELETE FROM role_permissions
    WHERE role_id IN (SELECT id FROM roles WHERE code = :role)
      AND permission_id IN (SELECT id FROM permissions WHERE code = :code)
"""


def instructions(roles: tuple[str, ...] = ROLES) -> list[tuple[str, dict]]:
    """Le SQL de la migration, pour qu'il puisse être éprouvé plutôt que recopié."""
    return [(ACCORDER, {"role": role, "code": CODE}) for role in roles]


def upgrade() -> None:
    bind = op.get_bind()
    for requete, params in instructions():
        bind.execute(text(requete), params)


def downgrade() -> None:
    bind = op.get_bind()
    for role in ROLES:
        bind.execute(text(RETIRER), {"role": role, "code": CODE})
