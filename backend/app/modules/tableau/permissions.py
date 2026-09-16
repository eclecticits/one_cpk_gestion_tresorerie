"""Droits du module Tableau.

Le Tableau est un module à part entière, au même titre que Trésorerie, RH ou
Comptabilité : il possède donc son propre espace de codes, `tableau.*`, et son
code de menu. Les codes historiques `secretariat.tableau.*` ont été renommés en
place par la migration 20260915_tableau_module, ce qui préserve les attributions
déjà faites aux rôles.
"""

from __future__ import annotations


TABLEAU_PERMISSIONS: list[tuple[str, str]] = [
    ("menu_tableau", "Accès au module Tableau"),
    ("tableau.view", "Tableau : consulter"),
    ("tableau.import", "Tableau : importer un fichier Excel"),
    ("tableau.analyze", "Tableau : lancer l'analyse"),
    ("tableau.compare", "Tableau : comparer deux exercices"),
    ("tableau.generate_report", "Tableau : générer un rapport"),
    ("tableau.generate_pv", "Tableau : générer un procès-verbal"),
    ("tableau.export", "Tableau : exporter les résultats"),
    ("tableau.decide", "Tableau : enregistrer une décision"),
    ("tableau.correct", "Tableau : corriger un dossier"),
    ("tableau.settings", "Tableau : modifier les règles de délibération"),
    ("tableau.view_audit_logs", "Tableau : consulter le journal des actions"),
    ("tableau.use_assistant", "Tableau : utiliser l'assistant"),
]

TABLEAU_PERMISSION_CODES = tuple(code for code, _ in TABLEAU_PERMISSIONS)
TABLEAU_PERMISSION_DESCRIPTIONS = {code: description for code, description in TABLEAU_PERMISSIONS}

# Correspondance des codes d'avant la sortie du Secrétariat, pour les migrations
# et pour lire l'historique.
ANCIENS_CODES: dict[str, str] = {
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
