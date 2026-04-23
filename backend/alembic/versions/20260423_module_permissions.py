"""split menu permissions by module

Revision ID: 20260423_module_permissions
Revises: 20260423_menu_encaissements
Create Date: 2026-04-23
"""

from __future__ import annotations

from alembic import op


revision = "20260423_module_permissions"
down_revision = "20260423_menu_encaissements"
branch_labels = None
depends_on = None


MODULE_PERMISSIONS = [
    ("menu_dashboard", "Accès au tableau de bord"),
    ("menu_encaissements", "Accès au module Encaissements"),
    ("menu_requisitions", "Accès au module Réquisitions"),
    ("menu_remboursement_transport", "Accès au module Remboursement transport"),
    ("menu_requisitions_ocr", "Accès au module Analyse PDF réquisitions"),
    ("menu_validation", "Accès au module Validation"),
    ("menu_validation_examens", "Accès aux dossiers d'examen"),
    ("menu_sorties_fonds", "Accès au module Sorties de fonds"),
    ("menu_cloture_caisse", "Accès au module Clôture de caisse"),
    ("menu_budget", "Accès au module Budget"),
    ("menu_services", "Accès au portail Commission / Services"),
    ("menu_rapports", "Accès au module Rapports"),
    ("menu_audit_logs", "Accès au module Audit système"),
    ("menu_experts_comptables", "Accès au module Experts-comptables"),
    ("menu_historique_imports", "Accès au module Historique des imports"),
    ("menu_settings", "Accès aux paramètres généraux"),
    ("menu_organisation_settings", "Accès aux paramètres Organisation"),
    ("menu_denominations", "Accès à la configuration billets"),
]


def _grant_module_from_permission(source_permission: str, module_permission: str) -> None:
    op.execute(
        f"""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT DISTINCT rp.role_id, module_perm.id
        FROM role_permissions rp
        JOIN permissions source_perm
          ON source_perm.id = rp.permission_id
         AND source_perm.code = '{source_permission}'
        JOIN permissions module_perm
          ON module_perm.code = '{module_permission}'
        ON CONFLICT DO NOTHING;
        """
    )


def upgrade() -> None:
    values = ",\n".join(
        f"('{code}', '{description.replace(chr(39), chr(39) + chr(39))}', NOW())"
        for code, description in MODULE_PERMISSIONS
    )
    op.execute(
        f"""
        INSERT INTO permissions (code, description, created_at)
        VALUES
        {values}
        ON CONFLICT (code) DO UPDATE
        SET description = EXCLUDED.description;
        """
    )

    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permissions p
        WHERE r.code = 'admin'
          AND p.code LIKE 'menu_%'
        ON CONFLICT DO NOTHING;
        """
    )

    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permissions p
        WHERE p.code = 'menu_dashboard'
        ON CONFLICT DO NOTHING;
        """
    )

    _grant_module_from_permission("can_create_requisition", "menu_requisitions")
    _grant_module_from_permission("can_create_requisition", "menu_remboursement_transport")
    _grant_module_from_permission("can_verify_technical", "menu_requisitions")
    _grant_module_from_permission("can_verify_technical", "menu_validation")
    _grant_module_from_permission("can_verify_technical", "menu_validation_examens")
    _grant_module_from_permission("can_validate_final", "menu_requisitions")
    _grant_module_from_permission("can_validate_final", "menu_validation")
    _grant_module_from_permission("can_execute_payment", "menu_sorties_fonds")
    _grant_module_from_permission("can_execute_payment", "menu_cloture_caisse")
    _grant_module_from_permission("can_view_reports", "menu_rapports")
    _grant_module_from_permission("can_view_reports", "menu_audit_logs")
    _grant_module_from_permission("can_view_reports", "menu_budget")
    _grant_module_from_permission("can_view_reports", "menu_experts_comptables")
    _grant_module_from_permission("can_view_reports", "menu_historique_imports")
    _grant_module_from_permission("can_edit_settings", "menu_settings")
    _grant_module_from_permission("can_edit_settings", "menu_organisation_settings")
    _grant_module_from_permission("can_edit_settings", "menu_denominations")
    _grant_module_from_permission("can_manage_users", "menu_settings")
    _grant_module_from_permission("menu_mon_espace", "menu_services")
    _grant_module_from_permission("can_view_all_services", "menu_requisitions")
    _grant_module_from_permission("can_view_all_services", "menu_remboursement_transport")
    _grant_module_from_permission("can_view_all_services", "menu_requisitions_ocr")
    _grant_module_from_permission("can_view_all_services", "menu_validation")
    _grant_module_from_permission("can_view_all_services", "menu_validation_examens")
    _grant_module_from_permission("can_view_all_services", "menu_budget")
    _grant_module_from_permission("can_view_all_services", "menu_services")
    _grant_module_from_permission("can_view_all_services", "menu_rapports")
    _grant_module_from_permission("can_view_all_services", "menu_audit_logs")
    _grant_module_from_permission("can_view_all_services", "menu_experts_comptables")
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE permission_id IN (
            SELECT id FROM permissions WHERE code = 'menu_mon_espace'
        );
        """
    )
    op.execute("DELETE FROM permissions WHERE code = 'menu_mon_espace';")


def downgrade() -> None:
    codes = ", ".join(f"'{code}'" for code, _ in MODULE_PERMISSIONS)
    op.execute(
        f"""
        DELETE FROM role_permissions
        WHERE permission_id IN (
            SELECT id FROM permissions WHERE code IN ({codes})
        );
        """
    )
    op.execute(f"DELETE FROM permissions WHERE code IN ({codes});")
