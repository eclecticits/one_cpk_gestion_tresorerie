"""Ré-imputation d'un encaissement sur un autre poste de recette.

Le poste d'un encaissement vit sur l'en-tête, les lignes, les versements, les
imputations figées et les compteurs des postes. Ces tests verrouillent que la
chaîne entière suit — le réalisé quitte un poste pour l'autre sans qu'un
centime ne se crée ni ne se perde —, ou que rien ne bouge.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select

from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.encaissement import Encaissement, EncaissementArticle
from app.models.mouvement_budget_imputation import MouvementBudgetImputation
from app.models.payment_history import PaymentHistory
from app.models.service_rubrique import ServiceRubrique
from app.schemas.payment import EncaissementArticleCreate, EncaissementCreate
from app.services.reimputation_encaissement import (
    apercu_reimputation_encaissement,
    reimputer_encaissement,
)

# Les écritures comptables sont générées dans le flux : sans cet import, les
# tables `compta_*` manquent aux métadonnées quand ce fichier tourne seul.
from app.modules.comptabilite import models as _compta_models  # noqa: F401

from test_encaissement_repartition import _contexte


async def _poste(db, org, modele, *, type_poste="RECETTE", service=None, libelle="Droits divers"):
    poste = BudgetPoste(
        organisation_id=org.id, exercice_id=modele.exercice_id, code=f"P-{uuid.uuid4().hex[:6]}",
        libelle=libelle, type=type_poste, active=True, montant_prevu=Decimal("100000"),
        montant_engage=0, montant_paye=0, is_deleted=False,
    )
    db.add(poste)
    await db.flush()
    if service is not None:
        db.add(ServiceRubrique(service_id=service.id, budget_poste_id=poste.id, active=True))
        await db.flush()
    return poste


async def _encaisser(db, monkeypatch, org, user, service, poste_entete, articles, *, payer=None):
    """Crée la note par le vrai flux, puis la règle (en tout ou partie) s'il y a lieu."""
    from app.api.v1.endpoints.encaissements import create_encaissement
    from app.services.encaissement_payments import record_encaissement_payment

    async def faux_recu(**_kwargs):
        return f"REC-{uuid.uuid4().hex[:8]}"

    monkeypatch.setattr("app.api.v1.endpoints.encaissements._generate_numero_recu", faux_recu)
    total = sum((montant for _libelle, montant, _poste in articles), Decimal("0"))
    reponse = await create_encaissement(
        payload=EncaissementCreate(
            type_client="personne_physique", client_sexe="M", client_nom="Cabinet ABC",
            libelle="Recette", montant=total, montant_total=total, montant_paye=Decimal("0"),
            mode_paiement="cash", canal="CAISSE", service_id=service.id,
            budget_poste_id=poste_entete.id,
            articles=[
                EncaissementArticleCreate(
                    libelle=libelle, quantite=1, prix_unitaire=montant, montant=montant,
                    budget_poste_id=poste.id,
                )
                for libelle, montant, poste in articles
            ],
        ),
        background_tasks=BackgroundTasks(),
        user=user,
        tenant_id=org.id,
        db=db,
    )
    await db.commit()
    encaissement_id = uuid.UUID(str(reponse["id"]))
    if payer:
        await record_encaissement_payment(
            db, organisation_id=org.id, encaissement_id=encaissement_id, montant=payer,
            mode_paiement="cash", reference=None, notes=None, user_id=user.id,
        )
        await db.commit()
    return await _lire(db, encaissement_id)


async def _lire(db, encaissement_id) -> Encaissement:
    res = await db.execute(
        select(Encaissement).where(Encaissement.id == encaissement_id).execution_options(populate_existing=True)
    )
    return res.scalar_one()


async def _paye(db, poste) -> Decimal:
    res = await db.execute(select(BudgetPoste.montant_paye).where(BudgetPoste.id == poste.id))
    return Decimal(res.scalar_one() or 0)


async def _imputations_actives(db, org) -> list[tuple[int, Decimal]]:
    res = await db.execute(
        select(MouvementBudgetImputation.budget_poste_id, MouvementBudgetImputation.montant_budget).where(
            MouvementBudgetImputation.organisation_id == org.id,
            MouvementBudgetImputation.statut == "ACTIVE",
        )
    )
    return sorted((pid, Decimal(str(m))) for pid, m in res.all())


async def _articles(db, encaissement) -> list[EncaissementArticle]:
    res = await db.execute(
        select(EncaissementArticle)
        .where(EncaissementArticle.encaissement_id == encaissement.id)
        .order_by(EncaissementArticle.sort_order)
        .execution_options(populate_existing=True)
    )
    return list(res.scalars().all())


@pytest.mark.asyncio
async def test_une_note_payee_change_de_poste_avec_son_realise(db_session, monkeypatch):
    db = db_session
    org, user, service, (cotisations, frais) = await _contexte(db)
    enc = await _encaisser(
        db, monkeypatch, org, user, service, cotisations,
        [("Cotisation annuelle", Decimal("400"), cotisations)], payer=Decimal("400"),
    )
    assert await _paye(db, cotisations) == Decimal("400")

    resultat = await reimputer_encaissement(
        db, encaissement=enc, nouveau_poste_id=frais.id, user_id=user.id, motif="Erreur de rubrique",
    )
    await db.commit()

    assert resultat["montant_paye_deplace"] == Decimal("400")
    assert await _paye(db, cotisations) == Decimal("0")
    assert await _paye(db, frais) == Decimal("400")
    assert await _imputations_actives(db, org) == [(frais.id, Decimal("400"))]

    enc = await _lire(db, enc.id)
    assert enc.budget_poste_id == frais.id
    assert enc.budget_poste_code == frais.code
    assert [a.budget_poste_id for a in await _articles(db, enc)] == [frais.id]
    paiement = (
        await db.execute(
            select(PaymentHistory)
            .where(PaymentHistory.encaissement_id == enc.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert paiement.budget_poste_id == frais.id


@pytest.mark.asyncio
async def test_une_ligne_seule_emporte_sa_part_et_laisse_la_voisine(db_session, monkeypatch):
    """Cotisation et inscription sur deux postes : seule l'inscription se trompait."""
    db = db_session
    org, user, service, (cotisations, frais) = await _contexte(db)
    droits = await _poste(db, org, cotisations, service=service)
    await db.commit()
    enc = await _encaisser(
        db, monkeypatch, org, user, service, cotisations,
        [("Cotisation", Decimal("300"), cotisations), ("Inscription", Decimal("100"), frais)],
        payer=Decimal("200"),
    )
    inscription = (await _articles(db, enc))[1]

    apercu = await apercu_reimputation_encaissement(
        db, encaissement=enc, nouveau_poste_id=droits.id, article_ids=[inscription.id]
    )
    assert apercu["montant_paye_deplace"] == Decimal("50")
    assert apercu["lignes"] == 1 and apercu["lignes_total"] == 2

    await reimputer_encaissement(
        db, encaissement=enc, nouveau_poste_id=droits.id, article_ids=[inscription.id],
        user_id=user.id, motif="Frais d'inscription mal classés",
    )
    await db.commit()

    assert await _paye(db, cotisations) == Decimal("150")
    assert await _paye(db, frais) == Decimal("0")
    assert await _paye(db, droits) == Decimal("50")
    enc = await _lire(db, enc.id)
    # L'en-tête désigne toujours une ligne : il ne bouge pas.
    assert enc.budget_poste_id == cotisations.id
    assert [a.budget_poste_id for a in await _articles(db, enc)] == [cotisations.id, droits.id]


@pytest.mark.asyncio
async def test_deux_lignes_d_un_meme_poste_se_partagent_le_versement(db_session, monkeypatch):
    """Le versement ne sait pas de quelle ligne il vient : il cède au prorata."""
    db = db_session
    org, user, service, (cotisations, frais) = await _contexte(db)
    enc = await _encaisser(
        db, monkeypatch, org, user, service, cotisations,
        [("Cotisation", Decimal("300"), cotisations), ("Inscription", Decimal("100"), cotisations)],
        payer=Decimal("400"),
    )
    inscription = (await _articles(db, enc))[1]

    await reimputer_encaissement(
        db, encaissement=enc, nouveau_poste_id=frais.id, article_ids=[inscription.id],
        user_id=user.id, motif="Inscription imputée en cotisation",
    )
    await db.commit()

    assert await _paye(db, cotisations) == Decimal("300")
    assert await _paye(db, frais) == Decimal("100")
    # L'originale est annulée, deux remplaçantes la reprennent : le total est invariant.
    assert await _imputations_actives(db, org) == sorted([(cotisations.id, Decimal("300")), (frais.id, Decimal("100"))])

    # Le solde d'un versement ultérieur suit les nouvelles lignes.
    from app.services.encaissement_payments import cancel_encaissement_payment

    paiement = (await db.execute(select(PaymentHistory).where(PaymentHistory.encaissement_id == enc.id))).scalar_one()
    await cancel_encaissement_payment(
        db, organisation_id=org.id, payment_id=paiement.id, motif_annulation="Erreur de caisse", user_id=user.id,
    )
    await db.commit()
    # L'annulation rend à chaque poste ce qu'il porte désormais.
    assert await _paye(db, cotisations) == Decimal("0")
    assert await _paye(db, frais) == Decimal("0")


@pytest.mark.asyncio
async def test_une_note_impayee_ne_change_que_ses_postes(db_session, monkeypatch):
    db = db_session
    org, user, service, (cotisations, frais) = await _contexte(db)
    enc = await _encaisser(
        db, monkeypatch, org, user, service, cotisations, [("Cotisation", Decimal("250"), cotisations)],
    )
    resultat = await reimputer_encaissement(
        db, encaissement=enc, nouveau_poste_id=frais.id, user_id=user.id, motif="Mauvaise rubrique",
    )
    await db.commit()
    assert resultat["montant_paye_deplace"] == Decimal("0")
    assert await _paye(db, frais) == Decimal("0")
    enc = await _lire(db, enc.id)
    assert enc.budget_poste_id == frais.id


@pytest.mark.asyncio
async def test_un_poste_de_depense_est_refuse(db_session, monkeypatch):
    """Un encaissement relève du budget des recettes."""
    db = db_session
    org, user, service, (cotisations, _frais) = await _contexte(db)
    depense = await _poste(db, org, cotisations, type_poste="DEPENSE", service=service)
    await db.commit()
    enc = await _encaisser(
        db, monkeypatch, org, user, service, cotisations,
        [("Cotisation", Decimal("100"), cotisations)], payer=Decimal("100"),
    )
    with pytest.raises(HTTPException) as exc:
        await reimputer_encaissement(
            db, encaissement=enc, nouveau_poste_id=depense.id, user_id=user.id, motif="Essai",
        )
    assert exc.value.status_code == 422
    assert await _paye(db, cotisations) == Decimal("100")


@pytest.mark.asyncio
async def test_un_poste_non_autorise_au_service_est_refuse(db_session, monkeypatch):
    db = db_session
    org, user, service, (cotisations, _frais) = await _contexte(db)
    etranger = await _poste(db, org, cotisations)
    await db.commit()
    enc = await _encaisser(
        db, monkeypatch, org, user, service, cotisations, [("Cotisation", Decimal("100"), cotisations)],
    )
    with pytest.raises(HTTPException) as exc:
        await reimputer_encaissement(
            db, encaissement=enc, nouveau_poste_id=etranger.id, user_id=user.id, motif="Essai",
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_un_autre_exercice_est_refuse(db_session, monkeypatch):
    db = db_session
    org, user, service, (cotisations, _frais) = await _contexte(db)
    exercice = BudgetExercice(organisation_id=org.id, annee=2027, statut=StatutBudget.VOTE)
    db.add(exercice)
    await db.flush()
    suivant = BudgetPoste(
        organisation_id=org.id, exercice_id=exercice.id, code=f"N-{uuid.uuid4().hex[:6]}", libelle="Cotisations",
        type="RECETTE", active=True, montant_prevu=Decimal("1000"), montant_engage=0, montant_paye=0,
        is_deleted=False,
    )
    db.add(suivant)
    await db.flush()
    db.add(ServiceRubrique(service_id=service.id, budget_poste_id=suivant.id, active=True))
    await db.commit()
    enc = await _encaisser(
        db, monkeypatch, org, user, service, cotisations,
        [("Cotisation", Decimal("100"), cotisations)], payer=Decimal("100"),
    )
    with pytest.raises(HTTPException) as exc:
        await reimputer_encaissement(
            db, encaissement=enc, nouveau_poste_id=suivant.id, user_id=user.id, motif="Essai",
        )
    assert exc.value.status_code == 422
    assert "exercice" in exc.value.detail


@pytest.mark.asyncio
async def test_le_poste_deja_en_place_et_le_motif_vide_sont_refuses(db_session, monkeypatch):
    db = db_session
    org, user, service, (cotisations, frais) = await _contexte(db)
    enc = await _encaisser(
        db, monkeypatch, org, user, service, cotisations, [("Cotisation", Decimal("100"), cotisations)],
    )
    with pytest.raises(HTTPException) as exc:
        await reimputer_encaissement(
            db, encaissement=enc, nouveau_poste_id=cotisations.id, user_id=user.id, motif="Essai",
        )
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        await reimputer_encaissement(db, encaissement=enc, nouveau_poste_id=frais.id, user_id=user.id, motif=" ")
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_un_encaissement_hors_budget_passe_par_l_affectation(db_session, monkeypatch):
    db = db_session
    org, user, service, (cotisations, frais) = await _contexte(db)
    enc = await _encaisser(
        db, monkeypatch, org, user, service, cotisations, [("Cotisation", Decimal("100"), cotisations)],
    )
    enc.nature_mouvement = "HORS_BUDGET_A_REGULARISER"
    await db.flush()
    with pytest.raises(HTTPException) as exc:
        await reimputer_encaissement(
            db, encaissement=enc, nouveau_poste_id=frais.id, user_id=user.id, motif="Essai",
        )
    assert exc.value.status_code == 422
    assert "Affecter au budget" in exc.value.detail


# ---------------------------------------------------------------------------
# Le brouillon comptable suit le poste ; l'écriture validée, non
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_le_brouillon_comptable_change_de_compte_de_produit(db_session):
    from datetime import date

    from sqlalchemy.orm import selectinload

    from app.core.tenant_context import set_current_tenant_id
    from app.modules.comptabilite.models import ComptaCompte, ComptaEcriture, ComptaMappingPosteBudgetaire
    from app.modules.comptabilite.services.generation_service import (
        generer_ecriture_encaissement,
        reecrire_produits_ecriture_brouillon,
    )
    from test_comptabilite_generation import _map, _org, _setup, _suffix

    db = db_session
    set_current_tenant_id(None)
    org = _org(f"reimput-enc-{_suffix()}")
    db.add(org)
    await db.flush()
    set_current_tenant_id(org.id)
    ctx = await _setup(db, org.id)
    await _map(db, org.id, ctx)

    # Un second poste de recette, sur un autre compte de produit.
    autre_produit = ComptaCompte(
        organisation_id=org.id, referentiel_id=ctx["compte_produit"].referentiel_id,
        numero="7061", libelle="Droits d'inscription", nature="PRODUIT", sens_normal="CREDIT",
    )
    db.add(autre_produit)
    autre_poste = await _poste(db, org, ctx["budget_poste_recette"], libelle="Inscriptions")
    db.add(ComptaMappingPosteBudgetaire(organisation_id=org.id, budget_poste_id=autre_poste.id, compte_id=autre_produit.id))
    await db.flush()

    ecriture = await generer_ecriture_encaissement(
        db, organisation_id=org.id, encaissement_id=str(uuid.uuid4()), date_operation=date(2026, 6, 2),
        montant=Decimal("100.00"), devise="USD", canal="CAISSE", compte_bancaire_id=ctx["caisse"].id,
        budget_poste_id=ctx["budget_poste_recette"].id, libelle="Cotisation",
    )
    await reecrire_produits_ecriture_brouillon(
        db, ecriture=ecriture,
        produits=[(ctx["budget_poste_recette"].id, Decimal("60.00")), (autre_poste.id, Decimal("40.00"))],
    )
    await db.commit()

    relue = (
        await db.execute(
            select(ComptaEcriture)
            .options(selectinload(ComptaEcriture.lignes))
            .where(ComptaEcriture.id == ecriture.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    par_compte = {ligne.compte_id: ligne for ligne in relue.lignes}
    assert par_compte[ctx["compte_caisse"].id].debit == Decimal("100.00")
    assert par_compte[ctx["compte_produit"].id].credit == Decimal("60.00")
    assert par_compte[autre_produit.id].credit == Decimal("40.00")

    # Des produits qui ne couvrent pas la trésorerie déséquilibreraient l'écriture.
    with pytest.raises(HTTPException) as exc:
        await reecrire_produits_ecriture_brouillon(
            db, ecriture=relue, produits=[(autre_poste.id, Decimal("90.00"))]
        )
    assert exc.value.status_code == 400

    # Validée, elle a atteint le Grand Livre : on ne la réécrit plus.
    relue.statut = "VALIDEE"
    with pytest.raises(HTTPException) as exc:
        await reecrire_produits_ecriture_brouillon(
            db, ecriture=relue, produits=[(autre_poste.id, Decimal("100.00"))]
        )
    assert exc.value.status_code == 409
    await db.rollback()
    set_current_tenant_id(None)
