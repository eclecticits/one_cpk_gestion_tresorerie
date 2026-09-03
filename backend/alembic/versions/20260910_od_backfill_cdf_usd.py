"""backfill montant_usd_snapshot for legacy CDF direct orders

Revision ID: 20260910_od_cdf_usd
Revises: 20260909_od_benef_norm

Le plafond anti-fractionnement somme `montant_usd_snapshot` sur 24 h. La
migration 20260908 n'a repris que les ordres en USD, faute de taux : « le CDF
demanderait le taux en vigueur au moment de l'ordre, que l'on n'a pas ». On l'a
en fait, pour les ordres payés — la sortie de fonds rattachée porte
`exchange_rate_snapshot`, c'est-à-dire le taux appliqué au paiement lui-même,
soit exactement le taux voulu.

Sans cette reprise, tout ordre direct en CDF antérieur compte pour zéro et le
plafond se contourne en s'appuyant sur lui.

Reste non reprenable après cette migration : un ordre direct en CDF **autorisé
mais jamais payé** avant le déploiement, qui n'a pas de sortie donc pas de
taux. L'ensemble est borné (il faut de plus qu'il ait moins de 24 h pour
compter) et dénombrable — cf. backend/scripts/audit_plafond_direct_cdf.sql.
Tout ordre créé après le déploiement reçoit son snapshot à la programmation.
"""

from alembic import op


revision = "20260910_od_cdf_usd"
down_revision = "20260909_od_benef_norm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `exchange_rate_snapshot` est le taux CDF par USD, et la conversion de
    # l'application est `montant / taux` (cf. `_montant_direct_usd` et
    # `_to_budget_currency`). On reprend la même, à l'arrondi près.
    op.execute(
        """
        UPDATE ordres_decaissement o
        SET montant_usd_snapshot = round(o.montant / s.exchange_rate_snapshot, 2)
        FROM sorties_fonds s
        WHERE s.id = o.sortie_fonds_id
          AND o.requisition_id IS NULL
          AND o.montant_usd_snapshot IS NULL
          AND upper(o.devise) = 'CDF'
          AND s.exchange_rate_snapshot IS NOT NULL
          AND s.exchange_rate_snapshot > 0
        """
    )


def downgrade() -> None:
    # Volontairement sans effet. Cette migration ne change pas le schéma : elle
    # remplit des valeurs. Les remettre à NULL effacerait aussi celles que
    # l'application a légitimement écrites depuis, qu'aucune colonne ne permet
    # de distinguer des valeurs reprises ici.
    pass
