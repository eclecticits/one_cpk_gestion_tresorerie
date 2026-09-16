"""Jonction des deux chantiers du jour sur le module Tableau.

Deux travaux ont avancé en parallèle depuis `20260915_tableau_audit` : la
correction d'imputation budgétaire d'une réquisition et l'ouverture du Tableau
aux sources multiples. Chacun a posé sa propre suite de migrations, d'où deux
têtes — et un `alembic upgrade head` qui refuse de choisir.

Cette révision ne fait rien d'autre que réunir les deux branches. Aucun schéma
n'y est touché : elle existe pour que l'historique redevienne linéaire à partir
d'ici.

Revision ID: 20260916_jonction
Revises: 20260916_reimputation, tableau_insurance_declarations
Create Date: 2026-09-16
"""

from __future__ import annotations


revision = "20260916_jonction"
down_revision = ("20260916_reimputation", "tableau_insurance_declarations")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Rien à appliquer : les deux branches ont déjà fait leur travail."""


def downgrade() -> None:
    """Rien à défaire : la jonction ne porte aucun schéma."""
