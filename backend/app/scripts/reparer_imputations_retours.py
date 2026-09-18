"""Rend aux retours en trésorerie le mouvement d'imputation qui leur manquait.

Un retour corrigeait le compteur du poste (`montant_paye -= montant`) sans
inscrire de mouvement d'imputation. La ré-imputation, elle, ne déplace que des
mouvements : un retour ne suivait donc jamais la dépense qu'il corrige. Quand
celle-ci changeait de poste, le reliquat restait derrière, et deux postes
mentaient — celui d'arrivée sur-comptait une dépense dont une part était
revenue, celui de départ gardait une correction sans dépense derrière.

Le code ne produit plus ce trou. Ce script répare ce qui a été enregistré avant,
en deux temps pour chaque retour sans mouvement :

1. si sa dépense a été ré-imputée depuis, le retour la rejoint — le montant est
   rendu à l'ancien poste et retiré du nouveau, exactement ce qu'aurait fait la
   ré-imputation si le mouvement avait existé ;
2. le mouvement manquant est écrit, pour que la prochaine ré-imputation
   l'emporte avec elle.

Lecture seule par défaut. Rien n'est écrit sans `--execute`.

Usage (dans le conteneur) :
  docker compose exec backend python -m app.scripts.reparer_imputations_retours --dry-run
  docker compose exec backend python -m app.scripts.reparer_imputations_retours --execute
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from decimal import Decimal

from sqlalchemy import select

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.db.session import SessionLocal  # noqa: E402
from app.models.budget import BudgetPoste  # noqa: E402
from app.models.mouvement_budget_imputation import MouvementBudgetImputation  # noqa: E402
from app.models.retour_caisse import RetourCaisse  # noqa: E402
from app.models.sortie_fonds import SortieFonds  # noqa: E402


def _montant(valeur) -> Decimal:
    return Decimal(str(valeur or 0))


async def reparer(execute: bool) -> int:
    corriges = 0
    async with SessionLocal() as db:
        retours = list(
            (
                await db.execute(
                    select(RetourCaisse)
                    .where(RetourCaisse.statut == "VALIDE", RetourCaisse.ajuste_budget.is_(True))
                    .order_by(RetourCaisse.date_retour)
                )
            ).scalars().all()
        )
        if not retours:
            print("Aucun retour validé avec ajustement budgétaire.")
            return 0

        for retour in retours:
            deja = (
                await db.execute(
                    select(MouvementBudgetImputation).where(
                        MouvementBudgetImputation.retour_caisse_id == retour.id,
                        MouvementBudgetImputation.statut == "ACTIVE",
                    )
                )
            ).scalars().first()
            if deja is not None:
                continue
            if retour.budget_poste_id is None:
                print(f"  {retour.reference_numero} : sans poste budgétaire, rien à rattacher.")
                continue

            sortie = (
                await db.execute(select(SortieFonds).where(SortieFonds.id == retour.sortie_fonds_id))
            ).scalar_one_or_none()
            montant = _montant(retour.montant)
            poste_actuel = retour.budget_poste_id
            poste_cible = (sortie.budget_poste_id if sortie is not None else None) or poste_actuel

            print(
                f"  {retour.reference_numero} : {montant} {retour.devise}"
                f" | poste du retour {poste_actuel} | poste de la dépense {poste_cible}"
            )

            # 1. Le retour rejoint sa dépense si elle a changé de poste depuis.
            if poste_cible != poste_actuel:
                ancien = (
                    await db.execute(select(BudgetPoste).where(BudgetPoste.id == poste_actuel))
                ).scalar_one_or_none()
                nouveau = (
                    await db.execute(select(BudgetPoste).where(BudgetPoste.id == poste_cible))
                ).scalar_one_or_none()
                if ancien is None or nouveau is None:
                    print("     poste introuvable : laissé en l'état.")
                    continue
                print(
                    f"     déplacement : {ancien.code} +{montant} (correction rendue),"
                    f" {nouveau.code} -{montant} (correction appliquée)"
                )
                if execute:
                    ancien.montant_paye = _montant(ancien.montant_paye) + montant
                    nouveau.montant_paye = max(Decimal("0"), _montant(nouveau.montant_paye) - montant)
                    retour.budget_poste_id = nouveau.id
                    retour.budget_poste_code = nouveau.code
                    retour.budget_poste_libelle = nouveau.libelle

            # 2. Le mouvement manquant, sur le poste où le retour agit désormais.
            print(f"     mouvement RETOUR_DEPENSE à inscrire sur le poste {poste_cible}")
            if execute:
                db.add(
                    MouvementBudgetImputation(
                        organisation_id=retour.organisation_id,
                        retour_caisse_id=retour.id,
                        budget_poste_id=poste_cible,
                        sens="RETOUR_DEPENSE",
                        montant_mouvement=montant,
                        devise_mouvement=(retour.devise or "USD").upper(),
                        montant_budget=montant,
                        exchange_rate_snapshot=retour.exchange_rate_snapshot,
                        statut="ACTIVE",
                        created_by=retour.created_by,
                    )
                )
            corriges += 1

        if execute:
            await db.commit()
            print(f"\n{corriges} retour(s) réparé(s).")
        else:
            await db.rollback()
            print(f"\n[lecture seule] {corriges} retour(s) seraient réparés. --execute pour écrire.")
    return corriges


def main() -> None:
    parseur = argparse.ArgumentParser(description=__doc__)
    groupe = parseur.add_mutually_exclusive_group()
    groupe.add_argument("--dry-run", action="store_true", help="par défaut : rien n'est écrit")
    groupe.add_argument("--execute", action="store_true", help="écrit les corrections")
    args = parseur.parse_args()
    asyncio.run(reparer(execute=bool(args.execute)))


if __name__ == "__main__":
    main()
