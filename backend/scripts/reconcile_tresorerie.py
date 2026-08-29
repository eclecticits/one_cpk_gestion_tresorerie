"""Réconciliation de trésorerie — le filet de la bascule des transferts internes.

Ce script ne corrige rien et n'écrit rien. Il répond à une seule question :

    les soldes stockés sont-ils encore égaux à la somme des mouvements qui
    prétendent les expliquer ?

C'est la **photo de départ** du chantier de bascule. Tant que les transferts
internes s'écrivent dans `sorties_fonds` (chemin historique) et que la table
dédiée `transferts_internes` reçoit les nouveaux, chaque phase de la migration
déplace des écritures d'une source à l'autre. Sans une mesure prise *avant*,
un écart découvert *après* est indécidable : personne ne peut dire s'il vient
de la bascule ou s'il était déjà là.

D'où la règle d'usage : exécuter ce script sur une restauration du dump de
production **avant** de toucher à quoi que ce soit, garder sa sortie, et le
rejouer après chaque phase. Un écart qui n'était pas dans la photo de départ
est une régression ; un écart déjà présent est une dette, à traiter pour
elle-même mais qui ne doit pas bloquer la bascule.

Trois contrôles, dans l'ordre où ils se cassent :

**C1 — Caisse centrale.** `solde_stocké == solde initial + Σ entrées − Σ sorties`,
les entrées et les sorties étant lues sur **les deux sources à la fois**. La
formule reproduit exactement `_recalculate_treasury_balances`
(`app/api/v1/endpoints/treasury.py`) : c'est la définition que l'application se
donne à elle-même, et la réconciliation n'a pas à en inventer une autre.

**C2 — Comptes bancaires.** Même équation, par compte. Elle n'existe nulle part
dans l'application : aucun endpoint ne recalcule un solde bancaire. Elle est
dérivée ici des sept endroits qui écrivent `CompteBancaire.solde_actuel`
(encaissements, retours, sorties, versements, transferts internes) — la liste
est reprise dans `termes_compte_bancaire`, et toute nouvelle écriture de ce
champ doit y être ajoutée sous peine de faire mentir le contrôle.

**C3 — Lignes affichées contre totaux.** Un total qu'aucun écran ne peut
détailler est un total que personne ne peut vérifier. Ce contrôle compare
chaque terme d'entrée à la somme des lignes que les écrans savent afficher pour
lui, les deux sources unionnées de part et d'autre. Il redevient rouge dès
qu'un filtre est ajouté d'un seul côté — un statut ignoré dans la liste mais
pas dans l'agrégat, des bornes de date uniformisées entre deux tables qui ne
s'horodatent pas pareil. C'est le symptôme qu'il faut rendre impossible : une
clôture qui affiche une entrée de 500 $ que sa propre liste ne justifie pas.

Usage ::

    python -m scripts.reconcile_tresorerie                    # base courante
    python -m scripts.reconcile_tresorerie --tenant 18        # une organisation
    python -m scripts.reconcile_tresorerie --json > photo.json
    python -m scripts.reconcile_tresorerie --database-url postgresql+asyncpg://...

Code de sortie : 0 si tout tombe juste, 1 s'il reste un écart.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import pkgutil
import sys
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.encaissement import Encaissement
from app.models.organisation import Organisation
from app.models.retour_caisse import RetourCaisse
from app.models.sortie_fonds import SortieFonds
from app.models.transfert_interne import TransfertInterne


def _charger_tous_les_modeles() -> None:
    """Déclare toutes les classes avant que le premier mapper ne se configure.

    `Encaissement` référence `Service` par son nom, et l'import de
    `entrees_caisse` appelle `aliased(User)`, ce qui déclenche la configuration
    des mappers immédiatement. Sans ce chargement préalable, l'import échoue sur
    un nom introuvable. C'est une condition d'import, pas une précaution — même
    geste que `tests/conftest.py`.
    """
    import app.models as paquet

    for info in pkgutil.iter_modules(paquet.__path__, paquet.__name__ + "."):
        importlib.import_module(info.name)
    from app.modules.secretariat import models  # noqa: F401


_charger_tous_les_modeles()

from app.services.entrees_caisse import (  # noqa: E402
    list_entrees_internes_caisse,
    list_entrees_internes_banque,
)

DEVISES = ("USD", "CDF")

#: Un centime. Les montants sont des `Numeric(15, 2)` : en dessous de ce seuil,
#: l'écart ne peut venir que d'un arrondi de représentation, pas d'un mouvement.
TOLERANCE_PAR_DEFAUT = Decimal("0.01")


def _d(value) -> Decimal:
    return Decimal(str(value or 0))


def _sortie_validee():
    """Filtre de statut des sorties, repris à l'identique des agrégateurs.

    `statut IS NULL` compte comme validé : les sorties antérieures à
    l'introduction de la colonne n'en portent pas, et les exclure ferait
    apparaître un faux écart sur tout l'historique.
    """
    return (SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE")


def _encaissement_actif():
    return (
        (Encaissement.is_deleted.is_(False))
        & ((Encaissement.statut_operation.is_(None)) | (Encaissement.statut_operation == "ACTIVE"))
        & (Encaissement.est_proforma.is_(False))
    )


def _montant_encaisse(devise: str):
    """USD sur `montant_paye`, CDF sur `montant_percu` — comme la trésorerie.

    L'asymétrie n'est pas une coquette : `montant_paye` est en devise de
    facturation et `montant_percu` en devise de perception. Les inverser
    décalerait chaque encaissement du taux de change.
    """
    return Encaissement.montant_paye if devise == "USD" else Encaissement.montant_percu


# ---------------------------------------------------------------------------
# Résultats
# ---------------------------------------------------------------------------


@dataclass
class Controle:
    """Un solde comparé à la somme des mouvements qui l'expliquent."""

    perimetre: str
    devise: str
    stocke: Decimal
    attendu: Decimal
    termes: dict[str, Decimal] = field(default_factory=dict)

    @property
    def ecart(self) -> Decimal:
        return self.stocke - self.attendu

    def juste(self, tolerance: Decimal) -> bool:
        return abs(self.ecart) <= tolerance

    def en_dict(self) -> dict:
        return {
            "perimetre": self.perimetre,
            "devise": self.devise,
            "stocke": str(self.stocke),
            "attendu": str(self.attendu),
            "ecart": str(self.ecart),
            "termes": {nom: str(valeur) for nom, valeur in self.termes.items()},
        }


@dataclass
class Couverture:
    """Un total agrégé face aux lignes qu'un écran sait afficher pour lui."""

    terme: str
    devise: str
    total: Decimal
    affichable: Decimal
    lignes: int
    chemin_affichage: str | None

    @property
    def ecart(self) -> Decimal:
        return self.total - self.affichable

    def juste(self, tolerance: Decimal) -> bool:
        return abs(self.ecart) <= tolerance

    def en_dict(self) -> dict:
        return {
            "terme": self.terme,
            "devise": self.devise,
            "total": str(self.total),
            "affichable": str(self.affichable),
            "ecart": str(self.ecart),
            "lignes": self.lignes,
            "chemin_affichage": self.chemin_affichage,
        }


@dataclass
class RapportOrganisation:
    organisation_id: int
    nom: str
    caisse: list[Controle] = field(default_factory=list)
    banques: list[Controle] = field(default_factory=list)
    couverture: list[Couverture] = field(default_factory=list)

    def ecarts(self, tolerance: Decimal) -> list[Controle | Couverture]:
        return [
            item
            for item in [*self.caisse, *self.banques, *self.couverture]
            if not item.juste(tolerance)
        ]

    def en_dict(self, tolerance: Decimal) -> dict:
        return {
            "organisation_id": self.organisation_id,
            "nom": self.nom,
            "caisse": [item.en_dict() for item in self.caisse],
            "banques": [item.en_dict() for item in self.banques],
            "couverture": [item.en_dict() for item in self.couverture],
            "conforme": not self.ecarts(tolerance),
        }


# ---------------------------------------------------------------------------
# C1 — Caisse centrale
# ---------------------------------------------------------------------------


async def _somme(db: AsyncSession, colonne, *filtres) -> Decimal:
    query = select(func.coalesce(func.sum(colonne), 0)).where(*filtres)
    return _d((await db.execute(query)).scalar_one())


async def termes_caisse(db: AsyncSession, tenant_id: int, devise: str) -> dict[str, Decimal]:
    """Décomposition du solde de caisse attendu, terme à terme.

    Reproduit `_recalculate_treasury_balances`. Les deux sources y sont déjà
    unionnées : `approvisionnements` vient de `sorties_fonds`, `transferts_*`
    de la table dédiée. Une opération vit dans exactement une des deux, donc
    l'union ne double compte pas — c'est l'invariant qui rend la bascule
    possible sans migration de données, et le contrôle qui le vérifie.
    """
    solde_initial = await _somme(
        db,
        CompteBancaire.solde_initial,
        CompteBancaire.organisation_id == tenant_id,
        CompteBancaire.account_type == "CASH",
        CompteBancaire.devise == devise,
        CompteBancaire.is_active.is_(True),
    )
    encaissements = await _somme(
        db,
        _montant_encaisse(devise),
        Encaissement.organisation_id == tenant_id,
        Encaissement.canal == "CAISSE",
        Encaissement.devise_perception == devise,
        _encaissement_actif(),
    )
    approvisionnements = await _somme(
        db,
        SortieFonds.montant_paye,
        SortieFonds.organisation_id == tenant_id,
        SortieFonds.type_sortie == "approvisionnement_caisse",
        SortieFonds.devise == devise,
        _sortie_validee(),
    )
    retours = await _somme(
        db,
        RetourCaisse.montant,
        RetourCaisse.organisation_id == tenant_id,
        RetourCaisse.statut == "VALIDE",
        RetourCaisse.canal == "CAISSE",
        RetourCaisse.devise == devise,
    )
    sorties = await _somme(
        db,
        SortieFonds.montant_paye,
        SortieFonds.organisation_id == tenant_id,
        SortieFonds.canal == "CAISSE",
        SortieFonds.devise == devise,
        _sortie_validee(),
    )
    # Aucun filtre sur `statut` : la contre-passation est additive, l'original
    # (CONTREPASSE) et sa ligne inverse (EXECUTE) coexistent et s'annulent.
    # Exclure l'original en gardant l'inverse créerait de l'argent.
    transferts_entrants = await _somme(
        db,
        TransfertInterne.montant,
        TransfertInterne.organisation_id == tenant_id,
        TransfertInterne.destination_type == "CAISSE",
        TransfertInterne.devise == devise,
    )
    transferts_sortants = await _somme(
        db,
        TransfertInterne.montant,
        TransfertInterne.organisation_id == tenant_id,
        TransfertInterne.source_type == "CAISSE",
        TransfertInterne.devise == devise,
    )
    return {
        "solde_initial": solde_initial,
        "encaissements": encaissements,
        "approvisionnements": approvisionnements,
        "transferts_entrants": transferts_entrants,
        "retours": retours,
        "sorties": -sorties,
        "transferts_sortants": -transferts_sortants,
    }


async def controler_caisse(db: AsyncSession, tenant_id: int) -> list[Controle]:
    caisse = await db.scalar(
        select(CaisseCentrale).where(CaisseCentrale.organisation_id == tenant_id).limit(1)
    )
    controles: list[Controle] = []
    for devise in DEVISES:
        termes = await termes_caisse(db, tenant_id, devise)
        stocke = Decimal("0")
        if caisse is not None:
            stocke = _d(caisse.solde_usd if devise == "USD" else caisse.solde_cdf)
        controles.append(
            Controle(
                perimetre="Caisse centrale",
                devise=devise,
                stocke=stocke,
                attendu=sum(termes.values(), Decimal("0")),
                termes=termes,
            )
        )
    return controles


# ---------------------------------------------------------------------------
# C2 — Comptes bancaires
# ---------------------------------------------------------------------------


async def termes_compte_bancaire(db: AsyncSession, compte: CompteBancaire) -> dict[str, Decimal]:
    """Décomposition du solde bancaire attendu, terme à terme.

    Dérivée des seuls endroits qui écrivent `CompteBancaire.solde_actuel` :

    - `banques.py` à la création (``solde_actuel = solde_initial``) ;
    - `encaissement_payments.py` (crédit d'un paiement, débit de son annulation) ;
    - `retours_caisse.py` (crédit d'un retour, débit de son annulation) ;
    - `sorties_fonds.py` (débit d'une sortie canal BANQUE — approvisionnement
      de caisse compris —, crédit du compte de destination d'un versement, et
      les mouvements inverses à l'annulation) ;
    - `transferts_internes_service.py` (les deux jambes du moteur dédié).

    Les annulations n'apparaissent pas comme des termes : elles remettent la
    ligne d'origine hors du périmètre (`statut != VALIDE`), ce que les filtres
    ci-dessous traduisent déjà. **Toute nouvelle écriture de `solde_actuel`
    doit être ajoutée ici**, faute de quoi le contrôle signalera un écart qui
    n'en est pas un — ou pire, taira un vrai.
    """
    tenant_id = compte.organisation_id
    devise = (compte.devise or "USD").upper()
    encaissements = await _somme(
        db,
        _montant_encaisse(devise),
        Encaissement.organisation_id == tenant_id,
        Encaissement.canal == "BANQUE",
        Encaissement.compte_bancaire_id == compte.id,
        Encaissement.devise_perception == devise,
        _encaissement_actif(),
    )
    retours = await _somme(
        db,
        RetourCaisse.montant,
        RetourCaisse.organisation_id == tenant_id,
        RetourCaisse.statut == "VALIDE",
        RetourCaisse.canal == "BANQUE",
        RetourCaisse.compte_bancaire_id == compte.id,
        RetourCaisse.devise == devise,
    )
    # Un versement caisse → banque porte `canal = CAISSE` et le compte de
    # DESTINATION dans `compte_bancaire_id` : il crédite donc ce compte sans
    # jamais entrer dans la somme des débits ci-dessous. Les deux termes ne se
    # recouvrent pas.
    versements = await _somme(
        db,
        SortieFonds.montant_paye,
        SortieFonds.organisation_id == tenant_id,
        SortieFonds.type_sortie == "versement_banque",
        SortieFonds.compte_bancaire_id == compte.id,
        SortieFonds.devise == devise,
        _sortie_validee(),
    )
    sorties = await _somme(
        db,
        SortieFonds.montant_paye,
        SortieFonds.organisation_id == tenant_id,
        SortieFonds.canal == "BANQUE",
        SortieFonds.compte_bancaire_id == compte.id,
        SortieFonds.devise == devise,
        _sortie_validee(),
    )
    transferts_entrants = await _somme(
        db,
        TransfertInterne.montant,
        TransfertInterne.organisation_id == tenant_id,
        TransfertInterne.destination_type == "BANQUE",
        TransfertInterne.destination_id == compte.id,
        TransfertInterne.devise == devise,
    )
    transferts_sortants = await _somme(
        db,
        TransfertInterne.montant,
        TransfertInterne.organisation_id == tenant_id,
        TransfertInterne.source_type == "BANQUE",
        TransfertInterne.source_id == compte.id,
        TransfertInterne.devise == devise,
    )
    return {
        "solde_initial": _d(compte.solde_initial),
        "encaissements": encaissements,
        "versements_recus": versements,
        "transferts_entrants": transferts_entrants,
        "retours": retours,
        "sorties": -sorties,
        "transferts_sortants": -transferts_sortants,
    }


async def controler_comptes_bancaires(db: AsyncSession, tenant_id: int) -> list[Controle]:
    comptes = (
        await db.execute(
            select(CompteBancaire)
            .where(
                CompteBancaire.organisation_id == tenant_id,
                CompteBancaire.account_type == "BANK",
            )
            .order_by(CompteBancaire.id.asc())
        )
    ).scalars().all()
    controles: list[Controle] = []
    for compte in comptes:
        termes = await termes_compte_bancaire(db, compte)
        libelle = compte.intitule or compte.numero_compte or f"compte {compte.id}"
        controles.append(
            Controle(
                perimetre=f"Banque #{compte.id} — {libelle}",
                devise=(compte.devise or "USD").upper(),
                stocke=_d(compte.solde_actuel),
                attendu=sum(termes.values(), Decimal("0")),
                termes=termes,
            )
        )
    return controles


# ---------------------------------------------------------------------------
# C3 — Lignes affichées contre totaux
# ---------------------------------------------------------------------------


async def controler_couverture_affichage(db: AsyncSession, tenant_id: int) -> list[Couverture]:
    """Chaque total d'entrée est-il justifiable, ligne à ligne, par un écran ?

    Depuis la Phase 1, `app/services/entrees_caisse.py` unionne les deux
    sources, comme le font depuis toujours les agrégateurs. Ce contrôle vérifie
    que l'union des lignes somme **exactement** l'union des totaux.

    Il redevient rouge le jour où quelqu'un ajoute un filtre d'un seul côté —
    un statut ignoré dans la liste mais pas dans l'agrégat, une borne de date
    uniformisée entre les deux sources. C'est précisément le genre de
    modification qui semble anodine et qui fait afficher à une clôture un total
    que sa propre liste ne justifie pas.
    """
    resultats: list[Couverture] = []
    for devise in DEVISES:
        # Entrées en caisse : approvisionnements du chemin historique + les
        # transferts du moteur dédié dont la destination est la caisse. C'est
        # terme pour terme le total repris par `clotures._appro_sum` et
        # `clotures._transf_sum(as_destination=True)`.
        approvisionnements = await _somme(
            db,
            SortieFonds.montant_paye,
            SortieFonds.organisation_id == tenant_id,
            SortieFonds.type_sortie == "approvisionnement_caisse",
            SortieFonds.devise == devise,
            _sortie_validee(),
        )
        transferts_caisse = await _somme(
            db,
            TransfertInterne.montant,
            TransfertInterne.organisation_id == tenant_id,
            TransfertInterne.destination_type == "CAISSE",
            TransfertInterne.devise == devise,
        )
        lignes_caisse = await list_entrees_internes_caisse(db, tenant_id=tenant_id, devise=devise)
        resultats.append(
            Couverture(
                terme="entrées de caisse : approvisionnements + transferts",
                devise=devise,
                total=approvisionnements + transferts_caisse,
                affichable=sum((ligne["montant"] for ligne in lignes_caisse), Decimal("0")),
                lignes=len(lignes_caisse),
                chemin_affichage="entrees_caisse.list_entrees_internes_caisse",
            )
        )

        versements = await _somme(
            db,
            SortieFonds.montant_paye,
            SortieFonds.organisation_id == tenant_id,
            SortieFonds.type_sortie == "versement_banque",
            SortieFonds.devise == devise,
            _sortie_validee(),
        )
        transferts_banque = await _somme(
            db,
            TransfertInterne.montant,
            TransfertInterne.organisation_id == tenant_id,
            TransfertInterne.destination_type == "BANQUE",
            TransfertInterne.devise == devise,
        )
        lignes_banque = await list_entrees_internes_banque(db, tenant_id=tenant_id, devise=devise)
        resultats.append(
            Couverture(
                terme="entrées bancaires : versements + transferts",
                devise=devise,
                total=versements + transferts_banque,
                affichable=sum((ligne["montant"] for ligne in lignes_banque), Decimal("0")),
                lignes=len(lignes_banque),
                chemin_affichage="entrees_caisse.list_entrees_internes_banque",
            )
        )
    return resultats


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def reconcilier_organisation(db: AsyncSession, *, organisation_id: int, nom: str = "") -> RapportOrganisation:
    return RapportOrganisation(
        organisation_id=organisation_id,
        nom=nom,
        caisse=await controler_caisse(db, organisation_id),
        banques=await controler_comptes_bancaires(db, organisation_id),
        couverture=await controler_couverture_affichage(db, organisation_id),
    )


async def reconcilier(db: AsyncSession, *, tenant_id: int | None = None) -> list[RapportOrganisation]:
    query = select(Organisation.id, Organisation.nom).order_by(Organisation.id.asc())
    if tenant_id is not None:
        query = query.where(Organisation.id == tenant_id)
    organisations = (await db.execute(query)).all()
    return [
        await reconcilier_organisation(db, organisation_id=row.id, nom=row.nom or "")
        for row in organisations
    ]


# ---------------------------------------------------------------------------
# Restitution
# ---------------------------------------------------------------------------


def _formater(rapports: list[RapportOrganisation], tolerance: Decimal) -> str:
    lignes: list[str] = []
    for rapport in rapports:
        entete = f"Organisation {rapport.organisation_id} — {rapport.nom or 'sans nom'}"
        lignes.append(entete)
        lignes.append("-" * len(entete))

        for controle in [*rapport.caisse, *rapport.banques]:
            # Un périmètre à zéro des deux côtés n'apprend rien : le bruit de
            # dizaines de comptes vides masquerait le seul écart qui compte.
            if controle.stocke == 0 and controle.attendu == 0:
                continue
            marque = "OK  " if controle.juste(tolerance) else "ÉCART"
            lignes.append(
                f"  {marque} {controle.perimetre} [{controle.devise}] : "
                f"stocké {controle.stocke} / attendu {controle.attendu} "
                f"(écart {controle.ecart})"
            )
            if not controle.juste(tolerance):
                for nom, valeur in controle.termes.items():
                    lignes.append(f"         {nom:.<28} {valeur:>18}")

        for couverture in rapport.couverture:
            if couverture.total == 0 and couverture.affichable == 0:
                continue
            marque = "OK  " if couverture.juste(tolerance) else "ÉCART"
            chemin = couverture.chemin_affichage or "AUCUN CHEMIN D'AFFICHAGE"
            lignes.append(
                f"  {marque} {couverture.terme} [{couverture.devise}] : "
                f"total {couverture.total} / affichable {couverture.affichable} "
                f"sur {couverture.lignes} ligne(s) — {chemin}"
            )

        ecarts = rapport.ecarts(tolerance)
        lignes.append(
            "  → conforme" if not ecarts else f"  → {len(ecarts)} écart(s) à instruire"
        )
        lignes.append("")

    total_ecarts = sum(len(rapport.ecarts(tolerance)) for rapport in rapports)
    lignes.append(
        f"{len(rapports)} organisation(s) contrôlée(s), {total_ecarts} écart(s) au total."
    )
    return "\n".join(lignes)


async def _executer(args: argparse.Namespace) -> int:
    from app.core.config import settings

    url = args.database_url or settings.database_url
    engine = create_async_engine(url, pool_pre_ping=True)
    fabrique = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    tolerance = Decimal(str(args.tolerance))
    try:
        async with fabrique() as db:
            rapports = await reconcilier(db, tenant_id=args.tenant)
    finally:
        await engine.dispose()

    if args.json:
        print(
            json.dumps(
                {
                    "tolerance": str(tolerance),
                    "organisations": [rapport.en_dict(tolerance) for rapport in rapports],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(_formater(rapports, tolerance))

    return 0 if all(not rapport.ecarts(tolerance) for rapport in rapports) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tenant", type=int, default=None, help="limiter à une organisation")
    parser.add_argument("--database-url", default=None, help="base à contrôler (défaut : celle de la configuration)")
    parser.add_argument("--tolerance", default=str(TOLERANCE_PAR_DEFAUT), help="écart toléré, en unité de devise")
    parser.add_argument("--json", action="store_true", help="rapport machine plutôt que lisible")
    return asyncio.run(_executer(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
