"""paiement mixte : mode et compte bancaire par ligne, volet ferme sur l'ordre

Socle du reglement mixte. Une requisition pouvait n'avoir qu'un seul mode de
paiement pour toutes ses lignes. Desormais :

  - la ligne de requisition porte l'intention de reglement (mode + compte),
    saisie par le demandeur ;
  - l'ordre de decaissement porte la decision ferme (mode + canal + compte),
    posee a l'autorisation et executee telle quelle par la caisse.

Cette revision n'ajoute que les colonnes et retro-remplit l'existant depuis la
requisition parente : aucun comportement ne change tant que les phases
suivantes ne s'appuient pas dessus.

Revision ID: 20260816_paiement_mixte
Revises: 20260814_ai_usage_log
Create Date: 2026-08-16 09:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260816_paiement_mixte"
down_revision = "20260814_ai_usage_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Ligne de requisition : intention de reglement.
    # Nullable a la creation pour pouvoir retro-remplir, passe NOT NULL ensuite.
    op.add_column(
        "lignes_requisition",
        sa.Column("mode_paiement", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "lignes_requisition",
        sa.Column("compte_bancaire_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_lignes_requisition_compte_bancaire",
        "lignes_requisition",
        "comptes_bancaires",
        ["compte_bancaire_id"],
        ["id"],
    )

    # Retro-remplissage : jusqu'ici toutes les lignes d'une requisition
    # partageaient forcement le mode et le compte de leur parente.
    # Le trigger d'immuabilite protege les operations normales, mais
    # 20260801 a defini un bypass transactionnel precis pour les migrations.
    # SET LOCAL ne desactive donc jamais la protection pour l'application.
    op.execute("SET LOCAL onec.admin_reset = 'on'")
    op.execute(
        """
        UPDATE public.lignes_requisition AS l
        SET mode_paiement = r.mode_paiement,
            compte_bancaire_id = r.compte_bancaire_id
        FROM public.requisitions AS r
        WHERE l.requisition_id = r.id
        """
    )
    # Lignes orphelines eventuelles (requisition supprimee en dur) : repli caisse.
    op.execute(
        "UPDATE public.lignes_requisition SET mode_paiement = 'cash' WHERE mode_paiement IS NULL"
    )
    op.alter_column("lignes_requisition", "mode_paiement", nullable=False)

    op.create_index(
        "ix_lignes_requisition_compte_bancaire_id",
        "lignes_requisition",
        ["compte_bancaire_id"],
    )

    # --- Ordre de decaissement : volet ferme.
    # Un ordre est mono-(mode, compte) : c'est ce qui garantit qu'il reste
    # traduisible en une seule sortie de fonds (lien 1:1 sortie_fonds_id).
    op.add_column(
        "ordres_decaissement",
        sa.Column("mode_paiement", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "ordres_decaissement",
        sa.Column("canal", sa.String(length=10), nullable=True),
    )
    op.add_column(
        "ordres_decaissement",
        sa.Column("compte_bancaire_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_ordres_decaissement_compte_bancaire",
        "ordres_decaissement",
        "comptes_bancaires",
        ["compte_bancaire_id"],
        ["id"],
    )

    # Ordres lies a une requisition : ils heritaient implicitement de son mode.
    op.execute(
        """
        UPDATE public.ordres_decaissement AS o
        SET mode_paiement = r.mode_paiement,
            compte_bancaire_id = r.compte_bancaire_id
        FROM public.requisitions AS r
        WHERE o.requisition_id = r.id
        """
    )
    # Ordres de sortie directe (requisition_id NULL) : payes par la caisse.
    op.execute(
        "UPDATE public.ordres_decaissement SET mode_paiement = 'cash' WHERE mode_paiement IS NULL"
    )
    op.execute(
        """
        UPDATE public.ordres_decaissement
        SET canal = CASE WHEN LOWER(mode_paiement) = 'cash' THEN 'CAISSE' ELSE 'BANQUE' END
        WHERE canal IS NULL
        """
    )
    op.alter_column("ordres_decaissement", "mode_paiement", nullable=False)
    op.alter_column("ordres_decaissement", "canal", nullable=False)

    op.create_check_constraint(
        "ck_ordres_decaissement_canal",
        "ordres_decaissement",
        "canal IN ('CAISSE','BANQUE')",
    )
    # Meme invariant que sur les sorties de fonds : un volet bancaire designe
    # toujours le compte d'ou sort l'argent.
    op.create_check_constraint(
        "ck_ordres_decaissement_compte_bancaire",
        "ordres_decaissement",
        "(canal = 'BANQUE' AND compte_bancaire_id IS NOT NULL) OR canal = 'CAISSE'",
    )
    op.create_index(
        "ix_ordres_decaissement_compte_bancaire_id",
        "ordres_decaissement",
        ["compte_bancaire_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ordres_decaissement_compte_bancaire_id", table_name="ordres_decaissement")
    op.drop_constraint(
        "ck_ordres_decaissement_compte_bancaire", "ordres_decaissement", type_="check"
    )
    op.drop_constraint("ck_ordres_decaissement_canal", "ordres_decaissement", type_="check")
    op.drop_constraint(
        "fk_ordres_decaissement_compte_bancaire", "ordres_decaissement", type_="foreignkey"
    )
    op.drop_column("ordres_decaissement", "compte_bancaire_id")
    op.drop_column("ordres_decaissement", "canal")
    op.drop_column("ordres_decaissement", "mode_paiement")

    op.drop_index("ix_lignes_requisition_compte_bancaire_id", table_name="lignes_requisition")
    op.drop_constraint(
        "fk_lignes_requisition_compte_bancaire", "lignes_requisition", type_="foreignkey"
    )
    op.drop_column("lignes_requisition", "compte_bancaire_id")
    op.drop_column("lignes_requisition", "mode_paiement")
