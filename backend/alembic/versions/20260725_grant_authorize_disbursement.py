"""Accorde can_authorize_disbursement aux rôles qui créent les réquisitions.

La migration d'origine (20260719_decaissement_progressif) tentait d'accorder
`can_authorize_disbursement` aux rôles disposant d'une permission de code
`requisitions` — code qui n'existe pas (les codes réels sont
`can_create_requisition` / `menu_requisitions`). Résultat : la permission
n'était accordée à aucun rôle, et seuls les admins pouvaient autoriser une
tranche de décaissement progressif.

Cette révision corrige durablement l'attribution en la reliant au vrai marqueur
« demandeur » : `can_create_requisition`. Combinée à la règle métier
(créateur de la réquisition OU admin), elle permet à un demandeur d'autoriser
les tranches de SES propres réquisitions.

Idempotente (ON CONFLICT DO NOTHING) : sans effet si déjà accordée.

Revision ID: 20260725_grant_authorize_disb
Create Date: 2026-07-25
"""

from alembic import op


revision = "20260725_grant_authorize_disb"
down_revision = "20260723c_merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT DISTINCT rp.role_id, target.id
        FROM role_permissions rp
        JOIN permissions source
          ON source.id = rp.permission_id
         AND source.code = 'can_create_requisition'
        JOIN permissions target
          ON target.code = 'can_authorize_disbursement'
        ON CONFLICT DO NOTHING;
        """
    )


def downgrade() -> None:
    # On retire l'attribution uniquement pour les rôles « demandeur » ; on laisse
    # d'éventuelles attributions manuelles faites via l'interface des rôles.
    op.execute(
        """
        DELETE FROM role_permissions rp
        USING permissions target
        WHERE rp.permission_id = target.id
          AND target.code = 'can_authorize_disbursement'
          AND rp.role_id IN (
              SELECT rp2.role_id
              FROM role_permissions rp2
              JOIN permissions source ON source.id = rp2.permission_id
              WHERE source.code = 'can_create_requisition'
          );
        """
    )
