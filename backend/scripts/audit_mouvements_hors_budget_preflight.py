"""Préflight du backfill « mouvements hors budget ».

Répond à une seule question avant de lancer la migration de classification :
la reprise de l'historique est-elle déterministe ? Tant qu'une ligne ne peut
pas être classée sans deviner, mieux vaut le savoir ici que le découvrir dans
une base de production à moitié migrée.

Trois familles de constats :
  * volumétrie — combien de lignes seront touchées, et comment elles seront
    classées ;
  * imputations reconstructibles — les sorties et paiements dont on peut
    rejouer l'imputation budgétaire à l'identique ;
  * points durs — les lignes qu'aucune règle ne classe, listées une par une.

Le script ne modifie rien : il ouvre une transaction en lecture seule et la
referme. Code de sortie 0 si le backfill peut partir, 1 s'il reste des points
durs, 2 si la configuration manque.

Usage :
    DATABASE_URL=postgresql+asyncpg://... python scripts/audit_mouvements_hors_budget_preflight.py
"""

from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("TEST_DATABASE_URL")

TRANSFERTS = "('versement_banque','approvisionnement_caisse')"

# (libellé, requête, bloquant ?)
COMPTAGES: list[tuple[str, str, bool]] = [
    ("encaissements à classer", "select count(*) from encaissements where nature_mouvement is null", False),
    (
        "  → seront BUDGETAIRE",
        "select count(*) from encaissements where nature_mouvement is null",
        False,
    ),
    (
        "  dont sans poste budgétaire (budgétaires sans imputation, comme aujourd'hui)",
        "select count(*) from encaissements where nature_mouvement is null and budget_poste_id is null",
        False,
    ),
    ("sorties à classer", "select count(*) from sorties_fonds where nature_mouvement is null", False),
    (
        "  → seront TRANSFERT_INTERNE",
        f"select count(*) from sorties_fonds where nature_mouvement is null and lower(coalesce(type_sortie,'')) in {TRANSFERTS}",
        False,
    ),
    (
        "  → seront BUDGETAIRE",
        f"select count(*) from sorties_fonds where nature_mouvement is null and lower(coalesce(type_sortie,'')) not in {TRANSFERTS}",
        False,
    ),
    (
        "imputations de sorties reconstructibles (poste unique connu)",
        f"""
        select count(*) from sorties_fonds sf
        where sf.budget_poste_id is not null
          and upper(coalesce(sf.statut,'VALIDE')) = 'VALIDE'
          and coalesce(sf.montant_paye,0) > 0
          and lower(coalesce(sf.type_sortie,'')) not in {TRANSFERTS}
          and not exists (select 1 from mouvement_budget_imputations m where m.sortie_fonds_id = sf.id)
        """,
        False,
    ),
    (
        "imputations de paiements reconstructibles (poste porté par le paiement)",
        """
        select count(*) from payment_history ph
        where ph.budget_poste_id is not null
          and upper(coalesce(ph.statut,'ACTIF')) = 'ACTIF'
          and coalesce(ph.montant,0) > 0
          and exists (select 1 from budget_postes bp where bp.id = ph.budget_poste_id)
          and not exists (select 1 from mouvement_budget_imputations m where m.payment_history_id = ph.id)
        """,
        False,
    ),
    (
        "sorties en devise non convertible (ni USD ni CDF) — imputation non reprise",
        f"""
        select count(*) from sorties_fonds sf
        where sf.budget_poste_id is not null
          and upper(coalesce(sf.statut,'VALIDE')) = 'VALIDE'
          and lower(coalesce(sf.type_sortie,'')) not in {TRANSFERTS}
          and upper(coalesce(sf.devise,'USD')) not in ('USD','CDF')
        """,
        True,
    ),
    (
        "sorties CDF sans taux exploitable — conversion budgétaire indéterminée",
        f"""
        select count(*) from sorties_fonds sf
        where sf.budget_poste_id is not null
          and upper(coalesce(sf.statut,'VALIDE')) = 'VALIDE'
          and lower(coalesce(sf.type_sortie,'')) not in {TRANSFERTS}
          and upper(coalesce(sf.devise,'USD')) = 'CDF'
          and coalesce(sf.exchange_rate_snapshot,0) <= 0
          and not exists (
            select 1 from print_settings ps
            where ps.organisation_id = sf.organisation_id and coalesce(ps.exchange_rate_cdf,0) > 0
          )
        """,
        True,
    ),
    (
        "sorties multi-postes non reprises (annulation restera sans reprise budgétaire)",
        f"""
        select count(*) from sorties_fonds sf
        where sf.budget_poste_id is null
          and upper(coalesce(sf.statut,'VALIDE')) = 'VALIDE'
          and lower(coalesce(sf.type_sortie,'')) not in {TRANSFERTS}
        """,
        False,
    ),
    (
        "imputations déjà présentes (migration rejouée)",
        "select count(*) from mouvement_budget_imputations",
        False,
    ),
]

DETAIL_DEVISE = f"""
select sf.id, sf.reference_numero, sf.type_sortie, sf.devise, sf.montant_paye,
       sf.exchange_rate_snapshot, sf.date_paiement
from sorties_fonds sf
where sf.budget_poste_id is not null
  and upper(coalesce(sf.statut,'VALIDE')) = 'VALIDE'
  and lower(coalesce(sf.type_sortie,'')) not in {TRANSFERTS}
  and (
    upper(coalesce(sf.devise,'USD')) not in ('USD','CDF')
    or (
      upper(coalesce(sf.devise,'USD')) = 'CDF'
      and coalesce(sf.exchange_rate_snapshot,0) <= 0
      and not exists (
        select 1 from print_settings ps
        where ps.organisation_id = sf.organisation_id and coalesce(ps.exchange_rate_cdf,0) > 0
      )
    )
  )
order by sf.date_paiement nulls last
limit 50
"""

DETAIL_MULTI_POSTES = f"""
select sf.id, sf.reference_numero, sf.type_sortie, sf.requisition_id, sf.montant_paye,
       sf.devise, sf.date_paiement
from sorties_fonds sf
where sf.budget_poste_id is null
  and upper(coalesce(sf.statut,'VALIDE')) = 'VALIDE'
  and lower(coalesce(sf.type_sortie,'')) not in {TRANSFERTS}
order by sf.date_paiement nulls last
limit 50
"""


async def main() -> int:
    if not DATABASE_URL:
        print("DATABASE_URL ou TEST_DATABASE_URL requis", file=sys.stderr)
        return 2

    engine = create_async_engine(DATABASE_URL)
    bloquants = 0
    multi_postes = 0
    try:
        async with engine.connect() as conn:
            await conn.execute(text("BEGIN READ ONLY"))
            try:
                print("Préflight — backfill mouvements hors budget")
                print("=" * 60)
                for label, sql, bloquant in COMPTAGES:
                    valeur = int((await conn.execute(text(sql))).scalar_one() or 0)
                    marque = " ⚠" if bloquant and valeur else ""
                    print(f"{label}: {valeur}{marque}")
                    if bloquant:
                        bloquants += valeur
                    if label.startswith("sorties multi-postes"):
                        multi_postes = valeur

                if bloquants:
                    print("\nSorties dont la conversion budgétaire est indéterminée :")
                    for row in (await conn.execute(text(DETAIL_DEVISE))).mappings().all():
                        print(f"  {dict(row)}")

                if multi_postes:
                    print(
                        "\nSorties multi-postes (non bloquant) : leur imputation n'est pas reprise,"
                        " leur annulation restera sans reprise budgétaire, comme aujourd'hui."
                    )
                    for row in (await conn.execute(text(DETAIL_MULTI_POSTES))).mappings().all():
                        print(f"  {dict(row)}")
            finally:
                await conn.execute(text("ROLLBACK"))
    finally:
        await engine.dispose()

    print("=" * 60)
    if bloquants:
        print(
            f"Préflight ÉCHOUÉ : {bloquants} ligne(s) sans conversion budgétaire déterminée.\n"
            "Renseignez le taux de change de l'organisation (ou le snapshot de ces sorties)\n"
            "avant de lancer la migration de backfill.",
            file=sys.stderr,
        )
        return 1
    print("Préflight OK : le backfill peut être appliqué.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
