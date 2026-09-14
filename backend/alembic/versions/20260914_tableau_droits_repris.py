"""Rend explicites les droits Tableau qu'une simple consultation suffisait à exercer.

Jusqu'ici les routes du Tableau acceptaient « secretariat.tableau.view » à la
place du droit correspondant : un rôle qui pouvait consulter pouvait aussi
importer, analyser, comparer, exporter, générer un rapport ou un PV et
enregistrer une décision. Les routes exigent désormais chacune leur droit.

Sans reprise, le durcissement retirerait en silence des capacités que des rôles
exercent aujourd'hui. Cette migration ne fait donc qu'écrire ce qui était déjà
vrai : chaque rôle qui détient « secretariat.tableau.view » reçoit les droits
qu'il exerçait par ce biais. Ils deviennent visibles dans l'arbre des
permissions — et, pour la première fois, retirables un à un.

« secretariat.tableau.correct » n'y figure pas : la correction d'un dossier
n'existait pas avant, elle reste réservée aux rôles à qui on l'accorde.

Revision ID: 20260914_tableau_droits_repris
Revises: 20260914_tableau_snapshot
Create Date: 2026-09-14
"""

from __future__ import annotations

from alembic import op


revision = "20260914_tableau_droits_repris"
down_revision = "20260914_tableau_snapshot"
branch_labels = None
depends_on = None


# Droits que « secretariat.tableau.view » ouvrait de fait avant le durcissement.
DROITS_REPRIS = (
    "secretariat.tableau.import",
    "secretariat.tableau.analyze",
    "secretariat.tableau.compare",
    "secretariat.tableau.generate_report",
    "secretariat.tableau.generate_pv",
    "secretariat.tableau.export",
    "secretariat.tableau.decide",
)


REPRISE = """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT consultants.role_id, p.id
          FROM (
              SELECT rp.role_id
                FROM role_permissions rp
                JOIN permissions v ON v.id = rp.permission_id
               WHERE v.code = 'secretariat.tableau.view'
          ) AS consultants
          JOIN permissions p ON p.code IN ({codes})
         WHERE NOT EXISTS (
             SELECT 1
               FROM role_permissions deja
              WHERE deja.role_id = consultants.role_id
                AND deja.permission_id = p.id
         )
""".replace("{codes}", ", ".join(f"'{code}'" for code in DROITS_REPRIS))


def upgrade() -> None:
    op.execute(REPRISE)


def downgrade() -> None:
    # Les droits repris ne sont pas distinguables de ceux accordés à la main
    # depuis : les retirer ferait plus de dégâts que de ne rien faire.
    pass
