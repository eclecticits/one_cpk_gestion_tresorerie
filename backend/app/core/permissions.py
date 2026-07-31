from __future__ import annotations


MODULE_PERMISSION_MAP: dict[str, str] = {
    "dashboard": "menu_dashboard",
    "encaissements": "menu_encaissements",
    "requisitions": "menu_requisitions",
    "remboursement_transport": "menu_remboursement_transport",
    "requisitions_ocr": "menu_requisitions_ocr",
    "validation": "menu_validation",
    "validation_examens": "menu_validation_examens",
    "sorties_fonds": "menu_sorties_fonds",
    "cloture_caisse": "menu_cloture_caisse",
    "budget": "menu_budget",
    "services": "menu_services",
    "rapports": "menu_rapports",
    "audit_logs": "menu_audit_logs",
    "experts_comptables": "menu_experts_comptables",
    "historique_imports": "menu_historique_imports",
    "settings": "menu_settings",
    "organisation_settings": "menu_organisation_settings",
    "denominations": "menu_denominations",
    "secretariat": "menu_secretariat",
    "comptabilite": "menu_comptabilite",
}

ALL_MENUS = list(MODULE_PERMISSION_MAP.keys())


def resolve_permission_code(permission_code: str) -> str:
    return MODULE_PERMISSION_MAP.get(permission_code, permission_code)
