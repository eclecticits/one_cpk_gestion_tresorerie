"""Ré-imputation d'une réquisition sur un autre poste budgétaire.

Corriger le poste d'une réquisition déjà validée et payée, ce n'est pas changer
une colonne : le poste vit à quatre endroits du circuit, et trois d'entre eux
portent de l'argent.

    ligne_requisition.budget_poste_id      -> source de `montant_engage` (dérivé)
    sortie_fonds.budget_poste_id           -> ce que la sortie dit avoir payé
    mouvement_budget_imputations           -> l'impact figé du paiement
    budget_postes.montant_paye             -> compteur alimenté par ces imputations

Déplacer les seules lignes laisserait l'engagement sur le nouveau poste et le
réalisé sur l'ancien : les deux postes mentiraient, chacun à sa manière. Cette
opération déplace donc la chaîne entière, sous une seule transaction, et refuse
quand elle ne peut pas le faire proprement.

Une réquisition n'a pas un poste, elle a autant de postes que de lignes.
`ligne_ids` désigne donc les lignes qui bougent ; omis, toute la réquisition
suit. Le paiement les accompagne selon ce qu'il dit avoir payé :

  - une imputation qui connaît sa ligne (`ligne_requisition_id`) tranche seule :
    elle part si sa ligne part, elle reste sinon. Aucun prorata n'intervient.
    C'est la forme que produit désormais le décaissement ;
  - à défaut, on se rabat sur le rattachement de la sortie ;
  - sans rien de tout cela — les imputations antérieures au lien —, l'impact est
    réparti au prorata : un acompte n'appartient à aucune ligne en particulier.
    Le rapport se prend poste par poste, car un paiement multi-postes porte une
    imputation par poste, et le poste que le déplacement ne concerne pas ne cède
    rien.

On ne scinde jamais la sortie de fonds elle-même : c'est une pièce de
décaissement, elle a été émise une fois pour un montant. On ne scinde que
l'impact budgétaire, qui est un enregistrement de budget : l'imputation d'origine
passe ANNULEE et deux ACTIVE la remplacent, une par poste. Le total du réalisé
est invariant — une ré-imputation ne crée ni ne détruit un centime.

Ce qu'elle ne fait jamais : réécrire une écriture comptable déjà passée. Quand
une sortie est comptabilisée, le poste a servi à choisir un compte ; changer le
poste dans son dos désaccorderait la comptabilité du budget sans laisser de
trace côté écritures. Le cas est refusé et renvoyé au comptable.
"""

from __future__ import annotations

import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetExercice, BudgetPoste
from app.models.ligne_requisition import LigneRequisition
from app.models.mouvement_budget_imputation import MouvementBudgetImputation
from app.models.requisition import Requisition
from app.models.retour_caisse import RetourCaisse
from app.models.sortie_fonds import SortieFonds
from app.services.budget_engagement import (
    postes_de_requisition,
    requisition_engage_le_budget,
    resynchroniser_engagements,
)

# Une sortie déjà passée en comptabilité fige le choix du compte : le poste ne
# peut plus bouger sans que le comptable ne repasse derrière.
STATUTS_COMPTABILISES = {"COMPTABILISEE", "COMPTABILISE"}

CENTIME = Decimal("0.01")

# Sens dont le montant alimente `montant_paye` ; `RETOUR_DEPENSE` le dégrève.
SENS_DEPENSE = {"RECETTE_REALISEE", "DEPENSE_PAYEE"}


def _montant(valeur: Any) -> Decimal:
    return Decimal(str(valeur or 0))


def _au_centime(valeur: Decimal) -> Decimal:
    return valeur.quantize(CENTIME, rounding=ROUND_HALF_UP)


async def _poste_verrouille(db: AsyncSession, organisation_id: int, poste_id: int) -> BudgetPoste | None:
    res = await db.execute(
        select(BudgetPoste)
        .where(
            BudgetPoste.id == poste_id,
            BudgetPoste.organisation_id == organisation_id,
            BudgetPoste.is_deleted.is_(False),
        )
        .with_for_update()
    )
    return res.scalar_one_or_none()


def _sans_accents(valeur: str) -> str:
    decompose = unicodedata.normalize("NFKD", valeur)
    return "".join(c for c in decompose if not unicodedata.combining(c)).upper()


async def _exercice_ouvert(db: AsyncSession, poste: BudgetPoste) -> bool:
    """Un exercice clôturé n'accepte plus de mouvement, fût-il correctif.

    Le statut est un enum dont la valeur est libellée — « Clôturé » — et non un
    code : on lit son nom, et on retombe sur la valeur désaccentuée si la
    colonne remonte une chaîne brute.
    """
    res = await db.execute(select(BudgetExercice.statut).where(BudgetExercice.id == poste.exercice_id))
    statut = res.scalar_one_or_none()
    if statut is None:
        return True
    nom = getattr(statut, "name", None) or _sans_accents(str(statut))
    return nom.upper() not in {"CLOTURE", "CLOTUREE", "FERME"}


@dataclass
class _Plan:
    """Ce qu'un déplacement toucherait, établi une fois pour l'aperçu et l'écriture."""

    lignes: list[LigneRequisition]
    deplacees: list[LigneRequisition]
    postes_avant: list[int]
    sorties: list[SortieFonds] = field(default_factory=list)
    # Sorties dont la pièce suit : tout leur impact s'en va, il n'y a plus rien
    # à laisser derrière.
    entieres: list[SortieFonds] = field(default_factory=list)
    # Imputations qui changent de poste en entier — leur ligne est connue et
    # elle part, ou la sortie tout entière s'en va.
    bougent: list[MouvementBudgetImputation] = field(default_factory=list)
    # Imputations dont la ligne est inconnue et dont une part seulement s'en
    # va : elles se répartissent au prorata du poste.
    a_repartir: list[MouvementBudgetImputation] = field(default_factory=list)
    imputations: dict[uuid.UUID, list[MouvementBudgetImputation]] = field(default_factory=dict)
    # Part des lignes qui partent, poste par poste. Un paiement crée une
    # imputation par poste (cf. `sorties_fonds`) : chacune ne doit céder que ce
    # que ses propres lignes emmènent, jamais la part d'un poste voisin.
    ratio_par_poste: dict[int, Decimal] = field(default_factory=dict)
    # Repli pour une imputation posée sur un poste qu'aucune ligne n'occupe.
    ratio_global: Decimal = Decimal("1")
    montant_engage_deplace: Decimal = Decimal("0")

    def ratio_pour(self, poste_id: int) -> Decimal:
        """Ce qu'une imputation de ce poste doit céder.

        Un poste qu'aucune ligne de la réquisition n'occupe n'a rien à voir avec
        le déplacement : il ne cède rien. Le repli global ne sert que si aucune
        ligne ne porte de poste — la réquisition n'a alors rien à opposer.
        """
        if poste_id in self.ratio_par_poste:
            return self.ratio_par_poste[poste_id]
        return self.ratio_global if not self.ratio_par_poste else Decimal("0")

    @property
    def fusionne_plusieurs_postes(self) -> bool:
        """Le déplacement rassemble-t-il sur un seul poste des lignes qui en occupaient plusieurs ?"""
        return len({ligne.budget_poste_id for ligne in self.deplacees if ligne.budget_poste_id}) > 1

    @property
    def a_repartir_effectives(self) -> list[MouvementBudgetImputation]:
        """Les imputations qui céderont vraiment quelque chose.

        Une imputation posée sur un poste que le déplacement ne touche pas reste
        entière : l'annoncer comme « répartie » ferait craindre un mouvement qui
        n'aura pas lieu.
        """
        return [imp for imp in self.a_repartir if self.ratio_pour(imp.budget_poste_id) > 0]

    @property
    def sorties_comptabilisees(self) -> list[SortieFonds]:
        return [s for s in self.sorties if (s.statut_comptabilisation or "").upper() in STATUTS_COMPTABILISES]


def _designer_lignes(
    lignes: list[LigneRequisition],
    ligne_ids: list[uuid.UUID] | None,
) -> list[LigneRequisition]:
    """Les lignes qui bougent. `None` les prend toutes ; une liste vide n'a pas d'objet."""
    if ligne_ids is None:
        return list(lignes)
    if not ligne_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Aucune ligne désignée : précisez les lignes à ré-imputer, ou aucune pour les déplacer toutes.",
        )
    connues = {ligne.id: ligne for ligne in lignes}
    inconnues = [str(lid) for lid in ligne_ids if lid not in connues]
    if inconnues:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Ces lignes n'appartiennent pas à la réquisition : {', '.join(inconnues)}",
        )
    # On suit l'ordre des lignes, pas celui de la demande : un identifiant
    # répété ne doit pas déplacer deux fois la même ligne.
    demandees = set(ligne_ids)
    return [ligne for ligne in lignes if ligne.id in demandees]


async def _imputations_par_sortie(
    db: AsyncSession,
    organisation_id: int,
    sorties: list[SortieFonds],
    *,
    verrouiller: bool,
) -> dict[uuid.UUID, list[MouvementBudgetImputation]]:
    if not sorties:
        return {}
    ids = [s.id for s in sorties]

    # Les retours rendus sur ces sorties comptent parmi leurs impacts : leur
    # mouvement ne porte pas `sortie_fonds_id` mais `retour_caisse_id`, et
    # l'ignorer laisserait le reliquat sur l'ancien poste pendant que la dépense
    # part sur le nouveau. Le poste d'arrivée compterait alors une dépense dont
    # une part est revenue, celui de départ une correction sans dépense derrière.
    sortie_par_retour = {
        rid: sid
        for rid, sid in (
            await db.execute(
                select(RetourCaisse.id, RetourCaisse.sortie_fonds_id).where(
                    RetourCaisse.organisation_id == organisation_id,
                    RetourCaisse.sortie_fonds_id.in_(ids),
                    RetourCaisse.statut == "VALIDE",
                )
            )
        ).all()
    }

    conditions = [MouvementBudgetImputation.sortie_fonds_id.in_(ids)]
    if sortie_par_retour:
        conditions.append(MouvementBudgetImputation.retour_caisse_id.in_(list(sortie_par_retour)))
    requete = select(MouvementBudgetImputation).where(
        MouvementBudgetImputation.organisation_id == organisation_id,
        or_(*conditions),
        MouvementBudgetImputation.statut == "ACTIVE",
    )
    if verrouiller:
        requete = requete.with_for_update()
    par_sortie: dict[uuid.UUID, list[MouvementBudgetImputation]] = {}
    for imp in (await db.execute(requete)).scalars().all():
        # Un mouvement de retour se range sous la sortie qu'il corrige : c'est
        # elle qui décide s'il part, et il ne doit pas la retenir seul.
        cle = imp.sortie_fonds_id or sortie_par_retour.get(imp.retour_caisse_id)
        if cle is None:
            continue
        par_sortie.setdefault(cle, []).append(imp)
    return par_sortie


async def _etablir_plan(
    db: AsyncSession,
    *,
    requisition: Requisition,
    ligne_ids: list[uuid.UUID] | None,
    verrouiller: bool,
) -> _Plan:
    organisation_id = requisition.organisation_id

    requete_lignes = select(LigneRequisition).where(LigneRequisition.requisition_id == requisition.id)
    if verrouiller:
        requete_lignes = requete_lignes.with_for_update()
    lignes = list((await db.execute(requete_lignes)).scalars().all())
    if not lignes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cette réquisition n'a aucune ligne à ré-imputer.",
        )
    deplacees = _designer_lignes(lignes, ligne_ids)

    requete_sorties = select(SortieFonds).where(
        SortieFonds.requisition_id == requisition.id,
        SortieFonds.organisation_id == organisation_id,
    )
    if verrouiller:
        requete_sorties = requete_sorties.with_for_update()
    sorties = list((await db.execute(requete_sorties)).scalars().all())

    # Le prorata d'une sortie qui couvre la réquisition entière. À montants tous
    # nuls, la proportion se prend sur le nombre de lignes : un rapport de
    # montants n'a alors rien à dire, mais la part reste définie.
    total = sum((_montant(ligne.montant_total) for ligne in lignes), Decimal("0"))
    part = sum((_montant(ligne.montant_total) for ligne in deplacees), Decimal("0"))
    ratio_global = (part / total) if total > 0 else (Decimal(len(deplacees)) / Decimal(len(lignes)))

    # Et le même rapport, poste par poste : l'imputation d'un poste ne cède que
    # ce que les lignes de ce poste emmènent.
    ids_deplacees = {ligne.id for ligne in deplacees}
    lignes_par_poste: dict[int, list[LigneRequisition]] = {}
    for ligne in lignes:
        if ligne.budget_poste_id is not None:
            lignes_par_poste.setdefault(ligne.budget_poste_id, []).append(ligne)

    def _proportion(du_poste: list[LigneRequisition]) -> Decimal:
        qui_partent = [ligne for ligne in du_poste if ligne.id in ids_deplacees]
        somme = sum((_montant(ligne.montant_total) for ligne in du_poste), Decimal("0"))
        if somme <= 0:
            return Decimal(len(qui_partent)) / Decimal(len(du_poste))
        return sum((_montant(ligne.montant_total) for ligne in qui_partent), Decimal("0")) / somme

    ratio_par_poste = {
        poste_id: _proportion(du_poste) for poste_id, du_poste in lignes_par_poste.items()
    }

    toutes_partent = len(deplacees) == len(lignes)
    imputations = await _imputations_par_sortie(db, organisation_id, sorties, verrouiller=verrouiller)
    rattachement_sortie = {s.id: s.ligne_requisition_id for s in sorties}

    # Chaque impact est jugé sur ce qu'il sait de lui-même. L'imputation qui
    # connaît sa ligne tranche seule ; celle qui l'ignore se rabat sur ce que
    # dit sa sortie ; sans rien de tout cela, elle se répartira au prorata.
    bougent: list[MouvementBudgetImputation] = []
    a_repartir: list[MouvementBudgetImputation] = []
    for liste in imputations.values():
        for imp in liste:
            ligne_connue = imp.ligne_requisition_id or rattachement_sortie.get(imp.sortie_fonds_id)
            if ligne_connue is not None:
                if ligne_connue in ids_deplacees:
                    bougent.append(imp)
            elif toutes_partent:
                bougent.append(imp)
            else:
                a_repartir.append(imp)

    # La pièce de décaissement ne suit que si plus rien ne la retient : tout son
    # impact s'en va. Une sortie sans imputation — hors budget, fonds de tiers —
    # se juge sur son propre rattachement.
    partants = {id(imp) for imp in bougent}

    def _suit(sortie: SortieFonds) -> bool:
        siennes = imputations.get(sortie.id, [])
        if siennes:
            return all(id(imp) in partants for imp in siennes)
        if sortie.ligne_requisition_id is not None:
            return sortie.ligne_requisition_id in ids_deplacees
        return toutes_partent

    return _Plan(
        lignes=lignes,
        deplacees=deplacees,
        postes_avant=await postes_de_requisition(db, requisition.id),
        sorties=sorties,
        entieres=[s for s in sorties if _suit(s)],
        bougent=bougent,
        a_repartir=a_repartir,
        imputations=imputations,
        ratio_par_poste=ratio_par_poste,
        ratio_global=ratio_global,
        montant_engage_deplace=part if requisition_engage_le_budget(requisition) else Decimal("0"),
    )


def _part_deplacee(plan: _Plan) -> Decimal:
    """Le réalisé qui changerait de poste : les impacts entiers et les parts réparties."""
    total = Decimal("0")
    for imp in plan.bougent:
        montant = _montant(imp.montant_budget)
        total += montant if imp.sens in SENS_DEPENSE else -montant
    for imp in plan.a_repartir:
        montant = _au_centime(_montant(imp.montant_budget) * plan.ratio_pour(imp.budget_poste_id))
        total += montant if imp.sens in SENS_DEPENSE else -montant
    return total


async def apercu_reimputation(
    db: AsyncSession,
    *,
    requisition: Requisition,
    nouveau_poste_id: int,
    ligne_ids: list[uuid.UUID] | None = None,
) -> dict[str, Any]:
    """Ce que la ré-imputation déplacerait, sans rien écrire.

    Sert à montrer l'effet avant de le décider : un super-admin qui corrige une
    imputation payée doit voir le montant qui change de poste, pas le découvrir
    dans un rapport le mois suivant.
    """
    plan = await _etablir_plan(db, requisition=requisition, ligne_ids=ligne_ids, verrouiller=False)

    return {
        "postes_avant": plan.postes_avant,
        "nouveau_poste_id": nouveau_poste_id,
        "lignes": len(plan.deplacees),
        "lignes_total": len(plan.lignes),
        "sorties": len(plan.entieres),
        "sorties_reparties": len(plan.a_repartir_effectives),
        "imputations": len(plan.bougent) + len(plan.a_repartir_effectives),
        "montant_engage_deplace": plan.montant_engage_deplace,
        "montant_paye_deplace": _part_deplacee(plan),
        "fusionne_plusieurs_postes": plan.fusionne_plusieurs_postes,
        "sorties_comptabilisees": [str(s.id) for s in plan.sorties_comptabilisees],
    }


def _scinder(
    imp: MouvementBudgetImputation,
    plan: _Plan,
    *,
    nouveau_poste_id: int,
    user_id: uuid.UUID | None,
    maintenant: datetime,
) -> tuple[Decimal, list[MouvementBudgetImputation]]:
    """Répartit une imputation entre son poste et le nouveau, au prorata.

    Le rapport est celui des lignes du poste où l'imputation se trouve, pas
    celui de la réquisition : un paiement multi-postes porte une imputation par
    poste, et le poste que le déplacement ne concerne pas ne cède rien.

    L'originale est annulée plutôt que corrigée : un impact figé ne se réécrit
    pas, il se remplace, et le journal garde la trace des deux états. Le centime
    d'arrondi reste sur le poste d'origine, qui conserve le reliquat.
    """
    ratio = plan.ratio_pour(imp.budget_poste_id)
    montant = _montant(imp.montant_budget)
    part = _au_centime(montant * ratio)
    reste = montant - part
    if part <= 0:
        return Decimal("0"), []

    mouvement = _montant(imp.montant_mouvement)
    part_mouvement = _au_centime(mouvement * ratio)

    def _nouvelle(poste_id: int, montant_budget: Decimal, montant_mouvement: Decimal) -> MouvementBudgetImputation:
        return MouvementBudgetImputation(
            organisation_id=imp.organisation_id,
            encaissement_id=imp.encaissement_id,
            payment_history_id=imp.payment_history_id,
            sortie_fonds_id=imp.sortie_fonds_id,
            retour_caisse_id=imp.retour_caisse_id,
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

    remplacantes = [_nouvelle(nouveau_poste_id, part, part_mouvement)]
    if reste > 0:
        remplacantes.append(_nouvelle(imp.budget_poste_id, reste, mouvement - part_mouvement))

    imp.statut = "ANNULEE"
    imp.annulee_le = maintenant
    imp.annulee_par_id = user_id
    return part, remplacantes


async def reimputer_requisition(
    db: AsyncSession,
    *,
    requisition: Requisition,
    nouveau_poste_id: int,
    ligne_ids: list[uuid.UUID] | None = None,
    user_id: uuid.UUID | None,
    motif: str,
    forcer: bool = False,
) -> dict[str, Any]:
    """Déplace des lignes de réquisition, et leur impact budgétaire, vers un autre poste.

    `ligne_ids` désigne les lignes concernées ; omis, toute la réquisition suit.
    `forcer` ne lève qu'un garde-fou : celui du dépassement du disponible sur le
    poste d'arrivée. Il ne permet ni de toucher un exercice clôturé, ni de
    passer outre une sortie déjà comptabilisée.
    """
    organisation_id = requisition.organisation_id
    motif = (motif or "").strip()
    if len(motif) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Un motif d'au moins 3 caractères est exigé : la ré-imputation est une décision, elle se justifie.",
        )

    nouveau_poste = await _poste_verrouille(db, organisation_id, nouveau_poste_id)
    if nouveau_poste is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Poste budgétaire introuvable")
    if not nouveau_poste.active:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Ce poste budgétaire est désactivé.")
    if not await _exercice_ouvert(db, nouveau_poste):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="L'exercice du poste d'arrivée est clôturé : la ré-imputation y est impossible.",
        )

    plan = await _etablir_plan(db, requisition=requisition, ligne_ids=ligne_ids, verrouiller=True)

    # Le refus porte sur les lignes désignées, pas sur la réquisition : une ligne
    # restée sans poste a toujours quelque chose à recevoir, même si ses voisines
    # sont déjà sur le poste d'arrivée.
    if all(ligne.budget_poste_id == nouveau_poste_id for ligne in plan.deplacees):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Ces lignes sont déjà imputées sur ce poste.",
        )

    if plan.sorties_comptabilisees:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Une sortie de fonds de cette réquisition est déjà comptabilisée : le poste a servi à choisir "
                "le compte. Passez par une écriture de régularisation comptable, puis reprenez la ré-imputation."
            ),
        )

    # Contrôle de disponibilité : l'engagement qui arrive s'ajoute à ce que le
    # poste porte déjà. `disponible = prévu − engagé`, ici comme partout.
    montant_engage_deplace = plan.montant_engage_deplace
    disponible = _montant(nouveau_poste.montant_prevu) - _montant(nouveau_poste.montant_engage)
    depassement = montant_engage_deplace - disponible
    if montant_engage_deplace > disponible and not forcer:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Le poste {nouveau_poste.code} n'a que {disponible} de disponible pour {montant_engage_deplace} "
                f"à imputer ({depassement} de dépassement). Reprenez avec « forcer » pour l'assumer."
            ),
        )

    # Les postes de départ sont verrouillés dans le même ordre que celui
    # d'arrivée, par identifiant croissant, pour ne pas croiser un autre
    # paiement en cours sur les mêmes lignes.
    concernes = {*plan.postes_avant, nouveau_poste_id}
    for imputations in plan.imputations.values():
        concernes.update(imp.budget_poste_id for imp in imputations)
    postes_touches = sorted(concernes)
    postes = {nouveau_poste_id: nouveau_poste}
    for poste_id in postes_touches:
        if poste_id not in postes:
            poste = await _poste_verrouille(db, organisation_id, poste_id)
            if poste is not None:
                postes[poste_id] = poste

    maintenant = datetime.now(timezone.utc)
    montant_paye_deplace = Decimal("0")
    # Lu avant que les lignes ne changent de poste : après, elles sont toutes
    # sur le poste d'arrivée et la fusion ne se voit plus.
    fusionne = plan.fusionne_plusieurs_postes

    def _deplacer_realise(depuis: int, montant: Decimal, sens: str) -> None:
        """Le compteur des deux postes suit le sens de l'imputation.

        Aucun plancher ici : un déplacement se fait mouvement par mouvement, et
        l'ordre dans lequel ils se présentent est arbitraire. Écrêter en chemin
        ferait disparaître l'écart d'un passage négatif transitoire — une
        dépense retirée avant le retour qui la corrige laisse le poste sous zéro
        le temps d'une ligne, et les dix dollars ainsi rabotés ne revenaient
        jamais. Le plancher s'applique une fois, à la fin, quand tous les
        mouvements ont parlé.
        """
        nonlocal montant_paye_deplace
        ancien = postes.get(depuis)
        if sens in SENS_DEPENSE:
            if ancien is not None:
                ancien.montant_paye = _montant(ancien.montant_paye) - montant
            nouveau_poste.montant_paye = _montant(nouveau_poste.montant_paye) + montant
            montant_paye_deplace += montant
        elif sens == "RETOUR_DEPENSE":
            if ancien is not None:
                ancien.montant_paye = _montant(ancien.montant_paye) + montant
            nouveau_poste.montant_paye = _montant(nouveau_poste.montant_paye) - montant
            montant_paye_deplace -= montant

    # Les lignes d'une réquisition validée sont gelées par un déclencheur — le
    # texte que le validateur a signé ne bouge plus. La ré-imputation est la
    # seule exception, et elle s'annonce : `SET LOCAL` ne vaut que pour cette
    # transaction, et le déclencheur ne l'honore que si rien d'autre que le
    # poste ne change (cf. migration 20260916_verrou_reimput).
    await db.execute(text("SET LOCAL onec.reimputation = 'on'"))

    # 1. Les lignes désignées : source de l'engagement, avec leurs empreintes de poste.
    for ligne in plan.deplacees:
        ligne.budget_poste_id = nouveau_poste_id
        ligne.budget_poste_code_snapshot = nouveau_poste.code
        ligne.budget_poste_libelle_snapshot = nouveau_poste.libelle

    # 2. Les pièces de décaissement que plus rien ne retient sur leur poste.
    for sortie in plan.entieres:
        sortie.budget_poste_id = nouveau_poste_id
        if hasattr(sortie, "budget_poste_code"):
            sortie.budget_poste_code = nouveau_poste.code
        if hasattr(sortie, "budget_poste_libelle"):
            sortie.budget_poste_libelle = nouveau_poste.libelle

    # 3. Les impacts dont la ligne est connue et part : ils changent de poste en
    #    entier, sans qu'aucun prorata n'ait à trancher.
    for imp in plan.bougent:
        _deplacer_realise(imp.budget_poste_id, _montant(imp.montant_budget), imp.sens)
        imp.budget_poste_id = nouveau_poste_id

    # 4. Ceux dont la ligne est inconnue et dont une part seulement s'en va. La
    #    pièce de décaissement ne bouge pas — elle couvre encore des lignes
    #    restées sur leur poste ; seul l'impact budgétaire se répartit.
    imputations_reparties = 0
    for imp in plan.a_repartir:
        part, remplacantes = _scinder(
            imp, plan, nouveau_poste_id=nouveau_poste_id, user_id=user_id, maintenant=maintenant
        )
        if not remplacantes:
            continue
        db.add_all(remplacantes)
        _deplacer_realise(imp.budget_poste_id, part, imp.sens)
        imputations_reparties += 1

    # Le plancher, maintenant que tous les mouvements ont parlé : un compteur ne
    # se lit jamais négatif, mais il a pu l'être en chemin.
    for poste in (*postes.values(), nouveau_poste):
        if _montant(poste.montant_paye) < 0:
            poste.montant_paye = Decimal("0")

    await db.flush()

    # 4. L'engagement est dérivé : on le recalcule des deux côtés, jamais on ne
    #    le décrémente à la main.
    ajustes = await resynchroniser_engagements(db, tenant_id=organisation_id, poste_ids=postes_touches)

    return {
        "postes_avant": plan.postes_avant,
        "nouveau_poste_id": nouveau_poste_id,
        "nouveau_poste_code": nouveau_poste.code,
        "lignes_deplacees": len(plan.deplacees),
        "lignes_total": len(plan.lignes),
        "sorties_deplacees": len(plan.entieres),
        "sorties_reparties": imputations_reparties,
        "imputations_deplacees": len(plan.bougent) + imputations_reparties,
        "montant_engage_deplace": montant_engage_deplace,
        "montant_paye_deplace": montant_paye_deplace,
        "postes_resynchronises": ajustes,
        "fusionne_plusieurs_postes": fusionne,
        "depassement_assume": bool(forcer and montant_engage_deplace > disponible),
        "motif": motif,
        "par": str(user_id) if user_id else None,
    }
