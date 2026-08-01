"""Calcul des états financiers (Lot 5) — Bilan, Résultat, SIG, Flux.

Le moteur ne connaît **aucun numéro de compte** : il lit la structure de
l'état dans `compta_postes_etat` et agrège les soldes selon les
rattachements de `compta_poste_etat_comptes`. Changer de référentiel, ou
adapter la présentation, relève donc du paramétrage.

**Deux modes de valorisation**, déterminés par le type d'état :
- *solde* (Bilan, Résultat, SIG) : le compte apporte son solde de l'exercice
  jusqu'à la date d'arrêté ;
- *variation* (Flux) : le compte apporte la variation de son solde sur la
  période, c'est-à-dire son solde final moins son solde d'ouverture.

**Le filtre de sens s'applique compte par compte, avant agrégation.** C'est
le point subtil : un poste « Créances clients » qui retiendrait le solde
global du collectif 41 masquerait le fait qu'un adhérent est créditeur. On
retient donc chaque compte individuellement selon le sens de SON solde, ce
qui envoie automatiquement les clients créditeurs au passif.

Comme les restitutions du Lot 4, ces états ne retiennent que les écritures
VALIDEE et CLOTUREE (cf. `reporting_service`), et le filtre `organisation_id`
est explicite sur chaque requête (contrainte C2).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.comptabilite.models import (
    ComptaCompte,
    ComptaEcriture,
    ComptaExercice,
    ComptaLigneEcriture,
    ComptaPosteEtat,
    ComptaPosteEtatCompte,
)
from app.modules.comptabilite.services.reporting_service import statuts_retenus

# Les états de flux raisonnent en variation de solde, les autres en solde.
TYPES_ETAT_VARIATION = {"FLUX"}


@dataclass
class SoldeCompte:
    compte_id: int
    numero: str
    libelle: str
    debit: Decimal
    credit: Decimal

    @property
    def solde(self) -> Decimal:
        """Solde algébrique : positif si débiteur, négatif si créditeur."""
        return self.debit - self.credit


@dataclass
class LigneEtat:
    """Ligne d'un état, restituée à plat.

    La hiérarchie sert au CALCUL des totaux ; la présentation, elle, est une
    liste ordonnée où l'indentation se lit dans `niveau` — un total se place
    après les lignes qu'il totalise, ce qu'un arbre imbriqué rendrait mal.
    """

    poste_id: int
    code: str
    libelle: str
    niveau: int
    est_total: bool
    sens_normal: str
    brut: Decimal
    amortissement: Decimal

    @property
    def net(self) -> Decimal:
        return self.brut - self.amortissement


@dataclass
class Etat:
    type_etat: str
    exercice_id: int
    devise_tenue: str
    date_arrete: date
    inclure_brouillons: bool
    lignes: list[LigneEtat]
    total: Decimal
    comptes_non_couverts: list[str]


async def _soldes_par_compte(
    db: AsyncSession,
    *,
    organisation_id: int,
    exercice_id: int,
    statuts: tuple[str, ...],
    date_debut: date | None = None,
    date_fin: date | None = None,
) -> dict[int, SoldeCompte]:
    stmt = (
        select(
            ComptaCompte.id,
            ComptaCompte.numero,
            ComptaCompte.libelle,
            func.coalesce(func.sum(ComptaLigneEcriture.debit_tenue), 0).label("debit"),
            func.coalesce(func.sum(ComptaLigneEcriture.credit_tenue), 0).label("credit"),
        )
        .select_from(ComptaLigneEcriture)
        .join(ComptaEcriture, ComptaEcriture.id == ComptaLigneEcriture.ecriture_id)
        .join(ComptaCompte, ComptaCompte.id == ComptaLigneEcriture.compte_id)
        .where(
            ComptaLigneEcriture.organisation_id == organisation_id,
            ComptaEcriture.organisation_id == organisation_id,
            ComptaEcriture.exercice_id == exercice_id,
            ComptaEcriture.statut.in_(statuts),
        )
        .group_by(ComptaCompte.id, ComptaCompte.numero, ComptaCompte.libelle)
    )
    if date_debut is not None:
        stmt = stmt.where(ComptaEcriture.date_ecriture >= date_debut)
    if date_fin is not None:
        stmt = stmt.where(ComptaEcriture.date_ecriture <= date_fin)

    res = await db.execute(stmt)
    return {
        row.id: SoldeCompte(
            compte_id=row.id, numero=row.numero, libelle=row.libelle,
            debit=Decimal(row.debit or 0), credit=Decimal(row.credit or 0),
        )
        for row in res.all()
    }


def _retenu(solde: Decimal, filtre_solde: str) -> bool:
    """Le compte entre-t-il dans ce poste, au vu du sens de son solde ?"""
    if filtre_solde == "DEBITEUR":
        return solde > 0
    if filtre_solde == "CREDITEUR":
        return solde < 0
    return True


def _comptes_du_rattachement(
    rattachement: ComptaPosteEtatCompte, soldes: dict[int, SoldeCompte]
) -> list[SoldeCompte]:
    if rattachement.compte_id is not None:
        compte = soldes.get(rattachement.compte_id)
        return [compte] if compte is not None else []
    prefixe = rattachement.prefixe_compte or ""
    return [s for s in soldes.values() if s.numero.startswith(prefixe)]


async def calculer_etat(
    db: AsyncSession,
    *,
    organisation_id: int,
    exercice_id: int,
    type_etat: str,
    date_arrete: date | None = None,
    inclure_brouillons: bool = False,
) -> Etat:
    """Calcule un état financier pour un exercice.

    `date_arrete` permet un arrêté intermédiaire (situation au 30/06 par
    exemple) ; par défaut, la fin de l'exercice.
    """
    exercice = await db.get(ComptaExercice, exercice_id)
    if exercice is None or exercice.organisation_id != organisation_id:
        raise ValueError("Exercice introuvable pour cette organisation.")

    arrete = date_arrete or exercice.date_fin
    statuts = statuts_retenus(inclure_brouillons)

    postes_res = await db.execute(
        select(ComptaPosteEtat)
        .where(
            ComptaPosteEtat.organisation_id == organisation_id,
            ComptaPosteEtat.referentiel_id == exercice.referentiel_id,
            ComptaPosteEtat.type_etat == type_etat,
        )
        .order_by(ComptaPosteEtat.ordre)
    )
    postes = list(postes_res.scalars().all())
    if not postes:
        raise ValueError(
            f"Aucune structure d'état « {type_etat} » pour le référentiel de cet exercice."
        )

    rattachements_res = await db.execute(
        select(ComptaPosteEtatCompte).where(
            ComptaPosteEtatCompte.organisation_id == organisation_id,
            ComptaPosteEtatCompte.poste_etat_id.in_([p.id for p in postes]),
        )
    )
    rattachements_par_poste: dict[int, list[ComptaPosteEtatCompte]] = {}
    for r in rattachements_res.scalars().all():
        rattachements_par_poste.setdefault(r.poste_etat_id, []).append(r)

    soldes = await _soldes_par_compte(
        db, organisation_id=organisation_id, exercice_id=exercice_id,
        statuts=statuts, date_fin=arrete,
    )

    if type_etat in TYPES_ETAT_VARIATION:
        # Variation = solde à l'arrêté − solde d'ouverture. L'ouverture est
        # portée par les à-nouveaux, seules écritures antérieures au premier
        # jour d'activité de l'exercice ; en l'absence de clôture précédente,
        # elle est nulle et la variation se confond avec le solde.
        ouverture = await _soldes_par_compte(
            db, organisation_id=organisation_id, exercice_id=exercice_id,
            statuts=statuts, date_fin=exercice.date_debut,
        )
        for compte_id, solde in soldes.items():
            depart = ouverture.get(compte_id)
            if depart is not None:
                solde.debit -= depart.debit
                solde.credit -= depart.credit

    # ── Valorisation des feuilles ────────────────────────────────────────────
    valeurs: dict[int, tuple[Decimal, Decimal]] = {}  # poste_id → (brut, amortissement)
    comptes_couverts: set[int] = set()

    for poste in postes:
        if poste.est_total:
            continue
        brut = Decimal("0")
        amortissement = Decimal("0")
        for rattachement in rattachements_par_poste.get(poste.id, []):
            for compte in _comptes_du_rattachement(rattachement, soldes):
                if not _retenu(compte.solde, rattachement.filtre_solde):
                    continue
                comptes_couverts.add(compte.compte_id)
                # Orientation du poste : un poste de passif ou de produit
                # affiche (crédit − débit) pour rester positif.
                valeur = compte.solde if poste.sens_normal == "DEBIT" else -compte.solde
                valeur *= rattachement.signe
                if rattachement.colonne == "AMORTISSEMENT":
                    amortissement += valeur
                else:
                    brut += valeur
        valeurs[poste.id] = (brut, amortissement)

    # ── Remontée des totaux, des feuilles vers la racine ─────────────────────
    enfants_par_parent: dict[int | None, list[ComptaPosteEtat]] = {}
    for poste in postes:
        enfants_par_parent.setdefault(poste.parent_id, []).append(poste)

    def valoriser(poste: ComptaPosteEtat) -> tuple[Decimal, Decimal]:
        if not poste.est_total:
            return valeurs[poste.id]
        brut = Decimal("0")
        amortissement = Decimal("0")
        for enfant in enfants_par_parent.get(poste.id, []):
            b, a = valoriser(enfant)
            brut += b * enfant.signe
            amortissement += a * enfant.signe
        valeurs[poste.id] = (brut, amortissement)
        return brut, amortissement

    # L'ordre d'affichage est celui du paramétrage (`ordre`), pas celui de
    # l'arbre : un total est présenté après les lignes qu'il totalise.
    lignes: list[LigneEtat] = []
    for poste in postes:
        brut, amortissement = valoriser(poste)
        lignes.append(
            LigneEtat(
                poste_id=poste.id, code=poste.code, libelle=poste.libelle,
                niveau=poste.niveau, est_total=poste.est_total, sens_normal=poste.sens_normal,
                brut=brut, amortissement=amortissement,
            )
        )

    # Le total de l'état est porté par son unique ligne de niveau 0 (TOTAL
    # ACTIF, RÉSULTAT NET, VARIATION DE TRÉSORERIE…). Sommer les racines
    # n'aurait aucun sens pour les SIG, où chaque solde est déjà cumulatif.
    sommet = next((l for l in lignes if l.niveau == 0), None)
    total = sommet.net if sommet is not None else Decimal("0")

    # ── Contrôle de couverture ───────────────────────────────────────────────
    # Un compte mouvementé qui n'entre dans aucun poste disparaîtrait
    # silencieusement de l'état — c'est la faiblesse d'un rattachement par
    # préfixe, et la raison d'être de ce contrôle.
    non_couverts = sorted(
        f"{s.numero} — {s.libelle}"
        for s in soldes.values()
        if s.compte_id not in comptes_couverts and (s.debit != 0 or s.credit != 0)
    )

    return Etat(
        type_etat=type_etat,
        exercice_id=exercice_id,
        devise_tenue=exercice.devise_tenue,
        date_arrete=arrete,
        inclure_brouillons=inclure_brouillons,
        lignes=lignes,
        total=total,
        comptes_non_couverts=non_couverts,
    )


@dataclass
class ControleBilan:
    total_actif: Decimal
    total_passif: Decimal
    ecart: Decimal
    equilibre: bool
    comptes_non_couverts: list[str]


async def controler_bilan(
    db: AsyncSession,
    *,
    organisation_id: int,
    exercice_id: int,
    date_arrete: date | None = None,
    inclure_brouillons: bool = False,
) -> ControleBilan:
    """Vérifie que l'actif égale le passif.

    Un écart ne vient presque jamais d'un déséquilibre comptable — celui-ci
    est garanti écriture par écriture — mais d'un **trou de paramétrage** :
    un compte mouvementé qui n'entre dans aucun poste. Les comptes concernés
    sont donc retournés avec l'écart, faute de quoi l'utilisateur n'aurait
    aucune piste.

    La couverture est appréciée sur les **trois** états à la fois (actif,
    passif, résultat) : pris isolément, chacun laisse légitimement de côté les
    comptes qui ne le concernent pas — la caisse n'a rien à faire au compte de
    résultat. Seul un compte absent des trois est un vrai trou.
    """
    etats = {}
    for type_etat in ("BILAN_ACTIF", "BILAN_PASSIF", "RESULTAT"):
        etats[type_etat] = await calculer_etat(
            db, organisation_id=organisation_id, exercice_id=exercice_id,
            type_etat=type_etat, date_arrete=date_arrete, inclure_brouillons=inclure_brouillons,
        )

    actif = etats["BILAN_ACTIF"]
    passif = etats["BILAN_PASSIF"]
    ecart = actif.total - passif.total
    non_couverts = set(actif.comptes_non_couverts)
    for autre in ("BILAN_PASSIF", "RESULTAT"):
        non_couverts &= set(etats[autre].comptes_non_couverts)

    return ControleBilan(
        total_actif=actif.total,
        total_passif=passif.total,
        ecart=ecart,
        equilibre=ecart == 0,
        comptes_non_couverts=sorted(non_couverts),
    )
