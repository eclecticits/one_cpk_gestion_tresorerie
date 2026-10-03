"""Ré-imputation d'un encaissement sur un autre poste budgétaire.

Le pendant, côté recettes, de `reimputation_budgetaire` (réquisitions). Corriger
le poste d'un encaissement déjà payé ne revient pas à changer une colonne : le
poste vit à cinq endroits, et trois d'entre eux portent de l'argent.

    encaissements.budget_poste_id          -> en-tête, imprimé sur le reçu ;
                                              repli des lignes muettes et des
                                              versements antérieurs au registre
    encaissement_articles.budget_poste_id  -> d'où chaque versement se répartit
    payment_history.budget_poste_id        -> poste retenu par le versement
    mouvement_budget_imputations           -> le réalisé, tel que le lit l'exécution
    budget_postes.montant_paye             -> compteur alimenté par ces imputations

Un reçu peut mêler plusieurs natures — une cotisation et des frais
d'inscription —, donc plusieurs postes. `article_ids` désigne les lignes qui
bougent ; omis, toute la note suit.

Une imputation de versement ne sait pas de quel article elle vient : elle est
née d'un prorata (`repartir`). Elle cède donc au prorata des articles de SON
poste qui partent. Quand tous partent, elle part entière. L'imputation d'origine
n'est jamais réécrite : elle passe ANNULEE et deux ACTIVE la remplacent, une par
poste. Le total du réalisé est invariant.

Ce qu'elle refuse :
  - une écriture comptable validée : le poste a servi à choisir le compte de
    produit, la correction revient au comptable. Un brouillon, lui, n'a pas
    atteint le Grand Livre : ses lignes de produit sont réécrites ;
  - un exercice clôturé, au départ comme à l'arrivée, ou un changement
    d'exercice : une recette de 2026 ne devient pas une recette de 2027 ;
  - une note reportée en arriérés, dont les versements suivent déjà les postes
    d'arriérés ;
  - un encaissement hors budget (« Affecter au budget » existe pour lui), de
    fonds de tiers, annulé ou supprimé ;
  - de partager un impact que rien ne permet de partager : versement antérieur
    au registre, ou imputation de régularisation posée sur un poste qu'aucun
    article n'occupe. Ceux-là ne se déplacent qu'avec toute la note.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetPoste
from app.models.encaissement import Encaissement, EncaissementArticle
from app.models.mouvement_budget_imputation import MouvementBudgetImputation
from app.models.payment_history import PaymentHistory
from app.models.service_rubrique import ServiceRubrique
from app.modules.comptabilite.models import ComptaEcriture
from app.modules.comptabilite.services.generation_service import reecrire_produits_ecriture_brouillon
from app.services.report_creances import reports_actifs, verifier_postes_ouverts

CENTIME = Decimal("0.01")
UN = Decimal("1")
ZERO = Decimal("0")

PAIEMENT_ACTIF = "ACTIF"
# Une écriture sortie du brouillon a atteint le Grand Livre : elle ne se
# réécrit plus, elle se contre-passe — c'est l'affaire du comptable.
ECRITURES_FIGEES = {"VALIDEE", "CLOTUREE"}


def _montant(valeur: Any) -> Decimal:
    return Decimal(str(valeur or 0))


def _au_centime(valeur: Decimal) -> Decimal:
    return valeur.quantize(CENTIME, rounding=ROUND_HALF_UP)


@dataclass
class _Plan:
    """Ce qu'un déplacement toucherait, établi une fois pour l'aperçu et l'écriture."""

    encaissement: Encaissement
    nouveau_poste: BudgetPoste
    articles: list[EncaissementArticle]
    deplaces: list[EncaissementArticle]
    # La note entière part : chaque impact s'en va sans prorata.
    complete: bool
    postes_avant: list[int]
    # Part des articles qui partent, poste par poste.
    ratio_par_poste: dict[int, Decimal]
    paiements: dict[uuid.UUID, PaymentHistory] = field(default_factory=dict)
    imputations: list[MouvementBudgetImputation] = field(default_factory=list)
    # Versements actifs sans imputation : antérieurs au registre, ils ne se
    # lisent que par leur poste (ou celui de l'en-tête).
    versements_hors_registre: list[PaymentHistory] = field(default_factory=list)
    # Note payée d'avant l'historique des versements : son montant ne vit que
    # sur l'en-tête.
    note_hors_registre: bool = False
    ecritures: dict[uuid.UUID, ComptaEcriture] = field(default_factory=dict)

    def poste_de(self, article: EncaissementArticle) -> int | None:
        """Une ligne muette s'impute là où l'encaissement s'impute."""
        return article.budget_poste_id or self.encaissement.budget_poste_id

    def ratio_pour(self, poste_id: int | None) -> Decimal | None:
        """Ce qu'un impact posé sur ce poste doit céder. `None` : on ne sait pas le dire."""
        if self.complete:
            return UN
        if poste_id is None:
            return None
        return self.ratio_par_poste.get(poste_id)

    def part_imputation(self, imp: MouvementBudgetImputation) -> Decimal:
        ratio = self.ratio_pour(imp.budget_poste_id) or ZERO
        montant = _montant(imp.montant_budget)
        return montant if ratio == UN else _au_centime(montant * ratio)

    def poste_versement(self, paiement: PaymentHistory) -> int | None:
        return paiement.budget_poste_id or self.encaissement.budget_poste_id

    @property
    def versements_deplaces(self) -> list[PaymentHistory]:
        return [p for p in self.versements_hors_registre if self.ratio_pour(self.poste_versement(p)) == UN]

    @property
    def imputations_cedantes(self) -> list[MouvementBudgetImputation]:
        return [imp for imp in self.imputations if self.part_imputation(imp) > 0]

    @property
    def paiements_touches(self) -> set[uuid.UUID]:
        touches = {imp.payment_history_id for imp in self.imputations_cedantes if imp.payment_history_id}
        touches.update(p.id for p in self.versements_deplaces)
        return touches

    @property
    def montant_deplace(self) -> Decimal:
        """Le réalisé qui change de poste, en devise budgétaire."""
        total = sum((self.part_imputation(imp) for imp in self.imputations), ZERO)
        total += sum((_montant(p.montant) for p in self.versements_deplaces), ZERO)
        if self.note_hors_registre and self.complete:
            total += _montant(self.encaissement.montant_paye)
        return total

    @property
    def postes_cedants(self) -> set[int]:
        postes = {imp.budget_poste_id for imp in self.imputations_cedantes}
        postes.update(pid for p in self.versements_deplaces if (pid := self.poste_versement(p)))
        if self.note_hors_registre and self.complete and self.encaissement.budget_poste_id:
            postes.add(self.encaissement.budget_poste_id)
        return postes

    @property
    def ecritures_a_reecrire(self) -> list[ComptaEcriture]:
        return [
            ecriture
            for pid, ecriture in self.ecritures.items()
            if pid in self.paiements_touches and ecriture.statut == "BROUILLON"
        ]


def _designer_articles(
    articles: list[EncaissementArticle],
    article_ids: list[uuid.UUID] | None,
) -> list[EncaissementArticle]:
    """Les articles qui bougent. `None` les prend tous ; une liste vide n'a pas d'objet."""
    if article_ids is None:
        return list(articles)
    if not article_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Aucune ligne désignée : précisez les lignes à ré-imputer, ou aucune pour déplacer toute la note.",
        )
    connus = {article.id for article in articles}
    inconnus = [str(aid) for aid in article_ids if aid not in connus]
    if inconnus:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Ces lignes n'appartiennent pas à l'encaissement : {', '.join(inconnus)}",
        )
    demandes = set(article_ids)
    return [article for article in articles if article.id in demandes]


def _ratios(plan_articles: list[EncaissementArticle], deplaces: list[EncaissementArticle], poste_de) -> dict[int, Decimal]:
    """Pour chaque poste, la part de ses articles qui s'en va.

    À montants tous nuls, la proportion se prend sur le nombre d'articles : un
    rapport de montants n'a alors rien à dire, mais la part reste définie.
    """
    ids_deplaces = {article.id for article in deplaces}
    par_poste: dict[int, list[EncaissementArticle]] = {}
    for article in plan_articles:
        poste_id = poste_de(article)
        if poste_id is not None:
            par_poste.setdefault(poste_id, []).append(article)
    ratios: dict[int, Decimal] = {}
    for poste_id, du_poste in par_poste.items():
        partants = [a for a in du_poste if a.id in ids_deplaces]
        somme = sum((_montant(a.montant) for a in du_poste), ZERO)
        if somme <= 0:
            ratios[poste_id] = Decimal(len(partants)) / Decimal(len(du_poste))
        else:
            ratios[poste_id] = sum((_montant(a.montant) for a in partants), ZERO) / somme
    return ratios


def _controler_etat(encaissement: Encaissement) -> None:
    if encaissement.is_deleted or (encaissement.statut_operation or "ACTIVE").upper() != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cet encaissement est annulé ou supprimé : son imputation ne se corrige plus.",
        )
    nature = (encaissement.nature_mouvement or "BUDGETAIRE").upper()
    if nature == "HORS_BUDGET_A_REGULARISER":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Encaissement hors budget : passez par « Affecter au budget » pour lui donner un poste.",
        )
    if nature != "BUDGETAIRE" or encaissement.impact_budgetaire is False:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cet encaissement n'a pas d'impact budgétaire : il n'a pas de poste à corriger.",
        )


async def _nouveau_poste(
    db: AsyncSession, encaissement: Encaissement, poste_id: int, *, verrouiller: bool
) -> BudgetPoste:
    requete = select(BudgetPoste).where(
        BudgetPoste.id == poste_id,
        BudgetPoste.organisation_id == encaissement.organisation_id,
        BudgetPoste.is_deleted.is_(False),
    )
    if verrouiller:
        requete = requete.with_for_update()
    poste = (await db.execute(requete)).scalar_one_or_none()
    if poste is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Poste budgétaire introuvable")
    if (poste.type or "").upper() != "RECETTE":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Le poste {poste.code} n'est pas un poste de recette.",
        )
    if poste.active is False:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Ce poste budgétaire est désactivé.")
    if encaissement.service_id is not None:
        autorise = (
            await db.execute(
                select(ServiceRubrique.budget_poste_id).where(
                    ServiceRubrique.service_id == encaissement.service_id,
                    ServiceRubrique.budget_poste_id == poste.id,
                )
            )
        ).first()
        if autorise is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Rubrique non autorisée pour le service de cet encaissement : {poste.code}",
            )
    return poste


async def _etablir_plan(
    db: AsyncSession,
    *,
    encaissement: Encaissement,
    nouveau_poste_id: int,
    article_ids: list[uuid.UUID] | None,
    verrouiller: bool,
) -> _Plan:
    """Lit le circuit, et refuse tout ce qui ne se déplace pas proprement.

    L'aperçu passe par ici comme l'écriture : un refus se lit avant de décider,
    pas au moment de valider.
    """
    organisation_id = encaissement.organisation_id
    _controler_etat(encaissement)
    if await reports_actifs(db, organisation_id=organisation_id, encaissement_id=encaissement.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Cette note a été reportée en arriérés à la clôture : ses versements suivent les postes "
                "d'arriérés, son imputation ne se corrige plus ici."
            ),
        )

    nouveau_poste = await _nouveau_poste(db, encaissement, nouveau_poste_id, verrouiller=verrouiller)

    requete_articles = (
        select(EncaissementArticle)
        .where(
            EncaissementArticle.encaissement_id == encaissement.id,
            EncaissementArticle.organisation_id == organisation_id,
        )
        .order_by(EncaissementArticle.sort_order)
    )
    if verrouiller:
        requete_articles = requete_articles.with_for_update()
    articles = list((await db.execute(requete_articles)).scalars().all())
    if not articles and article_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cet encaissement n'a pas de lignes : seule la note entière peut changer de poste.",
        )
    deplaces = _designer_articles(articles, article_ids)
    complete = len(deplaces) == len(articles)

    def poste_de(article: EncaissementArticle) -> int | None:
        return article.budget_poste_id or encaissement.budget_poste_id

    postes_avant = sorted({pid for a in deplaces if (pid := poste_de(a)) is not None})
    if not articles and encaissement.budget_poste_id is not None:
        postes_avant = [encaissement.budget_poste_id]
    deja_arrives = (
        all(poste_de(a) == nouveau_poste.id for a in deplaces)
        if deplaces
        else encaissement.budget_poste_id == nouveau_poste.id
    )
    if deja_arrives:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Ces lignes sont déjà imputées sur ce poste.",
        )

    requete_paiements = select(PaymentHistory).where(
        PaymentHistory.organisation_id == organisation_id,
        PaymentHistory.encaissement_id == encaissement.id,
    )
    if verrouiller:
        requete_paiements = requete_paiements.with_for_update()
    tous_paiements = list((await db.execute(requete_paiements)).scalars().all())
    paiements = {p.id: p for p in tous_paiements if (p.statut or PAIEMENT_ACTIF).upper() == PAIEMENT_ACTIF}

    conditions = [MouvementBudgetImputation.encaissement_id == encaissement.id]
    if paiements:
        conditions.append(MouvementBudgetImputation.payment_history_id.in_(list(paiements)))
    requete_imputations = select(MouvementBudgetImputation).where(
        MouvementBudgetImputation.organisation_id == organisation_id,
        MouvementBudgetImputation.statut == "ACTIVE",
        MouvementBudgetImputation.sens == "RECETTE_REALISEE",
        or_(*conditions),
    )
    if verrouiller:
        requete_imputations = requete_imputations.with_for_update()
    imputations = list((await db.execute(requete_imputations)).scalars().all())

    imputes = {imp.payment_history_id for imp in imputations if imp.payment_history_id}
    plan = _Plan(
        encaissement=encaissement,
        nouveau_poste=nouveau_poste,
        articles=articles,
        deplaces=deplaces,
        complete=complete,
        postes_avant=postes_avant,
        ratio_par_poste=_ratios(articles, deplaces, poste_de),
        paiements=paiements,
        imputations=imputations,
        # Un versement sans imputation est antérieur au registre — sauf si la
        # note en porte ailleurs : la régularisation impute la note, pas le
        # versement, et c'est alors elle qui fait foi.
        versements_hors_registre=[
            p for pid, p in paiements.items()
            if pid not in imputes and not any(imp.encaissement_id for imp in imputations)
        ],
        note_hors_registre=(
            not tous_paiements and not imputations and _montant(encaissement.montant_paye) > 0
        ),
    )

    # Ce qui ne se partage pas. Une correction partielle ne vaut que si chaque
    # impact sait dire quelle part de lui s'en va.
    if not complete:
        for imp in imputations:
            if plan.ratio_pour(imp.budget_poste_id) is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        "Une imputation de cette note porte sur un poste qu'aucune de ses lignes n'occupe "
                        "(régularisation) : seule la note entière peut changer de poste."
                    ),
                )
        for paiement in plan.versements_hors_registre:
            if (plan.ratio_pour(plan.poste_versement(paiement)) or ZERO) not in (ZERO, UN):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        "Un versement de cette note est antérieur au registre des imputations : il ne se "
                        "partage pas entre deux postes. Déplacez toutes les lignes de ce poste, ou la note entière."
                    ),
                )
        if plan.note_hors_registre:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Cette note a été payée avant le registre des versements : elle ne change de poste "
                    "qu'en entier."
                ),
            )

    # Une recette appartient à son exercice : la déplacer sur un autre ferait
    # apparaître en 2027 de l'argent encaissé en 2026.
    cedants = plan.postes_cedants | set(postes_avant)
    if cedants:
        exercices = {
            row[0]
            for row in (
                await db.execute(select(BudgetPoste.exercice_id).where(BudgetPoste.id.in_(cedants)))
            ).all()
        }
        if exercices - {nouveau_poste.exercice_id}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Le nouveau poste appartient à un autre exercice : une recette reste sur l'exercice où elle a été encaissée.",
            )
    await verifier_postes_ouverts(
        db,
        organisation_id=organisation_id,
        poste_ids=cedants | {nouveau_poste.id},
        message="L'exercice {annee} est clôturé (poste {poste}) : l'imputation de cet encaissement ne se corrige plus.",
    )

    # La comptabilité : un brouillon se réécrit, une écriture validée non.
    if plan.montant_deplace > 0:
        origines = [str(pid) for pid in plan.paiements_touches]
        ecritures = (
            await db.execute(
                select(ComptaEcriture).where(
                    ComptaEcriture.organisation_id == organisation_id,
                    ComptaEcriture.module_origine == "encaissements",
                    ComptaEcriture.statut != "ANNULEE",
                    or_(
                        (ComptaEcriture.type_origine == "payment_history")
                        & ComptaEcriture.objet_origine_id.in_(origines or [""]),
                        (ComptaEcriture.type_origine == "encaissement")
                        & (ComptaEcriture.objet_origine_id == str(encaissement.id)),
                    ),
                )
            )
        ).scalars().all()
        for ecriture in ecritures:
            if ecriture.statut in ECRITURES_FIGEES:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Une écriture comptable de cet encaissement est déjà validée : le poste a servi à choisir "
                        "le compte de produit. Passez par une écriture de régularisation comptable, puis reprenez "
                        "la ré-imputation."
                    ),
                )
            if ecriture.type_origine == "encaissement":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Cet encaissement porte une écriture comptable globale, antérieure au suivi par versement : "
                        "le comptable doit l'annuler avant que le poste ne change."
                    ),
                )
            plan.ecritures[uuid.UUID(ecriture.objet_origine_id)] = ecriture

    return plan


async def apercu_reimputation_encaissement(
    db: AsyncSession,
    *,
    encaissement: Encaissement,
    nouveau_poste_id: int,
    article_ids: list[uuid.UUID] | None = None,
) -> dict[str, Any]:
    """Ce que la ré-imputation déplacerait, sans rien écrire."""
    plan = await _etablir_plan(
        db,
        encaissement=encaissement,
        nouveau_poste_id=nouveau_poste_id,
        article_ids=article_ids,
        verrouiller=False,
    )
    return {
        "postes_avant": plan.postes_avant,
        "nouveau_poste_id": plan.nouveau_poste.id,
        "lignes": len(plan.deplaces),
        "lignes_total": len(plan.articles),
        "versements": len(plan.paiements_touches),
        "imputations": len(plan.imputations_cedantes),
        "montant_paye_deplace": plan.montant_deplace,
        "ecritures_reecrites": len(plan.ecritures_a_reecrire),
    }


async def reimputer_encaissement(
    db: AsyncSession,
    *,
    encaissement: Encaissement,
    nouveau_poste_id: int,
    article_ids: list[uuid.UUID] | None = None,
    user_id: uuid.UUID | None,
    motif: str,
) -> dict[str, Any]:
    """Déplace des lignes d'encaissement, et leur réalisé, vers un autre poste de recette."""
    organisation_id = encaissement.organisation_id
    motif = (motif or "").strip()
    if len(motif) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Un motif d'au moins 3 caractères est exigé : la ré-imputation est une décision, elle se justifie.",
        )

    plan = await _etablir_plan(
        db,
        encaissement=encaissement,
        nouveau_poste_id=nouveau_poste_id,
        article_ids=article_ids,
        verrouiller=True,
    )
    nouveau_poste = plan.nouveau_poste
    entete_avant = encaissement.budget_poste_id

    # Les postes touchés, verrouillés par identifiant croissant pour ne pas
    # croiser un versement en cours sur les mêmes postes.
    postes: dict[int, BudgetPoste] = {nouveau_poste.id: nouveau_poste}
    for poste_id in sorted(plan.postes_cedants - {nouveau_poste.id}):
        poste = (
            await db.execute(
                select(BudgetPoste)
                .where(BudgetPoste.id == poste_id, BudgetPoste.organisation_id == organisation_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if poste is not None:
            postes[poste_id] = poste

    def _deplacer_compteur(depuis: int | None, montant: Decimal) -> None:
        ancien = postes.get(depuis) if depuis is not None else None
        if ancien is not None:
            ancien.montant_paye = _montant(ancien.montant_paye) - montant
        nouveau_poste.montant_paye = _montant(nouveau_poste.montant_paye) + montant

    maintenant = datetime.now(timezone.utc)
    montant_deplace = plan.montant_deplace

    # 1. Les imputations : l'originale est annulée, une remplaçante par poste.
    imputations_deplacees = 0
    for imp in plan.imputations:
        part = plan.part_imputation(imp)
        if part <= 0:
            continue
        montant = _montant(imp.montant_budget)
        mouvement = _montant(imp.montant_mouvement)
        part_mouvement = mouvement if part == montant else _au_centime(mouvement * (part / montant))

        def _remplacante(poste_id: int, montant_budget: Decimal, montant_mouvement: Decimal) -> MouvementBudgetImputation:
            return MouvementBudgetImputation(
                organisation_id=imp.organisation_id,
                encaissement_id=imp.encaissement_id,
                payment_history_id=imp.payment_history_id,
                regularisation_budgetaire_id=imp.regularisation_budgetaire_id,
                budget_poste_id=poste_id,
                sens=imp.sens,
                montant_mouvement=montant_mouvement,
                devise_mouvement=imp.devise_mouvement,
                montant_budget=montant_budget,
                exchange_rate_snapshot=imp.exchange_rate_snapshot,
                statut="ACTIVE",
                created_by=user_id,
            )

        remplacantes = [_remplacante(nouveau_poste.id, part, part_mouvement)]
        if montant - part > 0:
            remplacantes.append(_remplacante(imp.budget_poste_id, montant - part, mouvement - part_mouvement))
        imp.statut = "ANNULEE"
        imp.annulee_le = maintenant
        imp.annulee_par_id = user_id
        db.add_all(remplacantes)
        _deplacer_compteur(imp.budget_poste_id, part)
        imputations_deplacees += 1

    # 2. Les versements antérieurs au registre : leur poste est leur seule trace.
    for paiement in plan.versements_deplaces:
        _deplacer_compteur(plan.poste_versement(paiement), _montant(paiement.montant))
        paiement.budget_poste_id = nouveau_poste.id
    if plan.note_hors_registre and plan.complete:
        _deplacer_compteur(entete_avant, _montant(encaissement.montant_paye))

    # 3. Le poste retenu par chaque versement suit, quand tout son poste part.
    for paiement in plan.paiements.values():
        if paiement.budget_poste_id is not None and plan.ratio_pour(paiement.budget_poste_id) == UN:
            paiement.budget_poste_id = nouveau_poste.id

    # 4. Les lignes. Une ligne muette suivait l'en-tête : avant qu'il ne bouge,
    #    elle reçoit son poste en propre, sans quoi elle partirait avec lui.
    ids_deplaces = {article.id for article in plan.deplaces}
    for article in plan.articles:
        if article.id in ids_deplaces:
            article.budget_poste_id = nouveau_poste.id
        elif article.budget_poste_id is None:
            article.budget_poste_id = entete_avant

    # 5. L'en-tête, imprimé sur le reçu : le nouveau poste si toute la note y
    #    est ; sinon il ne change que s'il ne désigne plus aucune ligne — il
    #    prend alors le poste qui porte le plus.
    poids: dict[int, Decimal] = {}
    for article in plan.articles:
        if article.budget_poste_id is not None:
            poids[article.budget_poste_id] = poids.get(article.budget_poste_id, ZERO) + _montant(article.montant)
    if plan.complete or not poids:
        entete = nouveau_poste.id
    elif entete_avant in poids:
        entete = entete_avant
    else:
        entete = max(poids.items(), key=lambda item: item[1])[0]
    if entete != entete_avant:
        poste_entete = postes.get(entete) or (
            await db.execute(select(BudgetPoste).where(BudgetPoste.id == entete))
        ).scalar_one()
        encaissement.budget_poste_id = poste_entete.id
        encaissement.budget_poste_code = poste_entete.code
        encaissement.budget_poste_libelle = poste_entete.libelle

    # Le plancher, une fois que tous les mouvements ont parlé.
    for poste in postes.values():
        if _montant(poste.montant_paye) < 0:
            poste.montant_paye = ZERO

    await db.flush()

    # 6. Les brouillons comptables suivent le registre : un produit par poste,
    #    tel que les imputations désormais actives du versement le disent.
    ecritures_reecrites = 0
    for paiement_id in sorted(plan.paiements_touches, key=str):
        ecriture = plan.ecritures.get(paiement_id)
        if ecriture is None or ecriture.statut != "BROUILLON":
            continue
        produits: dict[int, Decimal] = {}
        for poste_id, montant_mouvement in (
            await db.execute(
                select(MouvementBudgetImputation.budget_poste_id, MouvementBudgetImputation.montant_mouvement).where(
                    MouvementBudgetImputation.payment_history_id == paiement_id,
                    MouvementBudgetImputation.statut == "ACTIVE",
                    MouvementBudgetImputation.sens == "RECETTE_REALISEE",
                )
            )
        ).all():
            produits[poste_id] = produits.get(poste_id, ZERO) + _montant(montant_mouvement)
        if not produits:
            # Versement antérieur au registre : son produit tient en un poste.
            produits = {nouveau_poste.id: _montant(plan.paiements[paiement_id].montant)}
        await reecrire_produits_ecriture_brouillon(
            db, ecriture=ecriture, produits=sorted(produits.items())
        )
        ecritures_reecrites += 1

    return {
        "postes_avant": plan.postes_avant,
        "nouveau_poste_id": nouveau_poste.id,
        "nouveau_poste_code": nouveau_poste.code,
        "lignes_deplacees": len(plan.deplaces),
        "lignes_total": len(plan.articles),
        "versements_deplaces": len(plan.paiements_touches),
        "imputations_deplacees": imputations_deplacees,
        "montant_paye_deplace": montant_deplace,
        "ecritures_reecrites": ecritures_reecrites,
        "entete_avant": entete_avant,
        "entete_apres": encaissement.budget_poste_id,
        "motif": motif,
    }
