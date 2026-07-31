"""Module Comptabilité — RBAC dédié (Lot 1)

Ajoute les permissions et rôles comptables. Matrice actée :
- Comptable      : saisie de brouillons, lecture.
- Chef comptable : saisie, validation des écritures, lecture.
- DAF            : saisie, validation, clôture/verrouillage des exercices,
                    paramétrage du référentiel, lecture.
- Auditeur       : lecture seule (Grand Livre, balances, états).
- CAC            : lecture seule + export des états financiers.

Les permissions et rôles sont globaux (non tenant-scopés, comme le reste du
RBAC existant) ; leur attribution à un utilisateur se fait via `users.role_id`,
propre à chaque organisation.

Revision ID: 20260731_compta_rbac
Revises: 20260731_compta_fondations
Create Date: 2026-07-31
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "20260731_compta_rbac"
down_revision = "20260731_compta_fondations"
branch_labels = None
depends_on = None


PERMISSIONS: list[tuple[str, str]] = [
    ("compta.saisie", "Comptabilité — créer et modifier des écritures en brouillon"),
    ("compta.validation", "Comptabilité — valider les écritures (contrôle d'équilibre, numérotation)"),
    ("compta.cloture", "Comptabilité — gérer les exercices et périodes (ouverture, clôture, verrouillage)"),
    ("compta.parametrage", "Comptabilité — gérer le référentiel, le plan comptable et les journaux"),
    ("compta.lecture", "Comptabilité — consulter le Grand Livre, les balances et les états financiers"),
    ("compta.export", "Comptabilité — exporter les états financiers"),
]

# code de rôle -> libellé, description, permissions accordées
ROLES: list[tuple[str, str, str, list[str]]] = [
    (
        "comptable",
        "Comptable",
        "Saisie des écritures comptables au quotidien.",
        ["compta.saisie", "compta.lecture"],
    ),
    (
        "chef_comptable",
        "Chef comptable",
        "Valide les écritures saisies par les comptables.",
        ["compta.saisie", "compta.validation", "compta.lecture"],
    ),
    (
        "daf",
        "Directeur Administratif et Financier",
        "Pilotage complet : validation, clôture des exercices, paramétrage du plan comptable.",
        ["compta.saisie", "compta.validation", "compta.cloture", "compta.parametrage", "compta.lecture"],
    ),
    (
        "auditeur_comptable",
        "Auditeur",
        "Lecture seule des écritures, du Grand Livre et des balances.",
        ["compta.lecture"],
    ),
    (
        "cac",
        "Commissaire aux comptes",
        "Lecture seule et export des états financiers pour la certification.",
        ["compta.lecture", "compta.export"],
    ),
]


def upgrade() -> None:
    bind = op.get_bind()

    for code, description in PERMISSIONS:
        bind.execute(
            text(
                "INSERT INTO permissions (code, description, created_at) "
                "VALUES (:code, :description, NOW()) ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "description": description},
        )

    for code, label, description, perm_codes in ROLES:
        bind.execute(
            text(
                "INSERT INTO roles (code, label, description, created_at) "
                "VALUES (:code, :label, :description, NOW()) ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "label": label, "description": description},
        )
        bind.execute(
            text(
                """
                INSERT INTO role_permissions (role_id, permission_id)
                SELECT r.id, p.id
                FROM roles r
                CROSS JOIN permissions p
                WHERE r.code = :code AND p.code = ANY(:perm_codes)
                ON CONFLICT DO NOTHING
                """
            ),
            {"code": code, "perm_codes": perm_codes},
        )


def downgrade() -> None:
    bind = op.get_bind()
    role_codes = [code for code, *_ in ROLES]
    perm_codes = [code for code, _ in PERMISSIONS]

    bind.execute(
        text(
            """
            DELETE FROM role_permissions
            WHERE role_id IN (SELECT id FROM roles WHERE code = ANY(:role_codes))
               OR permission_id IN (SELECT id FROM permissions WHERE code = ANY(:perm_codes))
            """
        ),
        {"role_codes": role_codes, "perm_codes": perm_codes},
    )
    # Ne détache que les utilisateurs qui n'ont pas d'autre lien fonctionnel :
    # laisser role_id pointer vers un rôle supprimé casserait leurs permissions
    # sans prévenir. On préfère échouer explicitement si des comptes existent.
    bind.execute(
        text(
            """
            DO $$
            DECLARE
                v_count integer;
            BEGIN
                SELECT count(*) INTO v_count FROM users WHERE role_id IN (
                    SELECT id FROM roles WHERE code = ANY(:role_codes)
                );
                IF v_count > 0 THEN
                    RAISE EXCEPTION
                        'Downgrade impossible : % utilisateur(s) ont encore un rôle comptable assigné.',
                        v_count;
                END IF;
            END $$;
            """
        ).bindparams(role_codes=role_codes),
    )
    bind.execute(text("DELETE FROM roles WHERE code = ANY(:role_codes)"), {"role_codes": role_codes})
    bind.execute(text("DELETE FROM permissions WHERE code = ANY(:perm_codes)"), {"perm_codes": perm_codes})
