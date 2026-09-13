"""Normalise les n° d'ordre des dossiers Tableau déjà importés.

Les imports normalisent désormais le n° d'ordre (majuscules, espaces ôtés) car
il sert de clé d'identité du membre : c'est par lui que se regroupent les
situations successives d'un même expert. Les dossiers importés avant cette règle
portent encore la graphie du fichier d'origine, et seraient donc pris pour des
membres distincts d'un « EC/18.00062 » propre. Cette migration les aligne.

La structure du numéro n'est pas touchée : seules la casse et les espaces le
sont, exactement comme `_norm_numero_ordre` côté service.

Revision ID: 20260914_tableau_numeros
Revises: 20260914_tableau_base_idx
Create Date: 2026-09-14
"""

from __future__ import annotations

from alembic import op


revision = "20260914_tableau_numeros"
down_revision = "20260914_tableau_base_idx"
branch_labels = None
depends_on = None

TABLE = "secretariat_tableau_dossiers"

# Équivalent SQL de _norm_numero_ordre : majuscules, tout espace ôté, vide -> NULL.
NORMALISE = r"NULLIF(upper(regexp_replace({colonne}, '\s', '', 'g')), '')"

UPDATE = f"""
    UPDATE {TABLE}
       SET numero_ordre = {NORMALISE.format(colonne='numero_ordre')}
     WHERE numero_ordre IS NOT NULL
       AND numero_ordre IS DISTINCT FROM {NORMALISE.format(colonne='numero_ordre')}
"""


def upgrade() -> None:
    op.execute(UPDATE)


def downgrade() -> None:
    """Sans retour : la graphie d'origine des numéros n'est pas conservée.

    Rien n'est perdu pour autant — seules la casse et les espaces parasites le
    sont, et le numéro reste celui du membre.
    """
