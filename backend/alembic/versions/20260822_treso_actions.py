"""droits d'action Trésorerie + régularisation menu_comptabilite et secretariat.tableau

Trois choses, dans cet ordre.

1. **Semer 24 droits d'action Trésorerie** (`treso.<menu>.<action>`). Le catalogue
   ne retient que les actions qui correspondent à une route HTTP réellement
   identifiable, aujourd'hui gardée par le seul code de menu (ou par rien du
   tout). Un code semé mais jamais évalué côté API est une fausse promesse de
   sécurité : le dépôt en porte déjà plusieurs (cf. les 7 `secretariat.tableau.*`
   ci-dessous), on n'en ajoute pas.

2. **Rétro-accorder**. C'est le point critique de cette révision. Chaque nouveau
   code est accordé à tout rôle qui détient déjà la permission qui *autorise
   aujourd'hui* la même action — pas au hasard `menu_<x>`, mais la source réelle
   relevée endpoint par endpoint (table RETRO_GRANTS). Conséquence recherchée :
   au déploiement, **le comportement observable est strictement inchangé** ;
   personne ne perd un accès. Les gardes fines (`has_permission("treso.…")`) sont
   posées dans un second temps, endpoint par endpoint, sur une base déjà peuplée.
   C'est exactement la technique de `_grant_module_from_permission`
   (20260423_module_permissions), et le correctif appliqué deux fois déjà par
   20260725_grant_authorize_disb et 20260813_view_cancelled_ops après que des
   octrois dérivés d'un code source inexistant se soient révélés être des no-op.

   Trois exports font exception et sont signalés comme tels : `/exports/budget`,
   `/exports/sorties-fonds` et `/exports/experts-comptables` ne portent AUCUNE
   garde aujourd'hui (exports.py:477, :1342, :1868), pas plus que la lecture de
   l'annuaire des experts (experts.py:315, :473). Les rétro-accorder depuis le
   code de menu correspondant est un durcissement volontaire : en phase 2, un
   utilisateur qui n'a pas le menu perdra un accès qu'il n'aurait jamais dû avoir.

3. **Régulariser deux dettes relevées à l'audit**, sans quoi la matrice continue
   de mentir :
   - `menu_comptabilite` est déclaré dans MODULE_PERMISSION_MAP
     (core/permissions.py:24) mais aucune des 228 migrations ne l'insère.
     `/permissions/menu` ne peut donc jamais renvoyer le menu `comptabilite` à un
     non-admin. On le sème et on l'accorde à tout rôle portant un code `compta.*`
     — ce qui reproduit exactement ce que fait déjà Layout.tsx:268-280.
   - Les 7 `secretariat.tableau.*` sont exigés sur 15 routes
     (modules/secretariat/tableau/router.py:40-46) et déclarés dans
     SECRETARIAT_PERMISSIONS, mais jamais semés. 20260605_sec_roles:43-48 croit
     les accorder via `JOIN permissions p ON p.code IN (...)` : 0 ligne jointe,
     no-op silencieux. L'effet net n'est pas un blocage mais une SUR-ATTRIBUTION,
     car `secretariat.view` figure dans chacune des listes `has_any_permission`.
     On les sème et on les accorde à tout porteur de `secretariat.view` : c'est
     précisément l'ensemble qui peut déjà tout faire. La granularité ne devient
     réelle qu'une fois `secretariat.view` retiré des listes VIEW_PERMS &c. —
     et ce retrait est alors sans régression.

Idempotente : ON CONFLICT (code) DO UPDATE sur les permissions,
ON CONFLICT DO NOTHING sur les attributions.

Revision ID: 20260822_treso_actions
Revises: 20260820_secretaire_exec
Create Date: 2026-08-22
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

from app.modules.secretariat.permissions import (
    SECRETARIAT_PERMISSION_DESCRIPTIONS,
    SECRETARIAT_TABLEAU_PERMISSION_CODES,
)


revision = "20260822_treso_actions"
down_revision = "20260820_secretaire_exec"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# 1. Nouveaux droits d'action Trésorerie
#
# Chaque entrée cite la ou les routes qu'elle a vocation à garder en phase 2.
# Pas de route identifiable => pas de code. C'est le seul critère d'admission.
# ---------------------------------------------------------------------------

TRESO_PERMISSIONS: list[tuple[str, str]] = [
    # Encaissements — encaissements.py:64 met TOUT le routeur derrière
    # menu_encaissements : lire, saisir et supprimer sont aujourd'hui un seul et
    # même droit. C'est le besoin métier n°1 (« la caissière saisit, la
    # secrétaire consulte »).
    ("treso.encaissements.create", "Trésorerie — Encaissements : enregistrer un encaissement ou une proforma"),
    ("treso.encaissements.delete", "Trésorerie — Encaissements : supprimer ou restaurer un encaissement"),
    ("treso.encaissements.export", "Trésorerie — Encaissements : exporter la liste"),
    # Réquisitions — PUT /{id} (requisitions.py:1685) et POST /{id}/soft-delete
    # (:2132) ne portent que get_current_user : modifier ou supprimer une
    # réquisition déposée n'est gardé par rien.
    ("treso.requisitions.update", "Trésorerie — Réquisitions : modifier une réquisition déposée"),
    ("treso.requisitions.delete", "Trésorerie — Réquisitions : supprimer ou restaurer une réquisition"),
    ("treso.requisitions.export", "Trésorerie — Réquisitions : exporter le registre"),
    # Sorties de fonds — préparer une sortie (POST /drafts :744, POST "" :856)
    # n'est pas l'exécuter (can_execute_payment). L'export (:1342) est nu.
    ("treso.sorties_fonds.create", "Trésorerie — Sorties de fonds : préparer une sortie ou un brouillon"),
    ("treso.sorties_fonds.export", "Trésorerie — Sorties de fonds : exporter le journal des décaissements"),
    # Budget — le module a un CRUD complet et ZÉRO granularité : router.py:126
    # pose has_permission("budget") sur l'ensemble, et budget.py n'ajoute rien.
    ("treso.budget.create", "Trésorerie — Budget : créer une ligne, un poste ou un exercice"),
    ("treso.budget.update", "Trésorerie — Budget : modifier une ligne ou un poste"),
    ("treso.budget.delete", "Trésorerie — Budget : supprimer une ligne ou un poste"),
    ("treso.budget.validate", "Trésorerie — Budget : ouvrir ou clôturer un exercice budgétaire"),
    ("treso.budget.export", "Trésorerie — Budget : exporter le budget"),
    # Dossiers d'examen — can_verify_technical est partagé avec le circuit des
    # réquisitions (dossiers_requisition.py:875, :950) : on ne peut pas confier
    # les dossiers sans confier les réquisitions.
    ("treso.validation_examens.create", "Trésorerie — Dossiers d'examen : ouvrir un dossier"),
    ("treso.validation_examens.update", "Trésorerie — Dossiers d'examen : modifier un dossier ou sa composition"),
    ("treso.validation_examens.delete", "Trésorerie — Dossiers d'examen : supprimer un dossier"),
    ("treso.validation_examens.validate", "Trésorerie — Dossiers d'examen : valider ou rejeter un dossier"),
    # Remboursement transport — le code de menu ouvre la lecture ET la création
    # (remboursements_transport.py:161 vs :312).
    ("treso.remboursement_transport.create", "Trésorerie — Remboursement transport : créer une demande ou des participants"),
    # Clôture de caisse / Audit — seuls les exports méritent un code : le reste
    # est déjà réparti entre le code de menu (lecture) et can_execute_payment
    # (actes de caisse).
    ("treso.cloture_caisse.export", "Trésorerie — Clôture de caisse : exporter les clôtures"),
    ("treso.audit_logs.export", "Trésorerie — Audit système : exporter les journaux"),
    # Unités opérationnelles — services.py:403 et :493 sont gardés par
    # has_permission("budget") : créer ou modifier une unité exige aujourd'hui le
    # menu Budget, ce qui n'a aucun sens fonctionnel.
    ("treso.services.create", "Trésorerie — Unités opérationnelles : créer une unité"),
    ("treso.services.update", "Trésorerie — Unités opérationnelles : modifier une unité"),
    # Experts-comptables — experts.py:315 et :473 n'exigent que get_current_user :
    # tout utilisateur authentifié du tenant lit l'annuaire nominatif de l'Ordre.
    ("treso.experts_comptables.read", "Trésorerie — Experts-comptables : consulter l'annuaire"),
    ("treso.experts_comptables.export", "Trésorerie — Experts-comptables : exporter le tableau de l'Ordre"),
]


# ---------------------------------------------------------------------------
# 2. Régularisations (codes exigés par le code applicatif, jamais semés)
# ---------------------------------------------------------------------------

MENU_COMPTABILITE: tuple[str, str] = ("menu_comptabilite", "Accès au module Comptabilité")

TABLEAU_PERMISSIONS: list[tuple[str, str]] = [
    (code, SECRETARIAT_PERMISSION_DESCRIPTIONS[code])
    for code in SECRETARIAT_TABLEAU_PERMISSION_CODES
]

ALL_PERMISSIONS: list[tuple[str, str]] = [*TRESO_PERMISSIONS, MENU_COMPTABILITE, *TABLEAU_PERMISSIONS]

COMPTA_SOURCE_CODES = [
    "compta.lecture",
    "compta.saisie",
    "compta.validation",
    "compta.cloture",
    "compta.parametrage",
    "compta.export",
]


# ---------------------------------------------------------------------------
# 3. Rétro-attribution : nouveau code <- permission(s) qui autorisent DÉJÀ
#    la même action. Relevé endpoint par endpoint ; ne pas modifier sans
#    revérifier la garde effective, sous peine de retirer un accès en place.
# ---------------------------------------------------------------------------

RETRO_GRANTS: list[tuple[str, list[str]]] = [
    # encaissements.py:64 — routeur entier derrière menu_encaissements
    ("treso.encaissements.create", ["menu_encaissements"]),
    ("treso.encaissements.delete", ["menu_encaissements"]),
    ("treso.encaissements.export", ["menu_encaissements"]),  # exports.py:1061
    # requisitions.py:1685 / :2132 sans garde ; le porteur légitime est le menu
    # ou le demandeur (can_create_requisition).
    ("treso.requisitions.update", ["menu_requisitions", "can_create_requisition"]),
    ("treso.requisitions.delete", ["menu_requisitions", "can_create_requisition"]),
    ("treso.requisitions.export", ["menu_requisitions"]),  # exports.py:1635
    # router.py:112 — has_permission("sorties_fonds") sur tout le routeur
    ("treso.sorties_fonds.create", ["menu_sorties_fonds"]),
    ("treso.sorties_fonds.export", ["menu_sorties_fonds"]),  # exports.py:1342 : NU
    # router.py:126 — has_permission("budget") sur tout le routeur
    ("treso.budget.create", ["menu_budget"]),
    ("treso.budget.update", ["menu_budget"]),
    ("treso.budget.delete", ["menu_budget"]),
    ("treso.budget.validate", ["menu_budget"]),
    ("treso.budget.export", ["menu_budget"]),  # exports.py:477 : NU
    # router.py:110 — has_any_permission(["validation_examens","requisitions","services"])
    # Les trois sources doivent être reprises, sinon on retire l'accès aux
    # porteurs de menu_requisitions ou menu_services.
    ("treso.validation_examens.create", ["menu_validation_examens", "menu_requisitions", "menu_services"]),
    ("treso.validation_examens.update", ["menu_validation_examens", "menu_requisitions", "menu_services"]),
    ("treso.validation_examens.delete", ["menu_validation_examens", "menu_requisitions", "menu_services"]),
    # dossiers_requisition.py:875, :950
    ("treso.validation_examens.validate", ["can_verify_technical"]),
    # remboursements_transport.py:312 — has_any_permission([...,"menu_services"])
    ("treso.remboursement_transport.create", ["menu_remboursement_transport", "menu_services"]),
    # clotures.py:503 / audit_logs.py:164, :237
    ("treso.cloture_caisse.export", ["menu_cloture_caisse"]),
    ("treso.audit_logs.export", ["menu_audit_logs"]),
    # services.py:403, :493 — gardés (à tort) par has_permission("budget")
    ("treso.services.create", ["menu_budget"]),
    ("treso.services.update", ["menu_budget"]),
    # experts.py:315, :473 et exports.py:1868 : NUS. Le menu est le porteur sain.
    ("treso.experts_comptables.read", ["menu_experts_comptables"]),
    ("treso.experts_comptables.export", ["menu_experts_comptables"]),
    # Layout.tsx:268-280 fait déjà apparaître le menu Comptabilité sur les
    # codes compta.* : on aligne la base sur le comportement observé.
    (MENU_COMPTABILITE[0], COMPTA_SOURCE_CODES),
] + [
    # Sur-attribution constatée : secretariat.view figure dans chaque liste
    # has_any_permission de tableau/router.py, donc ses porteurs peuvent déjà
    # importer, analyser, comparer, générer et exporter.
    (code, ["secretariat.view"])
    for code in SECRETARIAT_TABLEAU_PERMISSION_CODES
]


def _seed_permissions() -> None:
    bind = op.get_bind()
    for code, description in ALL_PERMISSIONS:
        bind.execute(
            text(
                "INSERT INTO permissions (code, description, created_at) "
                "VALUES (:code, :description, NOW()) "
                "ON CONFLICT (code) DO UPDATE SET description = EXCLUDED.description"
            ),
            {"code": code, "description": description},
        )


def _grant_from_sources(target_code: str, source_codes: list[str]) -> None:
    """Accorde `target_code` à tout rôle détenant l'une des `source_codes`."""
    op.get_bind().execute(
        text(
            """
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT DISTINCT rp.role_id, target.id
            FROM role_permissions rp
            JOIN permissions source
              ON source.id = rp.permission_id
             AND source.code = ANY(:source_codes)
            JOIN permissions target
              ON target.code = :target_code
            ON CONFLICT DO NOTHING
            """
        ),
        {"source_codes": source_codes, "target_code": target_code},
    )


def _grant_to_admin_role() -> None:
    """Le rôle `admin` porte les nouveaux codes, comme pour RH et Secrétariat.

    Sans effet sur l'autorisation runtime (deps.py:550-553 court-circuite sur la
    chaîne users.role), mais la matrice de l'écran Rôles reflète alors l'état
    réel de la base.
    """
    op.get_bind().execute(
        text(
            """
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT r.id, p.id
            FROM roles r
            JOIN permissions p ON p.code = ANY(:codes)
            WHERE r.code = 'admin'
            ON CONFLICT DO NOTHING
            """
        ),
        {"codes": [code for code, _ in ALL_PERMISSIONS]},
    )


def upgrade() -> None:
    _seed_permissions()
    for target_code, source_codes in RETRO_GRANTS:
        _grant_from_sources(target_code, source_codes)
    _grant_to_admin_role()


def downgrade() -> None:
    bind = op.get_bind()
    codes = [code for code, _ in ALL_PERMISSIONS]
    # role_permissions serait purgée par la cascade FK, mais les migrations du
    # dépôt la vident explicitement : on garde la convention.
    bind.execute(
        text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE code = ANY(:codes))"
        ),
        {"codes": codes},
    )
    bind.execute(text("DELETE FROM permissions WHERE code = ANY(:codes)"), {"codes": codes})
