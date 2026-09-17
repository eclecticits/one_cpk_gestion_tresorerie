"""Un reçu peut mêler deux natures : chaque poste reçoit sa part, à l'exact.

Un encaissement n'imputait qu'un poste. Ses articles portent désormais le leur,
et chaque versement — un encaissement se règle parfois en plusieurs fois — se
répartit entre eux au prorata. Ce qui doit tenir : la somme des parts vaut le
versement au centime près, et l'annulation rend à chaque poste ce qu'il a reçu.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import select

from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.caisse_centrale import CaisseCentrale
from app.models.mouvement_budget_imputation import MouvementBudgetImputation
from app.models.organisation import Organisation
from app.models.service import Service
from app.models.service_rubrique import ServiceRubrique
from app.models.user import User
from app.schemas.payment import EncaissementArticleCreate, EncaissementCreate
from app.services.encaissement_repartition import repartir

# Les écritures comptables sont générées dans le flux : sans cet import, les
# tables `compta_*` manquent aux métadonnées quand ce fichier tourne seul.
from app.modules.comptabilite import models as _compta_models  # noqa: F401


class _FakeRequest:
    headers: dict = {}
    client = None


# ---------------------------------------------------------------------------
# La règle d'arrondi, isolée
# ---------------------------------------------------------------------------


def test_un_seul_poste_recoit_le_versement_entier():
    """Pas de prorata, donc pas d'arrondi : le cas courant reste exact."""
    assert repartir([(7, Decimal("120"))], Decimal("120")) == [(7, Decimal("120"))]
    assert repartir([(7, Decimal("120"))], Decimal("40")) == [(7, Decimal("40"))]


def test_la_somme_des_parts_vaut_toujours_le_versement():
    """Trois tiers d'un centime indivisible : l'écart va à la plus grosse part,
    jamais aux arrondis. Sinon le budget encaisserait moins que la caisse."""
    parts = repartir(
        [(1, Decimal("10")), (2, Decimal("10")), (3, Decimal("10"))], Decimal("10")
    )
    assert sum(part for _poste, part in parts) == Decimal("10")
    assert sorted(part for _poste, part in parts) == [
        Decimal("3.33"),
        Decimal("3.33"),
        Decimal("3.34"),
    ]


def test_une_ligne_sans_poste_suit_celui_de_l_encaissement():
    """Le repli garde son sens : une ligne muette s'impute où l'encaissement
    s'impute, exactement comme avant les postes par article."""
    parts = repartir([(None, Decimal("60")), (2, Decimal("40"))], Decimal("100"), poste_par_defaut=1)
    assert sorted(parts) == [(1, Decimal("60")), (2, Decimal("40"))]


def test_un_acompte_se_partage_dans_la_proportion_des_articles():
    """La moitié versée apporte la moitié à chacun, pas le tout au premier."""
    parts = repartir([(1, Decimal("300")), (2, Decimal("100"))], Decimal("200"))
    assert sorted(parts) == [(1, Decimal("150")), (2, Decimal("50"))]


# ---------------------------------------------------------------------------
# Le flux réel : deux postes, deux versements, puis une annulation
# ---------------------------------------------------------------------------


async def _contexte(db):
    org = Organisation(nom="Recettes", slug=f"rc-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex[:8]}@ex.com", role="admin", organisation_id=org.id)
    service = Service(organisation_id=org.id, code=f"S{uuid.uuid4().hex[:4]}", libelle="Service", is_active=True)
    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.VOTE)
    db.add_all([user, service, exercice])
    db.add(CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("0"), solde_cdf=0, est_ouverte=True))
    await db.flush()
    postes = []
    for suffixe, libelle in (("A", "Cotisations"), ("B", "Frais d'inscription")):
        poste = BudgetPoste(
            organisation_id=org.id, exercice_id=exercice.id, code=f"REC-{suffixe}-{uuid.uuid4().hex[:4]}",
            libelle=libelle, type="RECETTE", active=True, montant_prevu=Decimal("100000"),
            montant_engage=0, montant_paye=0, is_deleted=False,
        )
        db.add(poste)
        postes.append(poste)
    await db.flush()
    for poste in postes:
        db.add(ServiceRubrique(service_id=service.id, budget_poste_id=poste.id, active=True))
    await db.commit()
    return org, user, service, postes


@pytest.mark.asyncio
async def test_deux_articles_deux_postes_chacun_sa_part(db_session, monkeypatch):
    from app.api.v1.endpoints.encaissements import create_encaissement
    from app.services.encaissement_payments import cancel_encaissement_payment, record_encaissement_payment

    async def faux_recu(**_kwargs):
        return f"REC-{uuid.uuid4().hex[:8]}"

    monkeypatch.setattr("app.api.v1.endpoints.encaissements._generate_numero_recu", faux_recu)

    db = db_session
    org, user, service, (cotisations, frais) = await _contexte(db)

    encaissement = await create_encaissement(
        payload=EncaissementCreate(
            type_client="client_externe",
            client_nom="Cabinet ABC",
            libelle="Cotisation et inscription",
            montant=Decimal("400"),
            montant_total=Decimal("400"),
            montant_paye=Decimal("0"),
            mode_paiement="cash",
            canal="CAISSE",
            service_id=service.id,
            budget_poste_id=cotisations.id,
            articles=[
                EncaissementArticleCreate(
                    libelle="Cotisation annuelle", quantite=1, prix_unitaire=Decimal("300"),
                    montant=Decimal("300"), budget_poste_id=cotisations.id,
                ),
                EncaissementArticleCreate(
                    libelle="Frais d'inscription", quantite=1, prix_unitaire=Decimal("100"),
                    montant=Decimal("100"), budget_poste_id=frais.id,
                ),
            ],
        ),
        background_tasks=BackgroundTasks(),
        user=user,
        tenant_id=org.id,
        db=db,
    )
    await db.commit()
    encaissement_id = uuid.UUID(str(encaissement["id"]))

    # Un acompte de 200 : la moitié du reçu, donc la moitié de chaque poste.
    acompte = await record_encaissement_payment(
        db, organisation_id=org.id, encaissement_id=encaissement_id, montant=Decimal("200"),
        mode_paiement="cash", reference=None, notes=None, user_id=user.id,
    )
    await db.commit()
    await db.refresh(cotisations)
    await db.refresh(frais)
    assert Decimal(cotisations.montant_paye) == Decimal("150")
    assert Decimal(frais.montant_paye) == Decimal("50")

    # Le solde : chaque poste atteint exactement le montant de son article.
    # La référence distingue ce second versement du premier — sans elle, le
    # garde-fou anti double-clic y verrait le même paiement rejoué.
    await record_encaissement_payment(
        db, organisation_id=org.id, encaissement_id=encaissement_id, montant=Decimal("200"),
        mode_paiement="cash", reference="Solde", notes=None, user_id=user.id,
    )
    await db.commit()
    await db.refresh(cotisations)
    await db.refresh(frais)
    assert Decimal(cotisations.montant_paye) == Decimal("300")
    assert Decimal(frais.montant_paye) == Decimal("100")

    # L'annulation de l'acompte rend à chaque poste ce que CE versement lui
    # avait apporté — pas le tout à l'un d'eux.
    await cancel_encaissement_payment(
        db, organisation_id=org.id, payment_id=acompte.id, motif_annulation="Erreur de caisse",
        user_id=user.id,
    )
    await db.commit()
    await db.refresh(cotisations)
    await db.refresh(frais)
    assert Decimal(cotisations.montant_paye) == Decimal("150")
    assert Decimal(frais.montant_paye) == Decimal("50")

    imputations = (
        await db.execute(
            select(MouvementBudgetImputation).where(
                MouvementBudgetImputation.organisation_id == org.id,
                MouvementBudgetImputation.statut == "ACTIVE",
            )
        )
    ).scalars().all()
    # Le registre dit la même chose que les postes : deux parts vivantes, une
    # par poste, pour le seul versement qui reste.
    assert sorted(Decimal(str(i.montant_budget)) for i in imputations) == [Decimal("50"), Decimal("150")]


@pytest.mark.asyncio
async def test_un_article_sans_poste_suit_l_encaissement(db_session, monkeypatch):
    """Le cas courant — un seul poste, aucune ligne détaillée — ne bouge pas."""
    from app.api.v1.endpoints.encaissements import create_encaissement
    from app.services.encaissement_payments import record_encaissement_payment

    async def faux_recu(**_kwargs):
        return f"REC-{uuid.uuid4().hex[:8]}"

    monkeypatch.setattr("app.api.v1.endpoints.encaissements._generate_numero_recu", faux_recu)

    db = db_session
    org, user, service, (cotisations, _frais) = await _contexte(db)

    encaissement = await create_encaissement(
        payload=EncaissementCreate(
            type_client="client_externe",
            client_nom="Cabinet ABC",
            libelle="Cotisation annuelle",
            montant=Decimal("120"),
            montant_total=Decimal("120"),
            montant_paye=Decimal("0"),
            mode_paiement="cash",
            canal="CAISSE",
            service_id=service.id,
            budget_poste_id=cotisations.id,
        ),
        background_tasks=BackgroundTasks(),
        user=user,
        tenant_id=org.id,
        db=db,
    )
    await db.commit()

    await record_encaissement_payment(
        db, organisation_id=org.id, encaissement_id=uuid.UUID(str(encaissement["id"])),
        montant=Decimal("120"), mode_paiement="cash", reference=None, notes=None, user_id=user.id,
    )
    await db.commit()
    await db.refresh(cotisations)
    assert Decimal(cotisations.montant_paye) == Decimal("120")
