"""Une ligne d'import se situe dans sa feuille, pas seulement dans le classeur

Revision ID: 20260916_source_feuille
Revises: 20260916_jonction2

`tableau_source_rows` exigeait l'unicité de `(import_id, line_number)`. Or le
lecteur Excel renumérote à chaque onglet : la ligne 5 de la première feuille et
la ligne 5 de la seconde portaient le même numéro pour le même import, et tout
classeur multi-feuilles échouait sur la contrainte.

On aurait pu compter d'une seule traite sur tout le classeur. Ce numéro continu
n'aurait plus rien désigné pour l'opérateur : ce qu'il lit dans les erreurs
d'import, c'est « ligne 5 », et il va la chercher dans un onglet. Le parseur
transportait d'ailleurs déjà `feuille` dans ses messages d'erreur — elle était
calculée puis jetée avant l'écriture.

La colonne est donc ajoutée et l'unicité étendue. Les lignes déjà en base
prennent la chaîne vide : elles proviennent d'imports mono-feuille, où le couple
`(import_id, line_number)` était déjà unique, et leur ajouter un nom de feuille
inventé serait affirmer plus que ce qu'on sait.

Revision ID: 20260916_source_feuille
Create Date: 2026-09-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260916_source_feuille"
down_revision = "20260916_jonction2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tableau_source_rows",
        sa.Column("feuille", sa.String(120), nullable=False, server_default=""),
    )
    op.drop_constraint("uq_tableau_source_row_line", "tableau_source_rows", type_="unique")
    op.create_unique_constraint(
        "uq_tableau_source_row_line",
        "tableau_source_rows",
        ["import_id", "feuille", "line_number"],
    )


def downgrade() -> None:
    # Le retour n'est possible que si aucun import multi-feuilles n'a été chargé
    # depuis : deux lignes homonymes se heurteraient à l'ancienne contrainte.
    # Mieux vaut échouer ici que de perdre des lignes en silence.
    op.drop_constraint("uq_tableau_source_row_line", "tableau_source_rows", type_="unique")
    op.create_unique_constraint(
        "uq_tableau_source_row_line",
        "tableau_source_rows",
        ["import_id", "line_number"],
    )
    op.drop_column("tableau_source_rows", "feuille")
