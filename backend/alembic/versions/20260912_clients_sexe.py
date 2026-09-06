"""Le sexe rejoint la fiche client

Revision ID: 20260912_clients_sexe
Revises: 20260911_lignes_verrou_val1

Demandé pour les personnes physiques et les clients externes, à la saisie d'un
encaissement comme à l'export. La colonne vit sur `clients` et non sur
`encaissements` : c'est un trait de la personne, pas de l'opération. Le porter
sur l'encaissement l'aurait fait ressaisir à chaque versement, avec le risque
qu'un même client se retrouve M ici et F là.

Nullable, et sans reprise de l'existant : aucune fiche déjà en base ne porte
l'information, et la deviner d'après le prénom serait une invention. Les
fiches anciennes restent donc vides jusqu'à leur prochain passage au guichet.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260912_clients_sexe"
down_revision = "20260911_lignes_verrou_val1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("sexe", sa.String(length=1), nullable=True))
    # La contrainte tolère NULL explicitement : une organisation ou une banque
    # n'a pas de sexe, et le formulaire ne le leur demande pas.
    op.create_check_constraint(
        "ck_clients_sexe",
        "clients",
        "sexe IS NULL OR sexe IN ('M', 'F')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_clients_sexe", "clients", type_="check")
    op.drop_column("clients", "sexe")
