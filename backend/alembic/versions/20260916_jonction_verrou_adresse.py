"""Seconde jonction : le verrou de ré-imputation rejoint l'adresse du Tableau.

Deux travaux sont repartis en parallèle de `20260916_tableau_actual` — la levée
du verrou des lignes pour la correction d'imputation, et l'adresse des membres
du Tableau. Chacun a posé sa révision sans voir l'autre, d'où deux têtes et un
`alembic upgrade head` qui refuse de choisir.

Comme `20260916_jonction` avant elle, cette révision ne fait que réunir les deux
branches. Aucun schéma n'y est touché : elle existe pour que l'historique
redevienne linéaire à partir d'ici.

Revision ID: 20260916_jonction2
Revises: 20260916_verrou_reimput, 20260916_tableau_adresse
Create Date: 2026-09-16
"""

from __future__ import annotations


revision = "20260916_jonction2"
down_revision = ("20260916_verrou_reimput", "20260916_tableau_adresse")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Rien à appliquer : les deux branches ont déjà fait leur travail."""


def downgrade() -> None:
    """Rien à défaire : la jonction ne porte aucun schéma."""
