"""Backfill de la classification des mouvements et de leurs imputations.

Phase B, à n'appliquer qu'après un préflight vert
(`scripts/audit_mouvements_hors_budget_preflight.py`).

Trois temps :

1. **Classification.** Toute ligne antérieure était budgétaire par construction :
   il n'existait pas d'autre possibilité. Seuls les versements et
   approvisionnements faisaient déjà exception dans le code — sans le dire dans
   les données ; ils deviennent explicitement `TRANSFERT_INTERNE`.

2. **Imputations.** On enregistre l'imputation budgétaire que chaque sortie et
   chaque paiement a réellement produite, pour que leur annulation future
   reprenne le bon montant sur le bon poste au lieu de le recalculer. On
   n'ajoute RIEN aux compteurs des postes : cet argent y est déjà, on ne fait
   que noter d'où il vient. Les montants reprennent à l'identique la formule
   qu'appliquait le code (`_to_budget_currency` pour les sorties, montant brut
   pour les paiements) : une reprise qui divergerait ferait des écarts à
   l'annulation, exactement ce que cette table existe pour empêcher.

3. **Verrouillage.** `nature_mouvement` et `impact_budgetaire` deviennent
   obligatoires, avec une valeur par défaut, pour qu'aucune ligne future ne
   puisse rester non classée.

Le `downgrade` relâche les contraintes mais NE SUPPRIME PAS les imputations
reprises : elles décrivent des faits exacts, et les redeviner après coup serait
plus risqué que les garder.

Revision ID: 20260905_hors_budget_backfill
Revises: 20260904_hors_budget_schema
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260905_hors_budget_backfill"
down_revision = "20260904_hors_budget_schema"
branch_labels = None
depends_on = None


TRANSFERTS = "('versement_banque','approvisionnement_caisse')"


def upgrade() -> None:
    # --- 1. Classification ------------------------------------------------
    op.execute(
        """
        UPDATE encaissements
           SET nature_mouvement = 'BUDGETAIRE',
               impact_budgetaire = TRUE
         WHERE nature_mouvement IS NULL
        """
    )
    op.execute(
        f"""
        UPDATE sorties_fonds
           SET nature_mouvement = 'TRANSFERT_INTERNE',
               impact_budgetaire = FALSE
         WHERE nature_mouvement IS NULL
           AND lower(coalesce(type_sortie,'')) IN {TRANSFERTS}
        """
    )
    op.execute(
        """
        UPDATE sorties_fonds
           SET nature_mouvement = 'BUDGETAIRE',
               impact_budgetaire = TRUE
         WHERE nature_mouvement IS NULL
        """
    )

    # --- 2. Imputations historiques --------------------------------------
    # Sorties : le montant imputé au poste était le montant payé converti vers
    # la devise du budget (USD). On rejoue la même conversion — snapshot de la
    # sortie d'abord, taux de l'organisation ensuite, montant brut à défaut.
    op.execute(
        f"""
        INSERT INTO mouvement_budget_imputations (
            id, organisation_id, sortie_fonds_id, budget_poste_id, sens,
            montant_mouvement, devise_mouvement, montant_budget,
            exchange_rate_snapshot, statut, created_at
        )
        SELECT
            gen_random_uuid(),
            sf.organisation_id,
            sf.id,
            sf.budget_poste_id,
            'DEPENSE_PAYEE',
            sf.montant_paye,
            upper(coalesce(sf.devise,'USD')),
            CASE
                WHEN upper(coalesce(sf.devise,'USD')) = 'USD' THEN round(sf.montant_paye, 2)
                WHEN coalesce(sf.exchange_rate_snapshot, 0) > 0
                    THEN round(sf.montant_paye / sf.exchange_rate_snapshot, 2)
                WHEN coalesce(ps.exchange_rate_cdf, 0) > 0
                    THEN round(sf.montant_paye / ps.exchange_rate_cdf, 2)
                ELSE round(sf.montant_paye, 2)
            END,
            sf.exchange_rate_snapshot,
            'ACTIVE',
            coalesce(sf.created_at, now())
        FROM sorties_fonds sf
        LEFT JOIN LATERAL (
            SELECT p.exchange_rate_cdf
              FROM print_settings p
             WHERE p.organisation_id = sf.organisation_id
             LIMIT 1
        ) ps ON TRUE
        WHERE sf.budget_poste_id IS NOT NULL
          AND sf.impact_budgetaire IS TRUE
          AND upper(coalesce(sf.statut,'VALIDE')) = 'VALIDE'
          AND coalesce(sf.montant_paye, 0) > 0
          AND upper(coalesce(sf.devise,'USD')) IN ('USD','CDF')
          AND lower(coalesce(sf.type_sortie,'')) NOT IN {TRANSFERTS}
          AND EXISTS (SELECT 1 FROM budget_postes bp WHERE bp.id = sf.budget_poste_id)
          AND NOT EXISTS (
            SELECT 1 FROM mouvement_budget_imputations m WHERE m.sortie_fonds_id = sf.id
          )
        """
    )

    # Paiements d'encaissement : le code ajoutait le montant BRUT au poste, sans
    # conversion. On reprend ce montant tel quel, sinon l'annulation d'un
    # paiement en CDF retirerait autre chose que ce qu'elle avait ajouté.
    op.execute(
        """
        INSERT INTO mouvement_budget_imputations (
            id, organisation_id, payment_history_id, budget_poste_id, sens,
            montant_mouvement, devise_mouvement, montant_budget,
            statut, created_at
        )
        SELECT
            gen_random_uuid(),
            ph.organisation_id,
            ph.id,
            ph.budget_poste_id,
            'RECETTE_REALISEE',
            ph.montant,
            upper(coalesce(ph.devise,'USD')),
            round(ph.montant, 2),
            'ACTIVE',
            coalesce(ph.created_at, now())
        FROM payment_history ph
        WHERE ph.budget_poste_id IS NOT NULL
          AND upper(coalesce(ph.statut,'ACTIF')) = 'ACTIF'
          AND coalesce(ph.montant, 0) > 0
          AND upper(coalesce(ph.devise,'USD')) IN ('USD','CDF')
          AND EXISTS (SELECT 1 FROM budget_postes bp WHERE bp.id = ph.budget_poste_id)
          AND EXISTS (
            SELECT 1 FROM encaissements e
             WHERE e.id = ph.encaissement_id
               AND coalesce(e.impact_budgetaire, TRUE) IS TRUE
          )
          AND NOT EXISTS (
            SELECT 1 FROM mouvement_budget_imputations m WHERE m.payment_history_id = ph.id
          )
        """
    )

    # --- 3. Verrouillage --------------------------------------------------
    for table in ("encaissements", "sorties_fonds"):
        op.alter_column(table, "nature_mouvement", nullable=False, server_default="BUDGETAIRE")
        op.alter_column(
            table,
            "impact_budgetaire",
            nullable=False,
            server_default=sa.text("true"),
        )


def downgrade() -> None:
    # On relâche les contraintes sans défaire le backfill : les imputations
    # reprises décrivent des mouvements réels, les effacer rouvrirait le trou
    # que cette migration comble.
    for table in ("encaissements", "sorties_fonds"):
        op.alter_column(table, "impact_budgetaire", nullable=True, server_default=None)
        op.alter_column(table, "nature_mouvement", nullable=True, server_default=None)
