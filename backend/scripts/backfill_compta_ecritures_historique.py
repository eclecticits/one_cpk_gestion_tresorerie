"""Reprise d'historique (Lot 3) : génère les écritures comptables des
opérations ANTÉRIEURES à l'activation du module Comptabilité.

Le moteur ne génère une écriture qu'au moment où l'opération est saisie. Une
organisation qui active la comptabilité aujourd'hui a donc un Grand Livre qui
démarre aujourd'hui, alors que sa trésorerie porte l'historique complet. Ce
script rejoue les faits générateurs déjà en base (encaissements, sorties de
fonds, transferts internes) pour reconstituer cet historique.

Propriétés :
- **Idempotent** : la clé d'idempotence de l'écriture (organisation, module,
  type, objet) empêche tout doublon ; une opération déjà comptabilisée est
  comptée « déjà en compta » et laissée telle quelle. Le script peut donc être
  rejoué autant de fois que nécessaire.
- **Non bloquant, contrairement au moteur en ligne** : chaque opération est
  traitée dans son propre point de sauvegarde. Une résolution de compte qui
  échoue (poste budgétaire non mappé) n'interrompt pas la reprise — elle est
  rapportée en fin d'exécution. C'est l'inverse du choix fait en saisie
  (échec bloquant), et c'est délibéré : ici l'opération métier existe déjà,
  refuser de reprendre les autres n'apporterait rien.
- **Écritures au BROUILLON**, comme celles du moteur : un comptable les revoit
  et les valide.

Usage :
    python -m scripts.backfill_compta_ecritures_historique --dry-run
    python -m scripts.backfill_compta_ecritures_historique --depuis 2026-01-01
    python -m scripts.backfill_compta_ecritures_historique --organisation 12
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.db.session  # noqa: F401 — enregistre les event listeners de scoping tenant
from app.core.tenant_context import set_current_tenant_id
from app.models.encaissement import Encaissement
from app.models.ordre_decaissement import OrdreDecaissement
from app.models.sortie_fonds import SortieFonds
from app.models.transfert_interne import TransfertInterne
from app.modules.comptabilite.models import ComptaEcriture, ComptaSociete
from app.modules.comptabilite.services.generation_service import (
    generer_ecriture_encaissement,
    generer_ecriture_sortie_fonds,
    generer_ecriture_transfert_interne,
)

TYPES_TRANSFERT_SORTIE = {"versement_banque", "approvisionnement_caisse"}


@dataclass
class Rapport:
    """Compteurs d'une reprise, par organisation."""

    creees: int = 0
    deja_en_compta: int = 0
    echecs: list[str] = field(default_factory=list)

    def fusionner(self, autre: "Rapport") -> None:
        self.creees += autre.creees
        self.deja_en_compta += autre.deja_en_compta
        self.echecs.extend(autre.echecs)


def _jour(valeur: datetime | date | None) -> date | None:
    if valeur is None:
        return None
    return valeur.date() if isinstance(valeur, datetime) else valeur


async def _deja_comptabilise(
    db: AsyncSession, organisation_id: int, module_origine: str, type_origine: str, objet_id
) -> bool:
    """Vrai si l'opération porte déjà une écriture (quel que soit son statut).

    Les fonctions de génération sont idempotentes et retourneraient l'écriture
    existante ; on les court-circuite ici pour distinguer, dans le rapport, ce
    qui a réellement été créé de ce qui existait déjà.
    """
    res = await db.execute(
        select(ComptaEcriture.id).where(
            ComptaEcriture.organisation_id == organisation_id,
            ComptaEcriture.module_origine == module_origine,
            ComptaEcriture.type_origine == type_origine,
            ComptaEcriture.objet_origine_id == str(objet_id),
        )
    )
    return res.scalar_one_or_none() is not None


async def _imputations_multi_poste(
    db: AsyncSession, sortie: SortieFonds
) -> list[tuple[int, Decimal]] | None:
    """Reconstitue la répartition d'une sortie multi-postes.

    La répartition n'est pas stockée sur la sortie (seul le libellé « Réparti
    sur N postes » en garde la trace) : elle vit dans les lignes de l'ordre de
    décaissement qui l'a produite. Retourne `None` si l'ordre est introuvable
    — la sortie est alors signalée plutôt que comptabilisée sur un compte
    arbitraire.
    """
    res = await db.execute(
        select(OrdreDecaissement).where(
            OrdreDecaissement.sortie_fonds_id == sortie.id,
            OrdreDecaissement.organisation_id == sortie.organisation_id,
        )
    )
    ordre = res.scalar_one_or_none()
    if ordre is None:
        return None
    imputations = [
        (int(ligne["budget_poste_id"]), Decimal(str(ligne.get("montant", ligne.get("montant_total")) or 0)))
        for ligne in (ordre.lignes or [])
        if isinstance(ligne, dict) and ligne.get("budget_poste_id") is not None
    ]
    return imputations or None


async def _reprendre_encaissements(
    db: AsyncSession, organisation_id: int, depuis: date | None
) -> Rapport:
    rapport = Rapport()
    stmt = select(Encaissement).where(
        Encaissement.organisation_id == organisation_id,
        Encaissement.is_deleted.is_(False),
        Encaissement.est_proforma.is_(False),
        Encaissement.statut_operation != "ANNULEE",
        Encaissement.montant_paye > 0,
    )
    res = await db.execute(stmt.order_by(Encaissement.date_encaissement))
    for encaissement in res.scalars().all():
        date_operation = _jour(encaissement.date_paiement or encaissement.date_encaissement)
        if date_operation is None or (depuis is not None and date_operation < depuis):
            continue
        if await _deja_comptabilise(db, organisation_id, "encaissements", "encaissement", encaissement.id):
            rapport.deja_en_compta += 1
            continue
        try:
            async with db.begin_nested():
                await generer_ecriture_encaissement(
                    db,
                    organisation_id=organisation_id,
                    encaissement_id=str(encaissement.id),
                    date_operation=date_operation,
                    montant=encaissement.montant_paye,
                    devise=encaissement.devise_perception,
                    canal=encaissement.canal,
                    compte_bancaire_id=encaissement.compte_bancaire_id,
                    budget_poste_id=encaissement.budget_poste_id,
                    libelle=encaissement.libelle,
                    created_by=encaissement.created_by,
                )
        except Exception as exc:  # noqa: BLE001 — reprise non bloquante (cf. docstring)
            rapport.echecs.append(f"encaissement {encaissement.numero_recu or encaissement.id} : {exc}")
            continue
        rapport.creees += 1
    return rapport


async def _reprendre_sorties_fonds(
    db: AsyncSession, organisation_id: int, depuis: date | None
) -> Rapport:
    rapport = Rapport()
    res = await db.execute(
        select(SortieFonds)
        .where(
            SortieFonds.organisation_id == organisation_id,
            SortieFonds.statut == "VALIDE",
        )
        .order_by(SortieFonds.date_paiement)
    )
    for sortie in res.scalars().all():
        date_operation = _jour(sortie.date_paiement or sortie.created_at)
        if date_operation is None or (depuis is not None and date_operation < depuis):
            continue
        libelle = sortie.motif or sortie.beneficiaire or f"Sortie de fonds {sortie.reference_numero}"
        est_transfert = (sortie.type_sortie or "").lower() in TYPES_TRANSFERT_SORTIE
        type_origine = "transfert_interne" if est_transfert else "sortie_fonds"
        if await _deja_comptabilise(db, organisation_id, "sorties_fonds", type_origine, sortie.id):
            rapport.deja_en_compta += 1
            continue
        try:
            async with db.begin_nested():
                if est_transfert:
                    est_appro = (sortie.type_sortie or "").lower() == "approvisionnement_caisse"
                    await generer_ecriture_transfert_interne(
                        db,
                        organisation_id=organisation_id,
                        sortie_fonds_id=str(sortie.id),
                        date_operation=date_operation,
                        montant=sortie.montant_paye,
                        devise=sortie.devise,
                        compte_origine_bancaire_id=(sortie.compte_bancaire_id if est_appro else None),
                        compte_destination_bancaire_id=(None if est_appro else sortie.compte_bancaire_id),
                        libelle=libelle,
                        created_by=sortie.created_by,
                    )
                else:
                    imputations = None
                    if sortie.budget_poste_id is None:
                        imputations = await _imputations_multi_poste(db, sortie)
                        if imputations is None:
                            raise ValueError(
                                "répartition multi-postes introuvable (ordre de décaissement absent) — "
                                "à comptabiliser manuellement"
                            )
                    await generer_ecriture_sortie_fonds(
                        db,
                        organisation_id=organisation_id,
                        sortie_fonds_id=str(sortie.id),
                        date_operation=date_operation,
                        montant=sortie.montant_paye,
                        devise=sortie.devise,
                        canal=sortie.canal,
                        compte_bancaire_id=sortie.compte_bancaire_id,
                        budget_poste_id=sortie.budget_poste_id,
                        libelle=libelle,
                        created_by=sortie.created_by,
                        imputations=imputations,
                    )
        except Exception as exc:  # noqa: BLE001 — reprise non bloquante
            rapport.echecs.append(f"sortie {sortie.reference_numero or sortie.id} : {exc}")
            continue
        rapport.creees += 1
    return rapport


async def _reprendre_transferts(
    db: AsyncSession, organisation_id: int, depuis: date | None
) -> Rapport:
    rapport = Rapport()
    res = await db.execute(
        select(TransfertInterne)
        .where(TransfertInterne.organisation_id == organisation_id)
        .order_by(TransfertInterne.date_transfert)
    )
    for transfert in res.scalars().all():
        date_operation = _jour(transfert.date_transfert)
        if date_operation is None or (depuis is not None and date_operation < depuis):
            continue
        if await _deja_comptabilise(db, organisation_id, "transferts", "transfert_interne", transfert.id):
            rapport.deja_en_compta += 1
            continue
        try:
            async with db.begin_nested():
                await generer_ecriture_transfert_interne(
                    db,
                    organisation_id=organisation_id,
                    sortie_fonds_id=str(transfert.id),
                    date_operation=date_operation,
                    montant=transfert.montant,
                    devise=transfert.devise,
                    compte_origine_bancaire_id=(
                        transfert.source_id if transfert.source_type == "BANQUE" else None
                    ),
                    compte_destination_bancaire_id=(
                        transfert.destination_id if transfert.destination_type == "BANQUE" else None
                    ),
                    libelle=transfert.reference
                    or f"Transfert interne {transfert.source_type} → {transfert.destination_type}",
                    created_by=transfert.execute_par,
                    module_origine="transferts",
                )
        except Exception as exc:  # noqa: BLE001 — reprise non bloquante
            rapport.echecs.append(f"transfert #{transfert.id} : {exc}")
            continue
        rapport.creees += 1
    return rapport


async def reprendre_organisation(
    db: AsyncSession, *, organisation_id: int, depuis: date | None
) -> Rapport:
    """Rejoue tous les faits générateurs d'une organisation. Ne committe pas."""
    rapport = Rapport()
    rapport.fusionner(await _reprendre_encaissements(db, organisation_id, depuis))
    rapport.fusionner(await _reprendre_sorties_fonds(db, organisation_id, depuis))
    rapport.fusionner(await _reprendre_transferts(db, organisation_id, depuis))
    return rapport


async def run_backfill(*, dry_run: bool, depuis: date | None, organisation: int | None) -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL manquant. Ex: export DATABASE_URL=postgresql+asyncpg://user:pass@host/db"
        )
    engine = create_async_engine(database_url, pool_pre_ping=True)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with SessionLocal() as db:
        set_current_tenant_id(None)
        res = await db.execute(
            select(ComptaSociete.organisation_id).where(ComptaSociete.is_default.is_(True))
        )
        organisation_ids = sorted({row for row, in res.all()})

    if organisation is not None:
        organisation_ids = [o for o in organisation_ids if o == organisation]
        if not organisation_ids:
            logging.warning(
                "L'organisation #%d n'a pas la comptabilité activée : rien à reprendre.", organisation
            )

    logging.info(
        "%d organisation(s) à traiter%s.",
        len(organisation_ids),
        f", opérations à partir du {depuis}" if depuis else " (tout l'historique)",
    )

    for organisation_id in organisation_ids:
        async with SessionLocal() as db:
            set_current_tenant_id(organisation_id)
            try:
                rapport = await reprendre_organisation(
                    db, organisation_id=organisation_id, depuis=depuis
                )
                if dry_run:
                    await db.rollback()
                else:
                    await db.commit()
                logging.info(
                    "%sorg #%d : %d écriture(s) générée(s), %d opération(s) déjà comptabilisée(s), %d échec(s).",
                    "[dry-run] " if dry_run else "",
                    organisation_id,
                    rapport.creees,
                    rapport.deja_en_compta,
                    len(rapport.echecs),
                )
                for echec in rapport.echecs:
                    logging.warning("  org #%d — non repris : %s", organisation_id, echec)
            except Exception:
                await db.rollback()
                logging.exception("org #%d : échec global de la reprise, organisation ignorée.", organisation_id)
            finally:
                set_current_tenant_id(None)

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Reprise d'historique : écritures comptables des opérations déjà en base"
    )
    parser.add_argument("--dry-run", action="store_true", help="Calculer sans écrire en base")
    parser.add_argument(
        "--depuis",
        type=lambda s: date.fromisoformat(s),
        default=None,
        help="Ne reprendre que les opérations à partir de cette date (AAAA-MM-JJ)",
    )
    parser.add_argument(
        "--organisation", type=int, default=None, help="Limiter à une seule organisation"
    )
    parser.add_argument("--log", type=str, default=None, help="Chemin de fichier log")
    args = parser.parse_args()

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if args.log:
        handlers.append(logging.FileHandler(args.log, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, handlers=handlers, format="%(message)s")

    asyncio.run(
        run_backfill(dry_run=args.dry_run, depuis=args.depuis, organisation=args.organisation)
    )
