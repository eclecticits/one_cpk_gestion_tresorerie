"""Ré-imputation d'une réquisition qui porte plusieurs lignes budgétaires.

Une réquisition n'a pas un poste, elle a autant de postes que de lignes. Corriger
l'imputation d'une ligne ne doit pas emporter ses voisines : aujourd'hui le
service écrase toutes les lignes sur le poste d'arrivée, sans le dire, et fusionne
deux postes distincts en un seul.

Ces tests tiennent le contrat en quatre points :

1. La désignation. `ligne_ids` choisit les lignes qui bougent ; omis, toute la
   réquisition suit, comme avant.
2. Le rattachement du paiement. `sorties_fonds.ligne_requisition_id` dit quelle
   ligne une sortie a payée. Rattachée, elle suit sa ligne ; non rattachée — le
   cas de toutes les sorties antérieures au lien — elle couvre la réquisition
   entière.
3. La répartition. Quand une sortie non rattachée ne voit partir qu'une partie
   des lignes, son imputation est scindée au prorata : l'ancienne passe ANNULEE,
   deux ACTIVE la remplacent, une par poste. Le rapport se prend poste par
   poste, car un paiement multi-postes porte une imputation par poste et le
   poste étranger au déplacement ne cède rien. On ne scinde jamais la sortie de
   fonds elle-même — c'est une pièce de décaissement ; on ne scinde que l'impact
   budgétaire, qui est un enregistrement de budget.
4. Ce que le décaissement inscrit. La pièce de sortie ne nomme une ligne que
   lorsque la réquisition n'en a qu'une — au-delà, elle en couvre plusieurs et le
   lien serait faux. L'imputation, elle, est ventilée ligne par ligne : c'est
   par elle que la ré-imputation devient exacte, sans prorata.

La somme des imputations actives est invariante : un déplacement ne crée ni ne
détruit un centime de réalisé.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.ligne_requisition import LigneRequisition
from app.models.mouvement_budget_imputation import MouvementBudgetImputation
from app.models.requisition import Requisition
from app.models.sortie_fonds import SortieFonds
from app.api.v1.endpoints.sorties_fonds import _ligne_unique_de_requisition
from app.services.budget_engagement import resynchroniser_engagement_requisition
from app.services.reimputation_budgetaire import apercu_reimputation, reimputer_requisition

from test_budget_engagements import PREVU, _engage, _org, _poste, _requisition, _user
from test_reimputation_budgetaire import _paye, _poste_voisin


# Trois montants distincts et non proportionnels : une assertion qui passerait
# par hasard sur des montants égaux échoue ici.
L1 = Decimal("1000.00")
L2 = Decimal("2000.00")
L3 = Decimal("4000.00")


async def _ligne(db, org, req, poste, montant, *, rubrique="Ligne"):
    """Ajoute une ligne à une réquisition et tient `montant_total` à jour."""
    ligne = LigneRequisition(
        organisation_id=org.id,
        requisition_id=req.id,
        budget_poste_id=poste.id if poste is not None else None,
        rubrique=rubrique,
        description=rubrique,
        quantite=1,
        montant_unitaire=montant,
        montant_total=montant,
        devise="USD",
    )
    db.add(ligne)
    req.montant_total = Decimal(str(req.montant_total or 0)) + montant
    await db.flush()
    return ligne


async def _requisition_voisine(db, org, user, modele, poste, montant):
    """Seconde réquisition du même service — `_requisition` ne sait pas en créer deux.

    Son service porte un libellé fixe, et une contrainte d'unicité interdit le
    doublon dans une organisation : on réutilise donc celui du modèle.
    """
    req = Requisition(
        organisation_id=org.id,
        service_id=modele.service_id,
        numero_requisition=f"REQ-{uuid.uuid4().hex[:8]}",
        reference_numero=f"REF-{uuid.uuid4().hex[:8]}",
        objet="Autre réquisition",
        mode_paiement="cash",
        type_requisition="classique",
        status="SIGNEE_SERVICE",
        examen_status="NON_EXAMINE",
        montant_total=Decimal("0"),
        devise="USD",
        created_by=user.id,
        signed_by_id=user.id,
        signed_at=datetime.now(timezone.utc),
    )
    db.add(req)
    await db.flush()
    await _ligne(db, org, req, poste, montant, rubrique="Voisine")
    return req


async def _lignes(db, req):
    res = await db.execute(
        select(LigneRequisition)
        .where(LigneRequisition.requisition_id == req.id)
        .order_by(LigneRequisition.montant_total)
    )
    return list(res.scalars().all())


async def _payer_lignes(db, org, req, poste, montant, *, ligne=None, comptabilisee=False):
    """Décaissement et son imputation figée.

    `ligne` rattache la sortie à une ligne précise ; sans elle, la sortie couvre
    la réquisition entière — c'est la forme de toutes les sorties déjà en base.
    """
    sortie = SortieFonds(
        organisation_id=org.id,
        requisition_id=req.id,
        ligne_requisition_id=ligne.id if ligne is not None else None,
        type_sortie="REQUISITION",
        budget_poste_id=poste.id,
        montant_paye=montant,
        mode_paiement="cash",
        devise="USD",
        canal="CAISSE",
        statut="VALIDE",
        statut_comptabilisation="COMPTABILISEE" if comptabilisee else "NON_COMPTABILISEE",
        motif="Paiement",
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


async def _payer_multi_postes(db, org, req, repartition: dict, *, montant=None):
    """Un décaissement unique, une imputation par poste.

    C'est la forme que produit le paiement d'une réquisition multi-postes
    (cf. `repartition_postes` dans l'endpoint des sorties de fonds) : une seule
    pièce, autant d'imputations que de postes touchés.
    """
    total = montant if montant is not None else sum(repartition.values(), Decimal("0"))
    premier = next(iter(repartition))
    sortie = SortieFonds(
        organisation_id=org.id,
        requisition_id=req.id,
        type_sortie="REQUISITION",
        budget_poste_id=premier.id,
        montant_paye=total,
        mode_paiement="cash",
        devise="USD",
        canal="CAISSE",
        statut="VALIDE",
        statut_comptabilisation="NON_COMPTABILISEE",
        motif="Paiement multi-postes",
        beneficiaire="Fournisseur",
    )
    db.add(sortie)
    await db.flush()
    for poste, part in repartition.items():
        db.add(
            MouvementBudgetImputation(
                organisation_id=org.id,
                sortie_fonds_id=sortie.id,
                budget_poste_id=poste.id,
                sens="DEPENSE_PAYEE",
                montant_mouvement=part,
                devise_mouvement="USD",
                montant_budget=part,
                statut="ACTIVE",
            )
        )
        poste.montant_paye = Decimal(str(poste.montant_paye or 0)) + part
    await db.flush()
    return sortie


async def _payer_par_ligne(db, org, req, poste, parts: dict):
    """Une pièce de décaissement, une imputation par ligne.

    La forme que produit le décaissement depuis qu'il ventile la part d'un poste
    sur ses lignes : chaque impact sait d'où il vient.
    """
    total = sum(parts.values(), Decimal("0"))
    sortie = SortieFonds(
        organisation_id=org.id,
        requisition_id=req.id,
        type_sortie="REQUISITION",
        budget_poste_id=poste.id,
        montant_paye=total,
        mode_paiement="cash",
        devise="USD",
        canal="CAISSE",
        statut="VALIDE",
        statut_comptabilisation="NON_COMPTABILISEE",
        motif="Paiement ventilé",
        beneficiaire="Fournisseur",
    )
    db.add(sortie)
    await db.flush()
    for ligne, part in parts.items():
        db.add(
            MouvementBudgetImputation(
                organisation_id=org.id,
                sortie_fonds_id=sortie.id,
                budget_poste_id=poste.id,
                ligne_requisition_id=ligne.id,
                sens="DEPENSE_PAYEE",
                montant_mouvement=part,
                devise_mouvement="USD",
                montant_budget=part,
                statut="ACTIVE",
            )
        )
    poste.montant_paye = Decimal(str(poste.montant_paye or 0)) + total
    await db.flush()
    return sortie


async def _imputations(db, req, *, statut="ACTIVE"):
    """Imputations d'une réquisition, par poste, pour un statut donné."""
    res = await db.execute(
        select(MouvementBudgetImputation)
        .join(SortieFonds, SortieFonds.id == MouvementBudgetImputation.sortie_fonds_id)
        .where(
            SortieFonds.requisition_id == req.id,
            MouvementBudgetImputation.statut == statut,
        )
    )
    par_poste: dict[int, Decimal] = {}
    for imp in res.scalars().all():
        par_poste[imp.budget_poste_id] = par_poste.get(imp.budget_poste_id, Decimal("0")) + Decimal(
            str(imp.montant_budget or 0)
        )
    return par_poste


async def _trois_lignes_un_seul_poste(db):
    """Réquisition engagée de trois lignes, toutes sur A : 1000 + 2000 + 4000.

    La forme qu'il faut pour éprouver la répartition d'une sortie unique : un
    paiement multi-postes produirait une imputation par poste, et le prorata se
    lirait alors poste par poste plutôt que sur la sortie entière.
    """
    org = await _org(db)
    user = await _user(db, org)
    a = await _poste(db, org, prevu=PREVU * 2)
    c = await _poste_voisin(db, org, a, prevu=PREVU * 2)
    req = await _requisition(db, org, user, a, montant=L1, examen_status="EN_EXAMEN")
    ligne_l2 = await _ligne(db, org, req, a, L2, rubrique="Deuxieme")
    await _ligne(db, org, req, a, L3, rubrique="Troisieme")
    await resynchroniser_engagement_requisition(db, req)
    return org, user, a, c, req, ligne_l2


async def _trois_lignes(db, *, examen_status="EN_EXAMEN"):
    """Réquisition engagée de trois lignes : deux sur A (1000 + 2000), une sur B (4000)."""
    org = await _org(db)
    user = await _user(db, org)
    a = await _poste(db, org, prevu=PREVU * 2)
    b = await _poste_voisin(db, org, a, prevu=PREVU * 2)
    c = await _poste_voisin(db, org, a, prevu=PREVU * 2)
    req = await _requisition(db, org, user, a, montant=L1, examen_status=examen_status)
    # `_requisition` a déjà posé la première ligne (L1) sur A.
    await _ligne(db, org, req, a, L2, rubrique="Deuxieme")
    await _ligne(db, org, req, b, L3, rubrique="Troisieme")
    await resynchroniser_engagement_requisition(db, req)
    return org, user, a, b, c, req


# ---------------------------------------------------------------------------
# 1. Désigner les lignes qui bougent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seules_les_lignes_designees_changent_de_poste(db_session):
    """Le cœur du sujet : corriger une ligne ne déplace pas ses voisines."""
    org, user, a, b, c, req = await _trois_lignes(db_session)
    lignes = await _lignes(db_session, req)
    ligne_l2 = next(l for l in lignes if Decimal(str(l.montant_total)) == L2)

    resultat = await reimputer_requisition(
        db_session,
        requisition=req,
        nouveau_poste_id=c.id,
        ligne_ids=[ligne_l2.id],
        user_id=user.id,
        motif="La ligne 2 relevait du poste Mission",
    )

    assert resultat["lignes_deplacees"] == 1
    for ligne in await _lignes(db_session, req):
        await db_session.refresh(ligne)
    par_montant = {Decimal(str(l.montant_total)): l.budget_poste_id for l in await _lignes(db_session, req)}
    assert par_montant == {L1: a.id, L2: c.id, L3: b.id}

    # L'engagement suit exactement, poste par poste.
    assert await _engage(db_session, a) == L1
    assert await _engage(db_session, b) == L3
    assert await _engage(db_session, c) == L2


@pytest.mark.asyncio
async def test_sans_ligne_designee_toute_la_requisition_suit(db_session):
    """Le comportement d'origine reste la valeur par défaut : `ligne_ids` omis déplace tout."""
    org, user, a, b, c, req = await _trois_lignes(db_session)

    resultat = await reimputer_requisition(
        db_session,
        requisition=req,
        nouveau_poste_id=c.id,
        user_id=user.id,
        motif="Toute la réquisition relevait de Mission",
    )

    assert resultat["lignes_deplacees"] == 3
    assert {l.budget_poste_id for l in await _lignes(db_session, req)} == {c.id}
    assert await _engage(db_session, a) == Decimal("0")
    assert await _engage(db_session, b) == Decimal("0")
    assert await _engage(db_session, c) == L1 + L2 + L3


@pytest.mark.asyncio
async def test_une_ligne_etrangere_a_la_requisition_est_refusee(db_session):
    """On ne déplace pas la ligne d'une autre réquisition par un identifiant glissé dans la liste."""
    org, user, a, b, c, req = await _trois_lignes(db_session)
    autre = await _requisition_voisine(db_session, org, user, req, a, L1)
    ligne_etrangere = (await _lignes(db_session, autre))[0]

    with pytest.raises(HTTPException) as err:
        await reimputer_requisition(
            db_session,
            requisition=req,
            nouveau_poste_id=c.id,
            ligne_ids=[ligne_etrangere.id],
            user_id=user.id,
            motif="Tentative sur une ligne étrangère",
        )
    assert err.value.status_code in (404, 422)


@pytest.mark.asyncio
async def test_une_liste_de_lignes_vide_est_refusee(db_session):
    """Liste vide n'est pas « toutes les lignes » : c'est une demande sans objet."""
    org, user, a, b, c, req = await _trois_lignes(db_session)

    with pytest.raises(HTTPException) as err:
        await reimputer_requisition(
            db_session,
            requisition=req,
            nouveau_poste_id=c.id,
            ligne_ids=[],
            user_id=user.id,
            motif="Aucune ligne désignée",
        )
    assert err.value.status_code == 422


@pytest.mark.asyncio
async def test_le_disponible_ne_compte_que_les_lignes_deplacees(db_session):
    """Le contrôle de dépassement porte sur ce qui arrive, pas sur toute la réquisition.

    Le poste d'arrivée a de quoi accueillir la ligne de 1000, mais pas les 7000
    de la réquisition entière : déplacer la seule petite ligne doit passer.
    """
    org, user, a, b, c, req = await _trois_lignes(db_session)
    c.montant_prevu = L1
    await db_session.flush()
    lignes = await _lignes(db_session, req)
    ligne_l1 = next(l for l in lignes if Decimal(str(l.montant_total)) == L1)

    resultat = await reimputer_requisition(
        db_session,
        requisition=req,
        nouveau_poste_id=c.id,
        ligne_ids=[ligne_l1.id],
        user_id=user.id,
        motif="Le poste étroit accueille la petite ligne",
    )

    assert resultat["montant_engage_deplace"] == L1
    assert await _engage(db_session, c) == L1


# ---------------------------------------------------------------------------
# 2. Le paiement suit la ligne qu'il a payée
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_la_sortie_rattachee_a_une_ligne_suit_cette_ligne(db_session):
    """Deux paiements, deux lignes : celui qui ne bouge pas reste où il est."""
    org, user, a, b, c, req = await _trois_lignes(db_session)
    lignes = await _lignes(db_session, req)
    ligne_l1 = next(l for l in lignes if Decimal(str(l.montant_total)) == L1)
    ligne_l2 = next(l for l in lignes if Decimal(str(l.montant_total)) == L2)
    sortie_l1 = await _payer_lignes(db_session, org, req, a, L1, ligne=ligne_l1)
    sortie_l2 = await _payer_lignes(db_session, org, req, a, L2, ligne=ligne_l2)

    resultat = await reimputer_requisition(
        db_session,
        requisition=req,
        nouveau_poste_id=c.id,
        ligne_ids=[ligne_l2.id],
        user_id=user.id,
        motif="Le paiement de la ligne 2 changeait de poste",
    )

    await db_session.refresh(sortie_l1)
    await db_session.refresh(sortie_l2)
    assert sortie_l1.budget_poste_id == a.id, "la sortie de la ligne restée sur A ne bouge pas"
    assert sortie_l2.budget_poste_id == c.id
    assert resultat["montant_paye_deplace"] == L2

    # Le réalisé a changé de poste sans changer de total.
    assert await _imputations(db_session, req) == {a.id: L1, c.id: L2}
    assert await _paye(db_session, a) == L1
    assert await _paye(db_session, c) == L2


@pytest.mark.asyncio
async def test_une_sortie_globale_est_repartie_au_prorata(db_session):
    """Une sortie non rattachée couvre toutes les lignes : son imputation se scinde.

    C'est le cas de toutes les sorties déjà en base, que la reprise de données
    ne pourra pas rattacher rétroactivement.
    """
    org, user, a, c, req, ligne_l2 = await _trois_lignes_un_seul_poste(db_session)
    # Un seul décaissement pour toute la réquisition, non rattaché à une ligne.
    total = L1 + L2 + L3
    sortie = await _payer_lignes(db_session, org, req, a, total)

    await reimputer_requisition(
        db_session,
        requisition=req,
        nouveau_poste_id=c.id,
        ligne_ids=[ligne_l2.id],
        user_id=user.id,
        motif="Scission au prorata",
    )

    # L'imputation d'origine cède la place à deux imputations, une par poste :
    # la ligne qui part emmène sa part, 2000 sur 7000.
    actives = await _imputations(db_session, req)
    assert actives == {a.id: total - L2, c.id: L2}
    annulees = await _imputations(db_session, req, statut="ANNULEE")
    assert annulees == {a.id: total}, "l'imputation d'origine est annulée, pas modifiée"

    # La pièce de décaissement, elle, n'est jamais scindée.
    await db_session.refresh(sortie)
    assert Decimal(str(sortie.montant_paye)) == total
    assert sortie.budget_poste_id == a.id, "la sortie reste où un reliquat demeure"

    assert await _paye(db_session, a) == total - L2
    assert await _paye(db_session, c) == L2


@pytest.mark.asyncio
async def test_une_sortie_multi_postes_ne_touche_que_le_poste_concerne(db_session):
    """Le prorata se prend poste par poste, jamais sur la réquisition entière.

    Payer une réquisition multi-postes crée une imputation par poste : 3000 sur
    A (les lignes de 1000 et 2000), 4000 sur B (la ligne de 4000). Déplacer la
    ligne de 2000 ne regarde que A — il en cède les deux tiers. Le réalisé de B
    n'a rien à voir avec ce déplacement et ne doit pas bouger d'un centime.
    """
    org, user, a, b, c, req = await _trois_lignes(db_session)
    lignes = await _lignes(db_session, req)
    ligne_l2 = next(l for l in lignes if Decimal(str(l.montant_total)) == L2)
    await _payer_multi_postes(db_session, org, req, {a: L1 + L2, b: L3})

    resultat = await reimputer_requisition(
        db_session,
        requisition=req,
        nouveau_poste_id=c.id,
        ligne_ids=[ligne_l2.id],
        user_id=user.id,
        motif="Seul le poste A est concerné",
    )

    assert resultat["montant_paye_deplace"] == L2
    assert await _imputations(db_session, req) == {a.id: L1, b.id: L3, c.id: L2}
    assert await _imputations(db_session, req, statut="ANNULEE") == {a.id: L1 + L2}, (
        "seule l'imputation du poste concerné est remplacée"
    )
    assert await _paye(db_session, b) == L3, "le réalisé du poste étranger ne bouge pas"


@pytest.mark.asyncio
async def test_un_paiement_partiel_non_rattache_se_repartit_sur_la_requisition(db_session):
    """`NULL` veut dire « couvre la réquisition », pas « couvre telles lignes ».

    Un acompte de 3000 sur une réquisition de 7000 n'appartient à aucune ligne en
    particulier. Déplacer la ligne de 2000 en emporte donc la même proportion :
    3000 × 2000/7000 = 857.14, et 2142.86 restent sur le poste d'origine.
    """
    org, user, a, c, req, ligne_l2 = await _trois_lignes_un_seul_poste(db_session)
    await _payer_lignes(db_session, org, req, a, Decimal("3000.00"))

    resultat = await reimputer_requisition(
        db_session,
        requisition=req,
        nouveau_poste_id=c.id,
        ligne_ids=[ligne_l2.id],
        user_id=user.id,
        motif="Acompte réparti",
    )

    assert resultat["montant_paye_deplace"] == Decimal("857.14")
    assert await _imputations(db_session, req) == {
        a.id: Decimal("2142.86"),
        c.id: Decimal("857.14"),
    }


@pytest.mark.asyncio
async def test_le_prorata_ne_perd_pas_un_centime(db_session):
    """Des montants qui ne se divisent pas rond ne doivent créer ni perte ni excédent.

    100.00 partagés entre 33.33, 33.33 et 33.34 : au centime près, la somme des
    imputations actives reste 100.00.
    """
    org = await _org(db_session)
    user = await _user(db_session, org)
    a = await _poste(db_session, org)
    c = await _poste_voisin(db_session, org, a)
    req = await _requisition(db_session, org, user, a, montant=Decimal("33.33"), examen_status="EN_EXAMEN")
    await _ligne(db_session, org, req, a, Decimal("33.33"), rubrique="Deuxieme")
    await _ligne(db_session, org, req, a, Decimal("33.34"), rubrique="Troisieme")
    await resynchroniser_engagement_requisition(db_session, req)
    sortie = await _payer_lignes(db_session, org, req, a, Decimal("100.00"))
    lignes = await _lignes(db_session, req)
    bougent = [lignes[0].id, lignes[1].id]

    await reimputer_requisition(
        db_session,
        requisition=req,
        nouveau_poste_id=c.id,
        ligne_ids=bougent,
        user_id=user.id,
        motif="Arrondi",
    )

    actives = await _imputations(db_session, req)
    assert sum(actives.values()) == Decimal("100.00"), "le total du réalisé est invariant"
    assert await _paye(db_session, a) + await _paye(db_session, c) == Decimal("100.00")


@pytest.mark.asyncio
async def test_une_sortie_comptabilisee_bloque_meme_un_deplacement_partiel(db_session):
    """Le refus sur pièce comptabilisée ne s'assouplit pas parce qu'on ne bouge qu'une ligne."""
    org, user, a, b, c, req = await _trois_lignes(db_session)
    lignes = await _lignes(db_session, req)
    ligne_l2 = next(l for l in lignes if Decimal(str(l.montant_total)) == L2)
    await _payer_lignes(db_session, org, req, a, L2, ligne=ligne_l2, comptabilisee=True)

    with pytest.raises(HTTPException) as err:
        await reimputer_requisition(
            db_session,
            requisition=req,
            nouveau_poste_id=c.id,
            ligne_ids=[ligne_l2.id],
            user_id=user.id,
            motif="Tentative sur pièce comptabilisée",
        )
    assert err.value.status_code == 409


# ---------------------------------------------------------------------------
# 3. La ligne orpheline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_une_ligne_orpheline_recoit_le_poste_de_ses_voisines(db_session):
    """Bug de bord : une ligne sans poste ne peut pas recevoir le poste des autres.

    `postes_de_requisition` écarte les lignes à NULL. Une réquisition dont une
    ligne est sur C et l'autre sans poste renvoie `[C]`, et le garde-fou
    « déjà imputée sur ce poste » refuse — la ligne orpheline reste orpheline.
    """
    org = await _org(db_session)
    user = await _user(db_session, org)
    c = await _poste(db_session, org)
    req = await _requisition(db_session, org, user, c, montant=L1, examen_status="EN_EXAMEN")
    orpheline = await _ligne(db_session, org, req, None, L2, rubrique="Sans poste")
    await resynchroniser_engagement_requisition(db_session, req)

    await reimputer_requisition(
        db_session,
        requisition=req,
        nouveau_poste_id=c.id,
        ligne_ids=[orpheline.id],
        user_id=user.id,
        motif="La ligne était restée sans imputation",
    )

    await db_session.refresh(orpheline)
    assert orpheline.budget_poste_id == c.id
    assert await _engage(db_session, c) == L1 + L2


@pytest.mark.asyncio
async def test_deplacer_les_lignes_deja_sur_le_poste_reste_refuse(db_session):
    """Le garde-fou d'origine survit : désigner des lignes déjà sur le poste n'a pas d'objet."""
    org, user, a, b, c, req = await _trois_lignes(db_session)
    lignes = await _lignes(db_session, req)
    ligne_l1 = next(l for l in lignes if Decimal(str(l.montant_total)) == L1)

    with pytest.raises(HTTPException) as err:
        await reimputer_requisition(
            db_session,
            requisition=req,
            nouveau_poste_id=a.id,
            ligne_ids=[ligne_l1.id],
            user_id=user.id,
            motif="Déjà sur ce poste",
        )
    assert err.value.status_code == 422


# ---------------------------------------------------------------------------
# 4. L'aperçu dit ce qui va bouger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_l_apercu_detaille_les_lignes_et_la_repartition(db_session):
    """Avant de décider, on voit quelles lignes partent et pour quel montant — sans rien écrire."""
    org, user, a, c, req, ligne_l2 = await _trois_lignes_un_seul_poste(db_session)
    await _payer_lignes(db_session, org, req, a, L1 + L2 + L3)
    engage_avant = await _engage(db_session, a)

    apercu = await apercu_reimputation(
        db_session,
        requisition=req,
        nouveau_poste_id=c.id,
        ligne_ids=[ligne_l2.id],
    )

    assert apercu["lignes"] == 1
    assert apercu["montant_engage_deplace"] == L2
    assert apercu["montant_paye_deplace"] == L2, "la part prorata du décaissement global"
    assert await _engage(db_session, a) == engage_avant, "l'aperçu n'écrit rien"


@pytest.mark.asyncio
async def test_l_apercu_annonce_la_fusion_de_plusieurs_postes(db_session):
    """Déplacer toute une réquisition étalée sur deux postes les fusionne : ça doit se voir.

    C'est le silence d'aujourd'hui qui pose problème, pas le déplacement en bloc
    lui-même : l'aperçu doit nommer les postes qui disparaissent de la réquisition.
    """
    org, user, a, b, c, req = await _trois_lignes(db_session)

    apercu = await apercu_reimputation(db_session, requisition=req, nouveau_poste_id=c.id)

    assert sorted(apercu["postes_avant"]) == sorted([a.id, b.id])
    assert apercu["fusionne_plusieurs_postes"] is True


# ---------------------------------------------------------------------------
# 5. Ce que le décaissement inscrit dans le lien
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_le_decaissement_rattache_la_sortie_quand_la_ligne_est_certaine(db_session):
    """Une réquisition d'une seule ligne : la sortie dit laquelle elle paie."""
    org = await _org(db_session)
    user = await _user(db_session, org)
    poste = await _poste(db_session, org)
    req = await _requisition(db_session, org, user, poste, montant=L1)
    ligne = (await _lignes(db_session, req))[0]

    assert await _ligne_unique_de_requisition(db_session, req.id) == ligne.id


@pytest.mark.asyncio
async def test_le_decaissement_ne_rattache_rien_quand_la_requisition_a_plusieurs_lignes(db_session):
    """Le circuit paie par poste, pas par ligne : au-delà d'une ligne, le lien resterait faux.

    `NULL` n'est pas un oubli, c'est l'énoncé exact de ce que la sortie couvre —
    la réquisition entière. La ré-imputation s'appuie dessus pour répartir.
    """
    org, user, a, b, c, req = await _trois_lignes(db_session)

    assert await _ligne_unique_de_requisition(db_session, req.id) is None
    assert await _ligne_unique_de_requisition(db_session, None) is None


@pytest.mark.asyncio
async def test_une_imputation_qui_connait_sa_ligne_part_sans_prorata(db_session):
    """Le chemin exact : plus de répartition dès que le décaissement a nommé la ligne.

    Deux lignes sur le même poste, payées d'une seule pièce mais imputées ligne
    par ligne — ce que produit désormais `_ventiler_par_ligne`. Déplacer l'une
    emmène son impact entier ; l'autre ne bouge pas d'un centime, et aucune
    imputation n'est annulée puisqu'il n'y a rien à scinder.
    """
    org, user, a, c, req, ligne_l2 = await _trois_lignes_un_seul_poste(db_session)
    lignes = await _lignes(db_session, req)
    ligne_l1 = next(l for l in lignes if Decimal(str(l.montant_total)) == L1)
    sortie = await _payer_par_ligne(db_session, org, req, a, {ligne_l1: L1, ligne_l2: L2})

    resultat = await reimputer_requisition(
        db_session,
        requisition=req,
        nouveau_poste_id=c.id,
        ligne_ids=[ligne_l2.id],
        user_id=user.id,
        motif="La ligne nommée emmène son impact",
    )

    assert resultat["montant_paye_deplace"] == L2
    assert resultat["sorties_reparties"] == 0, "rien à répartir : la ligne était connue"
    assert await _imputations(db_session, req) == {a.id: L1, c.id: L2}
    assert await _imputations(db_session, req, statut="ANNULEE") == {}

    # La pièce couvre encore une ligne restée sur A : elle ne suit pas.
    await db_session.refresh(sortie)
    assert sortie.budget_poste_id == a.id
