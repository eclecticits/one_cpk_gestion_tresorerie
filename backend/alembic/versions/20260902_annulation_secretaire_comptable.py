"""Qui peut annuler une opération financière : le secrétaire exécutif et le comptable.

`20260428_fin_cancel` a créé `cancel_sortie_fonds` et `cancel_encaissement`
sans les attribuer à aucun rôle. Seul `admin` les a reçues depuis, si bien que
toute erreur de saisie remontait à un administrateur.

Décision : l'annulation appartient à l'**administrateur**, au **secrétaire
exécutif** et au **comptable**. Elle n'appartient pas au caissier — celui qui
saisit ne défait pas — ni au trésorier, qui valide.

`admin` porte déjà les deux codes ; seuls les deux autres rôles sont complétés
ici. Tous trois ont déjà `menu_sorties_fonds`, `menu_encaissements` et
`view_cancelled_financial_operations` : ils pourront donc relire ce qu'ils
annulent, ce qu'un droit d'annuler sans droit de voir ne permettrait pas.

Les rôles sont **globaux** (pas de colonne `organisation_id`) : l'attribution
vaut pour toutes les organisations.

Revision ID: 20260902_annul_secr_compta
Revises: 20260901_transferts_document
"""

from __future__ import annotations

from alembic import op


revision = "20260902_annul_secr_compta"
down_revision = "20260901_transferts_document"
branch_labels = None
depends_on = None

ROLES = ("secretaire_executif", "comptable")
PERMISSIONS = ("cancel_sortie_fonds", "cancel_encaissement")


def upgrade() -> None:
    for role_code in ROLES:
        for permission_code in PERMISSIONS:
            op.execute(
                f"""
                INSERT INTO role_permissions (role_id, permission_id)
                SELECT r.id, p.id
                FROM roles r, permissions p
                WHERE r.code = '{role_code}' AND p.code = '{permission_code}'
                ON CONFLICT DO NOTHING;
                """
            )


def downgrade() -> None:
    roles = ", ".join(f"'{code}'" for code in ROLES)
    permissions = ", ".join(f"'{code}'" for code in PERMISSIONS)
    op.execute(
        f"""
        DELETE FROM role_permissions
        WHERE role_id IN (SELECT id FROM roles WHERE code IN ({roles}))
          AND permission_id IN (SELECT id FROM permissions WHERE code IN ({permissions}));
        """
    )
