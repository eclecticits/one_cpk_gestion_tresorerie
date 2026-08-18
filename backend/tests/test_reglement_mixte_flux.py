"""Invariants du règlement mixte, de la saisie à l'autorisation.

Une réquisition dont les lignes ne partagent pas le même couple (mode de
paiement, compte bancaire) se règle en plusieurs volets. Ce fichier fixe les
trois garanties que le reste de la chaîne suppose acquises :

- le mode porté par la réquisition n'est qu'un résumé de ses lignes ;
- un règlement en plusieurs volets impose le décaissement progressif ;
- chaque volet est une enveloppe autonome : une tranche caisse ne peut pas
  consommer ce qui est destiné à la banque, même si le plafond global le
  permettrait.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.ordres_decaissement import create_ordre_decaissement
from app.models.banque import Banque
from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.organisation import Organisation
from app.models.service import Service
from app.models.service_rubrique import ServiceRubrique
from app.models.user import User
from app.schemas.ordre_decaissement import OrdreDecaissementCreate
from app.schemas.requisition import LigneRequisitionInline, RequisitionCreate
from app.services.reglement import MODE_PAIEMENT_MIXTE
from app.services.requisition_service import create_requisition_logic


async def _setup(db_session):
    """Organisation minimale : un service, deux postes budgétaires autorisés et
    deux comptes bancaires distincts (pour tester les volets multi-comptes)."""
    org = Organisation(nom="Mixte Test", slug=f"mix-{uuid.uuid4().hex[:8]}", is_active=True)
    db_session.add(org)
    await db_session.flush()

    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
    db_session.add(exercice)
    await db_session.flush()

    postes = []
    for suffix in ("A", "B"):
        poste = BudgetPoste(
            organisation_id=org.id,
            exercice_id=exercice.id,
            code=f"DEP-MIX-{suffix}-{uuid.uuid4().hex[:4]}",
            libelle=f"Poste {suffix}",
            type="DEPENSE",
            active=True,
            montant_prevu=Decimal("100000"),
            montant_engage=0,
            montant_paye=0,
            is_deleted=False,
        )
        db_session.add(poste)
        postes.append(poste)

    service = Service(
        organisation_id=org.id, code=f"S{uuid.uuid4().hex[:4]}", libelle="Service test", is_active=True
    )
    banque = Banque(organisation_id=org.id, nom=f"Banque {uuid.uuid4().hex[:4]}", is_active=True)
    db_session.add_all([service, banque])
    db_session.add(CaisseCentrale(organisation_id=org.id, est_ouverte=True, solde_usd=Decimal("5000"), solde_cdf=0))
    await db_session.flush()

    comptes = []
    for idx in range(2):
        compte = CompteBancaire(
            organisation_id=org.id,
            banque_id=banque.id,
            intitule=f"Compte {idx}",
            numero_compte=f"{uuid.uuid4().hex[:10]}",
            devise="USD",
            solde_initial=Decimal("10000"),
            solde_actuel=Decimal("10000"),
            is_active=True,
            account_type="BANK",
        )
        db_session.add(compte)
        comptes.append(compte)
    await db_session.flush()

    for poste in postes:
        db_session.add(
            ServiceRubrique(service_id=service.id, budget_poste_id=poste.id, active=True)
        )

    user = User(
        id=uuid.uuid4(),
        email=f"mix-{uuid.uuid4().hex[:6]}@example.com",
        role="admin",
        organisation_id=org.id,
    )
    db_session.add(user)
    await db_session.commit()
    return org, user, service, postes, comptes


def _ligne(poste, montant, *, mode=None, compte=None):
    return LigneRequisitionInline(
        budget_poste_id=poste.id,
        rubrique=poste.code,
        description=f"Dépense {poste.code}",
        quantite=1,
        montant_unitaire=Decimal(str(montant)),
        montant_total=Decimal(str(montant)),
        devise="USD",
        mode_paiement=mode,
        compte_bancaire_id=compte,
    )


async def _creer_requisition(db_session, org, user, service, lignes, *, mode="cash", compte=None):
    payload = RequisitionCreate(
        objet="Achat mixte de fournitures",
        mode_paiement=mode,
        type_requisition="classique",
        montant_total=sum((l.montant_total for l in lignes), Decimal("0")),
        devise="USD",
        service_id=service.id,
        compte_bancaire_id=compte,
        created_by=user.id,
        lignes=lignes,
    )
    return await create_requisition_logic(
        db=db_session, payload=payload, user=user, tenant_id=org.id
    )


@pytest.mark.asyncio
async def test_lignes_homogenes_ne_forcent_pas_le_decaissement_progressif(db_session):
    """Le cas courant ne doit rien changer : une réquisition mono-mode garde son
    mode et son circuit de paiement direct."""
    org, user, service, postes, _comptes = await _setup(db_session)

    req = await _creer_requisition(
        db_session,
        org,
        user,
        service,
        [_ligne(postes[0], "100"), _ligne(postes[1], "50")],
        mode="cash",
    )

    assert req.mode_paiement == "cash"
    assert req.decaissement_progressif is False


@pytest.mark.asyncio
async def test_modes_differents_rendent_la_requisition_mixte_et_progressive(db_session):
    org, user, service, postes, comptes = await _setup(db_session)

    req = await _creer_requisition(
        db_session,
        org,
        user,
        service,
        [
            _ligne(postes[0], "100", mode="cash"),
            _ligne(postes[1], "250", mode="virement", compte=comptes[0].id),
        ],
        mode="cash",
    )

    assert req.mode_paiement == MODE_PAIEMENT_MIXTE
    # Deux volets ne peuvent pas être soldés par un paiement unique.
    assert req.decaissement_progressif is True
    # Aucun compte au niveau de la pièce : il est porté par chaque volet.
    assert req.compte_bancaire_id is None


@pytest.mark.asyncio
async def test_deux_comptes_bancaires_forcent_le_progressif_sans_rendre_mixte(db_session):
    org, user, service, postes, comptes = await _setup(db_session)

    req = await _creer_requisition(
        db_session,
        org,
        user,
        service,
        [
            _ligne(postes[0], "100", mode="virement", compte=comptes[0].id),
            _ligne(postes[1], "250", mode="virement", compte=comptes[1].id),
        ],
        mode="virement",
        compte=comptes[0].id,
    )

    assert req.mode_paiement == "virement"
    assert req.decaissement_progressif is True


@pytest.mark.asyncio
async def test_ordre_sur_requisition_mixte_exige_un_volet_explicite(db_session):
    org, user, service, postes, comptes = await _setup(db_session)
    req = await _creer_requisition(
        db_session,
        org,
        user,
        service,
        [
            _ligne(postes[0], "100", mode="cash"),
            _ligne(postes[1], "250", mode="virement", compte=comptes[0].id),
        ],
    )
    req.status = "APPROUVEE"
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await create_ordre_decaissement(
            payload=OrdreDecaissementCreate(
                requisition_id=req.id,
                beneficiaire="Fournisseur",
                montant=Decimal("100"),
                devise="USD",
                lignes=[{"budget_poste_id": postes[0].id, "montant": 100}],
            ),
            request=None,
            user=user,
            tenant_id=org.id,
            db=db_session,
        )

    assert exc.value.status_code == 400
    assert "mixte" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_une_tranche_ne_peut_pas_deborder_sur_l_enveloppe_de_l_autre_volet(db_session):
    """Le plafond global autoriserait 350 ; le volet caisse n'en couvre que 100."""
    org, user, service, postes, comptes = await _setup(db_session)
    req = await _creer_requisition(
        db_session,
        org,
        user,
        service,
        [
            _ligne(postes[0], "100", mode="cash"),
            _ligne(postes[1], "250", mode="virement", compte=comptes[0].id),
        ],
    )
    req.status = "APPROUVEE"
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await create_ordre_decaissement(
            payload=OrdreDecaissementCreate(
                requisition_id=req.id,
                beneficiaire="Fournisseur",
                montant=Decimal("150"),
                devise="USD",
                mode_paiement="cash",
                lignes=[{"budget_poste_id": postes[0].id, "montant": 150}],
            ),
            request=None,
            user=user,
            tenant_id=org.id,
            db=db_session,
        )

    assert exc.value.status_code == 400
    assert "volet" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_chaque_volet_donne_un_ordre_autonome(db_session):
    org, user, service, postes, comptes = await _setup(db_session)
    req = await _creer_requisition(
        db_session,
        org,
        user,
        service,
        [
            _ligne(postes[0], "100", mode="cash"),
            _ligne(postes[1], "250", mode="virement", compte=comptes[0].id),
        ],
    )
    req.status = "APPROUVEE"
    await db_session.commit()

    ordre_caisse = await create_ordre_decaissement(
        payload=OrdreDecaissementCreate(
            requisition_id=req.id,
            beneficiaire="Fournisseur",
            montant=Decimal("100"),
            devise="USD",
            mode_paiement="cash",
            lignes=[{"budget_poste_id": postes[0].id, "montant": 100}],
        ),
        request=None,
        user=user,
        tenant_id=org.id,
        db=db_session,
    )
    ordre_banque = await create_ordre_decaissement(
        payload=OrdreDecaissementCreate(
            requisition_id=req.id,
            beneficiaire="Fournisseur",
            montant=Decimal("250"),
            devise="USD",
            mode_paiement="virement",
            compte_bancaire_id=comptes[0].id,
            lignes=[{"budget_poste_id": postes[1].id, "montant": 250}],
        ),
        request=None,
        user=user,
        tenant_id=org.id,
        db=db_session,
    )

    assert ordre_caisse["canal"] == "CAISSE"
    assert ordre_caisse["compte_bancaire_id"] is None
    assert ordre_banque["canal"] == "BANQUE"
    assert ordre_banque["compte_bancaire_id"] == comptes[0].id
    # Deux ordres distincts, chacun payable sans attendre l'autre.
    assert ordre_caisse["id"] != ordre_banque["id"]
