"""reglages propres au bon de sortie directe

Revision ID: 20261007_bon_sortie_directe
Revises: 20261006_remb_recette_ident
Create Date: 2026-10-07

Une sortie sur requisition a deja ete autorisee en amont (examen, validations,
visa) : son bon n'est qu'une piece d'execution. Une sortie directe n'a aucun
circuit : la signature de l'autorite sur le bon est l'autorisation elle-meme.
Ce bon a donc son propre signataire (titulaire et interimaire) et sa mention
d'avertissement.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20261007_bon_sortie_directe"
down_revision = "20261006_remb_recette_ident"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "print_settings",
        sa.Column(
            "sortie_directe_label_autorite",
            sa.String(length=200),
            nullable=False,
            server_default="L'AUTORITÉ",
        ),
    )
    op.add_column(
        "print_settings",
        sa.Column("sortie_directe_nom_autorite", sa.String(length=200), nullable=False, server_default=""),
    )
    op.add_column(
        "print_settings",
        sa.Column("sortie_directe_nom_interim", sa.String(length=200), nullable=False, server_default=""),
    )
    op.add_column(
        "print_settings",
        sa.Column(
            "sortie_directe_mention",
            sa.String(length=300),
            nullable=False,
            server_default=(
                "Sortie hors réquisition — valable uniquement revêtue de la "
                "signature et du cachet de l'Autorité."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("print_settings", "sortie_directe_mention")
    op.drop_column("print_settings", "sortie_directe_nom_interim")
    op.drop_column("print_settings", "sortie_directe_nom_autorite")
    op.drop_column("print_settings", "sortie_directe_label_autorite")
