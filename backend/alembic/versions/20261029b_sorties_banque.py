"""Sorties par banque : permission distincte, retirée à la caisse.

Une sortie qui débite un compte bancaire — y compris l'approvisionnement de la
caisse, qui part de la banque — ne doit être ni vue ni exécutée par la caisse.
Jusqu'ici `menu_sorties_fonds` et `can_execute_payment` ouvraient les deux
canaux d'un même geste.

`sorties_fonds_banque` est accordée à chaque rôle qui exécute déjà des sorties
(`can_execute_payment`), sauf au caissier : rien ne change pour les autres, la
caisse perd la banque. Les administrateurs la tiennent d'office (court-circuit
`admin` de `_user_has_permission`).

Idempotente (ON CONFLICT DO NOTHING).

Revision ID: 20261029b_sorties_banque
Revises: 20261029a_ordre_direct_a_valoir
Create Date: 2026-10-29
"""

from alembic import op


revision = "20261029b_sorties_banque"
down_revision = "20261029a_ordre_direct_a_valoir"
branch_labels = None
depends_on = None


CODE = "sorties_fonds_banque"
DESCRIPTION = "Voir et exécuter les sorties par banque"
# `tresorerie` est l'ancien code du caissier (cf. LEGACY_ROLE_CODE_MAP).
ROLES_CAISSE = "('caissier', 'tresorerie')"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO permissions (code, description, created_at)
        VALUES ('{CODE}', '{DESCRIPTION}', NOW())
        ON CONFLICT (code) DO UPDATE SET description = EXCLUDED.description;
        """
    )
    op.execute(
        f"""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT DISTINCT rp.role_id, target.id
        FROM role_permissions rp
        JOIN permissions source
          ON source.id = rp.permission_id
         AND source.code = 'can_execute_payment'
        JOIN roles r ON r.id = rp.role_id
        JOIN permissions target ON target.code = '{CODE}'
        WHERE lower(r.code) NOT IN {ROLES_CAISSE}
        ON CONFLICT DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM role_permissions
        WHERE permission_id IN (SELECT id FROM permissions WHERE code = '{CODE}');
        """
    )
    op.execute(f"DELETE FROM permissions WHERE code = '{CODE}';")
