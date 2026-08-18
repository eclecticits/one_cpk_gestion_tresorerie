"""Accorde view_cancelled_financial_operations aux rôles qui voient les modules financiers.

Annuler un encaissement ou une sortie n'efface rien : l'opération passe à
`statut_operation = 'ANNULEE'` et reste en base avec son motif. Mais la liste
filtre sur `ACTIVE` par défaut, et les options « Annulés » / « Tous » sont
conditionnées à `view_cancelled_financial_operations`. Or cette permission
n'était rattachée à aucun rôle réel — seulement aux rôles `load_test_*` issus
d'une campagne de charge. Conséquence : hors admin (qui bénéficie du bypass
`role in {admin, super_admin}`), l'historique des opérations annulées était
inaccessible.

L'attribution est dérivée des marqueurs d'accès au module (`menu_encaissements`,
`menu_sorties_fonds`) et non de `cancel_encaissement` : ce dernier n'est lui non
plus porté par aucun rôle réel, si bien qu'en partir n'accorderait rien — c'est
exactement l'écueil corrigé par 20260725_grant_authorize_disb.

Consulter une opération annulée est une lecture : le tableau l'affiche barrée,
avec son badge « Annulé » et son motif, actions désactivées.

Idempotente (ON CONFLICT DO NOTHING) : sans effet si déjà accordée.

Revision ID: 20260813_view_cancelled_ops
Create Date: 2026-08-13
"""

from alembic import op


revision = "20260813_view_cancelled_ops"
down_revision = "20260813_budget_comment_edit"
branch_labels = None
depends_on = None


SOURCE_CODES = "('menu_encaissements', 'menu_sorties_fonds')"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT DISTINCT rp.role_id, target.id
        FROM role_permissions rp
        JOIN permissions source
          ON source.id = rp.permission_id
         AND source.code IN {SOURCE_CODES}
        JOIN permissions target
          ON target.code = 'view_cancelled_financial_operations'
        ON CONFLICT DO NOTHING;
        """
    )


def downgrade() -> None:
    # On ne retire que les attributions dérivées des marqueurs de module ; une
    # attribution faite à la main via l'écran des rôles survit au downgrade.
    op.execute(
        f"""
        DELETE FROM role_permissions rp
        USING permissions target
        WHERE rp.permission_id = target.id
          AND target.code = 'view_cancelled_financial_operations'
          AND rp.role_id IN (
              SELECT rp2.role_id
              FROM role_permissions rp2
              JOIN permissions source ON source.id = rp2.permission_id
              WHERE source.code IN {SOURCE_CODES}
          );
        """
    )
