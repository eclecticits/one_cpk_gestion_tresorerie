"""Le Tableau devient un module, au même rang que Trésorerie, RH ou Comptabilité.

Trois choses en découlent, et aucune ne doit faire perdre un accès en place :

1. Les codes `secretariat.tableau.*` deviennent `tableau.*`. Le renommage se fait
   sur place, si bien que les lignes de `role_permissions` suivent : aucun rôle
   n'est à refaire. Si un code d'arrivée existe déjà (migration rejouée, base
   partiellement à jour), l'ancien est supprimé après report de ses attributions.

2. `menu_tableau` apparaît, comme tout module en possède un. Il est accordé aux
   rôles qui détiennent déjà `tableau.view` : ce sont exactement ceux qui
   voyaient l'écran depuis le menu Secrétariat.

3. `tableau.settings` naît avec la page de réglages. Les règles de délibération
   s'éditaient jusqu'ici sous le droit d'analyser : ce droit est donc reporté sur
   les porteurs de `tableau.analyze`, faute de quoi la page apparaîtrait vide à
   ceux qui l'utilisaient.

Enfin, `modules_config` reçoit une entrée `tableau` qui reprend l'état du module
Secrétariat dont il sort : une organisation qui avait le Secrétariat activé voit
le Tableau, une organisation qui l'avait coupé ne le voit pas davantage
qu'avant. Sans cette reprise, le module resterait invisible pour toute
organisation dont les modules sont explicitement configurés.

Revision ID: 20260915_tableau_module
Revises: 20260914_tableau_droits_repris
Create Date: 2026-09-15
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision = "20260915_tableau_module"
down_revision = "20260914_tableau_droits_repris"
branch_labels = None
depends_on = None


RENOMMAGES: dict[str, str] = {
    "secretariat.tableau.view": "tableau.view",
    "secretariat.tableau.import": "tableau.import",
    "secretariat.tableau.analyze": "tableau.analyze",
    "secretariat.tableau.compare": "tableau.compare",
    "secretariat.tableau.generate_report": "tableau.generate_report",
    "secretariat.tableau.generate_pv": "tableau.generate_pv",
    "secretariat.tableau.export": "tableau.export",
    "secretariat.tableau.decide": "tableau.decide",
    "secretariat.tableau.correct": "tableau.correct",
}

DESCRIPTIONS: dict[str, str] = {
    "tableau.view": "Tableau : consulter",
    "tableau.import": "Tableau : importer un fichier Excel",
    "tableau.analyze": "Tableau : lancer l'analyse",
    "tableau.compare": "Tableau : comparer deux exercices",
    "tableau.generate_report": "Tableau : générer un rapport",
    "tableau.generate_pv": "Tableau : générer un procès-verbal",
    "tableau.export": "Tableau : exporter les résultats",
    "tableau.decide": "Tableau : enregistrer une décision",
    "tableau.correct": "Tableau : corriger un dossier",
}

NOUVEAUX: list[tuple[str, str, str | None]] = [
    # (code, description, code dont il hérite les attributions)
    ("menu_tableau", "Accès au module Tableau", "tableau.view"),
    ("tableau.settings", "Tableau : modifier les règles de délibération", "tableau.analyze"),
]


RENOMMAGE_SIMPLE = """
    UPDATE permissions
       SET code = :nouveau, description = :description
     WHERE code = :ancien
       AND NOT EXISTS (SELECT 1 FROM permissions WHERE code = :nouveau)
"""

# Base où les deux codes coexistent (migration rejouée, reprise partielle) : les
# attributions de l'ancien sont reportées sur le nouveau avant qu'il disparaisse.
REPORT_ATTRIBUTIONS = """
    INSERT INTO role_permissions (role_id, permission_id)
    SELECT rp.role_id, cible.id
      FROM role_permissions rp
      JOIN permissions source ON source.id = rp.permission_id AND source.code = :ancien
      JOIN permissions cible ON cible.code = :nouveau
     WHERE NOT EXISTS (
         SELECT 1 FROM role_permissions deja
          WHERE deja.role_id = rp.role_id AND deja.permission_id = cible.id
     )
"""

PURGE_ATTRIBUTIONS = """
    DELETE FROM role_permissions
     WHERE permission_id IN (SELECT id FROM permissions WHERE code = :ancien)
"""

PURGE_PERMISSION = "DELETE FROM permissions WHERE code = :ancien"

SEMER_PERMISSION = """
    INSERT INTO permissions (code, description, created_at)
    VALUES (:code, :description, now())
    ON CONFLICT (code) DO UPDATE SET description = EXCLUDED.description
"""

HERITER_ATTRIBUTIONS = """
    INSERT INTO role_permissions (role_id, permission_id)
    SELECT rp.role_id, cible.id
      FROM role_permissions rp
      JOIN permissions source ON source.id = rp.permission_id AND source.code = :source
      JOIN permissions cible ON cible.code = :code
     WHERE NOT EXISTS (
         SELECT 1 FROM role_permissions deja
          WHERE deja.role_id = rp.role_id AND deja.permission_id = cible.id
     )
"""

# Le module hérite de l'activation du Secrétariat, dont il sort.
ACTIVER_MODULE = """
    UPDATE organisation_settings
       SET modules_config = jsonb_set(
           coalesce(modules_config, '{}'::jsonb),
           '{tableau}',
           jsonb_build_object(
               'enabled',
               coalesce(modules_config -> 'secretariat' ->> 'enabled', 'true')::boolean
           ),
           true
       )
     WHERE modules_config IS NOT NULL
       AND NOT (modules_config ? 'tableau')
"""


def instructions() -> list[tuple[str, dict]]:
    """Le SQL de la migration, pour qu'il puisse être éprouvé plutôt que recopié."""
    pas: list[tuple[str, dict]] = []
    for ancien, nouveau in RENOMMAGES.items():
        params = {"ancien": ancien, "nouveau": nouveau, "description": DESCRIPTIONS[nouveau]}
        pas.append((RENOMMAGE_SIMPLE, params))
        pas.append((REPORT_ATTRIBUTIONS, {"ancien": ancien, "nouveau": nouveau}))
        pas.append((PURGE_ATTRIBUTIONS, {"ancien": ancien}))
        pas.append((PURGE_PERMISSION, {"ancien": ancien}))
    for code, description, source in NOUVEAUX:
        pas.append((SEMER_PERMISSION, {"code": code, "description": description}))
        if source:
            pas.append((HERITER_ATTRIBUTIONS, {"code": code, "source": source}))
    pas.append((ACTIVER_MODULE, {}))
    return pas


def upgrade() -> None:
    bind = op.get_bind()
    for requete, params in instructions():
        bind.execute(text(requete), params)


def downgrade() -> None:
    bind = op.get_bind()

    for ancien, nouveau in RENOMMAGES.items():
        bind.execute(
            text(
                "UPDATE permissions SET code = :ancien WHERE code = :nouveau "
                "AND NOT EXISTS (SELECT 1 FROM permissions WHERE code = :ancien)"
            ),
            {"ancien": ancien, "nouveau": nouveau},
        )

    for code, _description, _source in NOUVEAUX:
        bind.execute(
            text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code = :code)"),
            {"code": code},
        )
        bind.execute(text("DELETE FROM permissions WHERE code = :code"), {"code": code})

    bind.execute(text("UPDATE organisation_settings SET modules_config = modules_config - 'tableau' WHERE modules_config ? 'tableau'"))
