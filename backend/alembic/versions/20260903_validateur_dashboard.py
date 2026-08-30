"""Le validateur voit le tableau de bord.

Le rôle `validateur` — le plus nombreux de la plateforme — n'avait pas
`menu_dashboard`. Sur la racine, `ServiceAwareDashboard` le renvoyait donc vers
`/services/mon-espace/<id>`, la page « Unité opérationnelle », faute de mieux à
lui montrer. Chaque retour à l'accueil le déposait là, et il n'avait aucun
moyen d'atteindre le tableau de bord.

Ce rebond n'était pas un défaut de code : c'était le code qui disait
correctement une absence de droit. La corriger relève donc des permissions.

Les rôles `agent_documents`, `assistant_e_admin` et `president_e_commission`
sont dans le même cas et NE sont PAS traités ici : leur situation n'a pas été
tranchée, et leur accorder le tableau de bord au passage serait décider à la
place de quelqu'un.

Revision ID: 20260903_validateur_dash
Revises: 20260902_annul_secr_compta
"""

from __future__ import annotations

from alembic import op


revision = "20260903_validateur_dash"
down_revision = "20260902_annul_secr_compta"
branch_labels = None
depends_on = None

ROLE = "validateur"
PERMISSION = "menu_dashboard"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r, permissions p
        WHERE r.code = '{ROLE}' AND p.code = '{PERMISSION}'
        ON CONFLICT DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM role_permissions
        WHERE role_id = (SELECT id FROM roles WHERE code = '{ROLE}')
          AND permission_id = (SELECT id FROM permissions WHERE code = '{PERMISSION}');
        """
    )
