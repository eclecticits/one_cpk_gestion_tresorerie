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
    "tableau": "menu_tableau",
}

ALL_MENUS = list(MODULE_PERMISSION_MAP.keys())


def resolve_permission_code(permission_code: str) -> str:
    return MODULE_PERMISSION_MAP.get(permission_code, permission_code)


# Terminer ou rejeter l'examen d'une réquisition ou d'un dossier. L'écran des
# permissions propose « Dossiers d'examen → Valider un dossier d'examen » : sans
# ce code, la case s'enregistrait sans rien ouvrir, et seul « Validation → Avis
# technique » donnait réellement le droit.
EXAMEN_VALIDATION_PERMISSIONS: tuple[str, ...] = ("can_verify_technical", "treso.validation_examens.validate")


# Permissions à attribution explicite. L'administrateur ne les tient PAS de son
# rôle : le court-circuit `admin` de `has_permission` les ignore, et elles ne
# s'obtiennent qu'en étant cochées pour le rôle dans Paramètres → Permissions —
# rôle Administrateur compris, qui devient réglable pour elles seules.
# Le super-administrateur, qui règle ces permissions, garde son court-circuit.
#
# Y figurent les corrections qui déplacent du réalisé déjà encaissé : on décide
# qui les porte, on ne les reçoit pas par défaut de fonction.
PERMISSIONS_EXPLICITES: frozenset[str] = frozenset({
    "treso.encaissements.reimputer",
})


def est_permission_explicite(permission_code: str) -> bool:
    return resolve_permission_code(permission_code) in PERMISSIONS_EXPLICITES
