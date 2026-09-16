"""Ré-imputation d'une réquisition sur un autre poste budgétaire.

Le poste vit à quatre endroits du circuit, et trois portent de l'argent :
les lignes (source de l'engagement), la sortie de fonds, les imputations figées
du paiement et les compteurs des postes. Déplacer les seules lignes laisserait
l'engagement d'un côté et le réalisé de l'autre. Ces tests verrouillent le fait
que la chaîne entière suit, ou que rien ne bouge.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.ligne_requisition import LigneRequisition
from app.models.mouvement_budget_imputation import MouvementBudgetImputation
from app.models.sortie_fonds import SortieFonds
from app.services.budget_engagement import resynchroniser_engagement_requisition
from app.services.reimputation_budgetaire import apercu_reimputation, reimputer_requisition

from test_budget_engagements import (
    MONTANT,
    PREVU,
    _engage,
    _org,
    _poste,
    _requisition,
    _user,
)


async def _payer(db, org, req, poste, *, montant=MONTANT, comptabilisee=False):
    """Simule le décaissement : une sortie, son imputation figée, le compteur du poste."""
    sortie = SortieFonds(
        organisation_id=org.id,
        requisition_id=req.id,
        type_sortie="REQUISITION",
        budget_poste_id=poste.id,
        montant_paye=montant,
        mode_paiement="cash",
        devise="USD",
        canal="CAISSE",
        statut="VALIDE",
        statut_comptabilisation="COMPTABILISEE" if comptabilisee else "NON_COMPTABILISEE",
        motif="Paiement fournitures",
        beneficiaire="Fournisseur",
    )
    db.add(sortie)
    await db.flush()
    db.add(
        MouvementBudgetImputation(
            organisation_id=org.id,
            sortie_fonds_id=sortie.id,
            budget_poste_id=poste.id,
            sens="DEPENSE_PAYEE",
            montant_mouvement=montant,
            devise_mouvement="USD",
            montant_budget=montant,
            statut="ACTIVE",
        )
    )
    poste.montant_paye = Decimal(str(poste.montant_paye or 0)) + montant
    await db.flush()
    return sortie


async def _poste_voisin(db, org, modele, *, prevu=PREVU):
    """Second poste du même exercice — un exercice est unique par organisation et année."""
    poste = BudgetPoste(
        organisation_id=org.id,
        exercice_id=modele.exercice_id,
        code=f"DEP-{uuid.uuid4().hex[:6]}",
        libelle="Mission",
        type="DEPENSE",
        active=True,
        montant_prevu=prevu,
        montant_engage=Decimal("0"),
        is_deleted=False,
    )
    db.add(poste)
    await db.flush()
    return poste


async def _paye(db, poste) -> Decimal:
    res = await db.execute(select(BudgetPoste.montant_paye).where(BudgetPoste.id == poste.id))
    return Decimal(res.scalar_one() or 0)


async def _contexte_engage(db):
    """Réquisition partie à l'examen : son montant est gelé sur le poste d'origine."""
    org = await _org(db)
    user = await _user(db, org)
    ancien = await _poste(db, org)
    nouveau = await _poste_voisin(db, org, ancien)
    req = await _requisition(db, org, user, ancien, examen_status="EN_EXAMEN")
    await resynchroniser_engagement_requisition(db, req)
    return org, user, ancien, nouveau, req


@pytest.mark.asyncio
async def test_l_engagement_quitte_l_ancien_poste_et_gele_le_nouveau(db_session):
    org, user, ancien, nouveau, req = await _contexte_engage(db_session)
    assert await _engage(db_session, ancien) == MONTANT

    await reimputer_requisition(
        db_session,
        requisition=req,
        nouveau_poste_id=nouveau.id,
        user_id=user.id,
        motif="Imputation initiale erronée",
    )

    assert await _engage(db_session, ancien) == Decimal("0.00")
    assert await _engage(db_session, nouveau) == MONTANT


@pytest.mark.asyncio
async def test_une_requisition_payee_emmene_son_realise(db_session):
    """Le cœur du sujet : l'engagement et le payé ne doivent pas se séparer."""
    org, user, ancien, nouveau, req = await _contexte_engage(db_session)
    sortie = await _payer(db_session, org, req, ancien)
    assert await _paye(db_session, ancien) == MONTANT

    resultat = await reimputer_requisition(
        db_session,
        requisition=req,
        nouveau_poste_id=nouveau.id,
        user_id=user.id,
        motif="Correction après paiement",
    )

    assert await _paye(db_session, ancien) == Decimal("0.00")
    assert await _paye(db_session, nouveau) == MONTANT
    assert await _engage(db_session, ancien) == Decimal("0.00")
    assert await _engage(db_session, nouveau) == MONTANT
    assert resultat["montant_paye_deplace"] == MONTANT

    # La sortie et l'imputation figée pointent le nouveau poste.
    await db_session.refresh(sortie)
    assert sortie.budget_poste_id == nouveau.id
    imputation = (await db_session.execute(
        select(MouvementBudgetImputation).where(MouvementBudgetImputation.sortie_fonds_id == sortie.id)
    )).scalar_one()
    assert imputation.budget_poste_id == nouveau.id
    assert imputation.statut == "ACTIVE", "l'imputation est déplacée, jamais annulée"


@pytest.mark.asyncio
async def test_une_sortie_comptabilisee_bloque_la_reimputation(db_session):
    org, user, ancien, nouveau, req = await _contexte_engage(db_session)
    await _payer(db_session, org, req, ancien, comptabilisee=True)

    with pytest.raises(HTTPException) as erreur:
        await reimputer_requisition(
            db_session,
            requisition=req,
            nouveau_poste_id=nouveau.id,
            user_id=user.id,
            motif="Correction après comptabilisation",
        )

    assert erreur.value.status_code == 409
    assert "comptabilis" in str(erreur.value.detail).lower()
    # Rien n'a bougé.
    assert await _engage(db_session, ancien) == MONTANT
    assert await _engage(db_session, nouveau) == Decimal("0.00")


@pytest.mark.asyncio
async def test_le_depassement_est_refuse_puis_assumable(db_session):
    org = await _org(db_session)
    user = await _user(db_session, org)
    ancien = await _poste(db_session, org)
    etroit = await _poste_voisin(db_session, org, ancien, prevu=Decimal("100.00"))
    req = await _requisition(db_session, org, user, ancien, examen_status="EN_EXAMEN")
    await resynchroniser_engagement_requisition(db_session, req)

    with pytest.raises(HTTPException) as erreur:
        await reimputer_requisition(
            db_session,
            requisition=req,
            nouveau_poste_id=etroit.id,
            user_id=user.id,
            motif="Poste trop étroit",
        )
    assert erreur.value.status_code == 409
    assert await _engage(db_session, ancien) == MONTANT

    resultat = await reimputer_requisition(
        db_session,
        requisition=req,
        nouveau_poste_id=etroit.id,
        user_id=user.id,
        motif="Dépassement assumé par le Conseil",
        forcer=True,
    )
    assert resultat["depassement_assume"] is True
    assert await _engage(db_session, etroit) == MONTANT


@pytest.mark.asyncio
async def test_un_exercice_cloture_reste_intouchable(db_session):
    org, user, ancien, nouveau, req = await _contexte_engage(db_session)
    exercice = (await db_session.execute(
        select(BudgetExercice).where(BudgetExercice.id == nouveau.exercice_id)
    )).scalar_one()
    exercice.statut = StatutBudget.CLOTURE
    await db_session.flush()

    with pytest.raises(HTTPException) as erreur:
        await reimputer_requisition(
            db_session,
            requisition=req,
            nouveau_poste_id=nouveau.id,
            user_id=user.id,
            motif="Exercice fermé",
        )

    assert erreur.value.status_code == 409
    assert await _engage(db_session, ancien) == MONTANT


@pytest.mark.asyncio
async def test_le_motif_est_exige(db_session):
    org, user, ancien, nouveau, req = await _contexte_engage(db_session)

    with pytest.raises(HTTPException) as erreur:
        await reimputer_requisition(
            db_session,
            requisition=req,
            nouveau_poste_id=nouveau.id,
            user_id=user.id,
            motif="  ",
        )

    assert erreur.value.status_code == 422


@pytest.mark.asyncio
async def test_l_apercu_annonce_ce_qui_bougerait_sans_rien_ecrire(db_session):
    org, user, ancien, nouveau, req = await _contexte_engage(db_session)
    await _payer(db_session, org, req, ancien)

    apercu = await apercu_reimputation(db_session, requisition=req, nouveau_poste_id=nouveau.id)

    assert apercu["postes_avant"] == [ancien.id]
    assert apercu["montant_engage_deplace"] == MONTANT
    assert apercu["montant_paye_deplace"] == MONTANT
    assert apercu["sorties_comptabilisees"] == []
    # Rien n'a été écrit.
    assert await _engage(db_session, nouveau) == Decimal("0.00")
    assert await _paye(db_session, nouveau) == Decimal("0.00")



# ── Tous les statuts, pas seulement les réquisitions payées ─────────────────


@pytest.mark.asyncio
async def test_un_brouillon_change_de_poste_sans_rien_engager(db_session):
    """Un brouillon n'engage rien : le changer de poste ne doit rien geler."""
    org = await _org(db_session)
    user = await _user(db_session, org)
    ancien = await _poste(db_session, org)
    nouveau = await _poste_voisin(db_session, org, ancien)
    req = await _requisition(db_session, org, user, ancien)  # NON_EXAMINE
    await resynchroniser_engagement_requisition(db_session, req)
    assert await _engage(db_session, ancien) == Decimal("0.00")

    resultat = await reimputer_requisition(
        db_session,
        requisition=req,
        nouveau_poste_id=nouveau.id,
        user_id=user.id,
        motif="Poste choisi par erreur à la saisie",
    )

    assert resultat["montant_engage_deplace"] == Decimal("0")
    assert await _engage(db_session, ancien) == Decimal("0.00")
    assert await _engage(db_session, nouveau) == Decimal("0.00")
    ligne = (await db_session.execute(
        select(LigneRequisition).where(LigneRequisition.requisition_id == req.id)
    )).scalars().first()
    assert ligne.budget_poste_id == nouveau.id
    assert ligne.budget_poste_code_snapshot == nouveau.code


@pytest.mark.asyncio
async def test_un_poste_etroit_n_arrete_pas_un_brouillon(db_session):
    """Le contrôle de disponibilité ne mord que sur ce qui gèle du crédit."""
    org = await _org(db_session)
    user = await _user(db_session, org)
    ancien = await _poste(db_session, org)
    etroit = await _poste_voisin(db_session, org, ancien, prevu=Decimal("1.00"))
    req = await _requisition(db_session, org, user, ancien)  # brouillon

    resultat = await reimputer_requisition(
        db_session,
        requisition=req,
        nouveau_poste_id=etroit.id,
        user_id=user.id,
        motif="Réaffectation avant soumission",
    )

    assert resultat["depassement_assume"] is False
    assert await _engage(db_session, etroit) == Decimal("0.00")


@pytest.mark.asyncio
async def test_une_ligne_sans_poste_en_recoit_un(db_session):
    """Cas courant d'une saisie incomplète : la correction impute enfin la ligne."""
    org = await _org(db_session)
    user = await _user(db_session, org)
    ancien = await _poste(db_session, org)
    nouveau = await _poste_voisin(db_session, org, ancien)
    req = await _requisition(db_session, org, user, ancien)
    ligne = (await db_session.execute(
        select(LigneRequisition).where(LigneRequisition.requisition_id == req.id)
    )).scalars().first()
    ligne.budget_poste_id = None
    await db_session.flush()

    resultat = await reimputer_requisition(
        db_session,
        requisition=req,
        nouveau_poste_id=nouveau.id,
        user_id=user.id,
        motif="Ligne restée sans imputation",
    )

    assert resultat["postes_avant"] == []
    await db_session.refresh(ligne)
    assert ligne.budget_poste_id == nouveau.id


@pytest.mark.asyncio
async def test_une_requisition_examinee_mais_non_payee_suit_aussi(db_session):
    """En attente de paiement : l'engagement bouge, le réalisé n'existe pas encore."""
    org = await _org(db_session)
    user = await _user(db_session, org)
    ancien = await _poste(db_session, org)
    nouveau = await _poste_voisin(db_session, org, ancien)
    req = await _requisition(db_session, org, user, ancien, examen_status="EXAMINE")
    req.status = "AUTORISEE"
    await resynchroniser_engagement_requisition(db_session, req)
    assert await _engage(db_session, ancien) == MONTANT

    resultat = await reimputer_requisition(
        db_session,
        requisition=req,
        nouveau_poste_id=nouveau.id,
        user_id=user.id,
        motif="Correction avant décaissement",
    )

    assert resultat["montant_engage_deplace"] == MONTANT
    assert resultat["montant_paye_deplace"] == Decimal("0")
    assert await _engage(db_session, ancien) == Decimal("0.00")
    assert await _engage(db_session, nouveau) == MONTANT
