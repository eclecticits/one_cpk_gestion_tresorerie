"""versements en francs : l'argent réel, non sa contre-valeur en dollars

Une note payée en francs est libellée en dollars. Jusqu'ici son versement
portait la contre-valeur en dollars sous la devise CDF : la caisse ou la banque
en francs était créditée de 100 pour 280 000 CDF reçus, et les états de
trésorerie, qui lisent le versement, suivaient. Le versement porte désormais
l'argent réel (montant × taux figé sur la note) ; la note et le budget gardent
l'équivalent en dollars.

Les lignes existantes sont converties à l'identique : versements CDF, part en
devise de leurs imputations budgétaires, et `montant_percu` des notes. Une
recette à identifier est tenue dans la devise de son compte et n'est pas
touchée. Les soldes de caisse et de banque ne sont PAS recalculés : ils ont été
crédités de la contre-valeur, et les corriger est un rapprochement à faire avec
un relevé, pas une conversion aveugle.

Revision ID: 20261024b_cdf_versements
Revises: 20261024a_ft_requalifie
Create Date: 2026-10-24
"""

from alembic import op


revision = "20261024b_cdf_versements"
down_revision = "20261024a_ft_requalifie"
branch_labels = None
depends_on = None


NOTES_EN_FRANCS = """
    SELECT e.id, e.taux_change_applique AS taux
    FROM encaissements e
    WHERE e.devise_perception = 'CDF'
      AND COALESCE(e.nature_mouvement, 'BUDGETAIRE') <> 'A_IDENTIFIER'
      AND COALESCE(e.taux_change_applique, 0) > 1
"""


def _convertir(operateur: str, percu: str) -> None:
    op.execute(
        f"""
        UPDATE mouvement_budget_imputations m
        SET montant_mouvement = ROUND(m.montant_mouvement {operateur} n.taux, 2)
        FROM payment_history ph, ({NOTES_EN_FRANCS}) n
        WHERE m.payment_history_id = ph.id
          AND ph.encaissement_id = n.id
          AND m.devise_mouvement = 'CDF'
        """
    )
    op.execute(
        f"""
        UPDATE payment_history ph
        SET montant = ROUND(ph.montant {operateur} n.taux, 2)
        FROM ({NOTES_EN_FRANCS}) n
        WHERE ph.encaissement_id = n.id
          AND ph.devise = 'CDF'
        """
    )
    op.execute(
        f"""
        UPDATE encaissements e
        SET montant_percu = ROUND({percu}, 2)
        FROM ({NOTES_EN_FRANCS}) n
        WHERE e.id = n.id
          AND EXISTS (SELECT 1 FROM payment_history ph WHERE ph.encaissement_id = e.id)
        """
    )


def upgrade() -> None:
    # Le perçu d'une note en francs : les francs reçus.
    _convertir("*", "COALESCE(e.montant_paye, 0) * n.taux")


def downgrade() -> None:
    # Ancienne règle : le perçu suivait le payé, en dollars.
    _convertir("/", "COALESCE(e.montant_paye, 0)")
