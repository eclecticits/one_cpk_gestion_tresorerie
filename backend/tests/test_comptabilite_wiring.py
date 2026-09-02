"""Tests du branchement réel du moteur de génération comptable sur les
endpoints métier (encaissements, sorties_fonds) — Lot 2, décision actée :
« Auto-mapper avant de brancher ».

Couvre :
- Organisation SANS comptabilité activée : la saisie de trésorerie n'est
  jamais affectée (aucune écriture tentée, aucune exception).
- Organisation AVEC comptabilité activée + mappée : une écriture est
  générée dans la MÊME transaction que l'opération métier (cas simple,
  transfert interne, multi-postes, encaissement).
- Mapping manquant : échec bloquant, ET atomicité — l'opération métier
  entière est annulée (pas de sortie orpheline sans écriture).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.organisation import Organisation
from app.models.organisation_settings import OrganisationSettings
from app.models.payment_history import PaymentHistory
from app.models.requisition import Requisition
from app.models.ligne_requisition import LigneRequisition
from app.models.service import Service
from app.models.user import User
from app.modules.comptabilite.models import ComptaEcriture
from app.modules.comptabilite.services.mapping_defaut_service import generer_mappings_par_defaut
from app.modules.comptabilite.services.setup_service import setup_comptabilite
from app.schemas.payment import EncaissementCreate
from app.schemas.sortie_fonds import SortieFondsCreate


class _FakeRequest:
    headers: dict = {}
    client = None


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


async def _org(db) -> Organisation:
    org = Organisation(nom="Wiring Test", slug=f"wiring-{_suffix()}", is_active=True)
    db.add(org)
    await db.flush()
    return org


async def _depense_poste(db, org, montant_prevu=100000) -> BudgetPoste:
    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
    db.add(exercice)
    await db.flush()
    poste = BudgetPoste(
        organisation_id=org.id, exercice_id=exercice.id, code=f"DEP-{_suffix()}",
        libelle="Poste dépense", type="DEPENSE", active=True,
        montant_prevu=montant_prevu, montant_engage=0, montant_paye=0, is_deleted=False,
    )
    db.add(poste)
    await db.flush()
    return poste, exercice


async def _recette_poste(db, org, exercice, montant_prevu=100000) -> BudgetPoste:
    poste = BudgetPoste(
        organisation_id=org.id, exercice_id=exercice.id, code=f"REC-{_suffix()}",
        libelle="Poste recette", type="RECETTE", active=True,
        montant_prevu=montant_prevu, montant_engage=0, montant_paye=0, is_deleted=False,
    )
    db.add(poste)
    await db.flush()
    return poste


async def _service(db, org) -> Service:
    service = Service(organisation_id=org.id, code=f"S{_suffix()[:4]}", libelle="Service", is_active=True)
    db.add(service)
    await db.flush()
    return service


async def _caisse(db, org, *, usd=Decimal("0")) -> CaisseCentrale:
    caisse = CaisseCentrale(organisation_id=org.id, solde_usd=usd, solde_cdf=Decimal("0"), est_ouverte=True)
    db.add(caisse)
    await db.flush()
    return caisse


async def _banque(db, org, *, solde=Decimal("0"), devise="USD") -> CompteBancaire:
    compte = CompteBancaire(
        organisation_id=org.id, intitule="Compte banque", numero_compte=f"TEST-{_suffix()}",
        devise=devise, solde_initial=solde, solde_actuel=solde, is_active=True, account_type="BANK",
    )
    db.add(compte)
    await db.flush()
    return compte


async def _admin(db, org) -> User:
    user = User(id=uuid.uuid4(), email=f"a{_suffix()}@ex.com", role="admin", organisation_id=org.id)
    db.add(user)
    await db.flush()
    return user


async def _activer_comptabilite(db, org, *, mapper: bool = True) -> None:
    settings = (
        await db.execute(
            select(OrganisationSettings).where(OrganisationSettings.organisation_id == org.id)
        )
    ).scalar_one_or_none()
    if settings is None:
        settings = OrganisationSettings(
            organisation_id=org.id,
            accounting_integration_mode="automatic",
        )
        db.add(settings)
    else:
        settings.accounting_integration_mode = "automatic"
    await setup_comptabilite(
        db, organisation_id=org.id, organisation_nom=org.nom, type_referentiel="SYSCEBNL",
        exercice_date_debut=date(2026, 1, 1), exercice_date_fin=date(2026, 12, 31),
    )
    if mapper:
        await generer_mappings_par_defaut(db, organisation_id=org.id)
    await db.flush()


async def _ecriture_pour(db, module_origine: str, type_origine: str, objet_origine_id: str) -> ComptaEcriture | None:
    res = await db.execute(
        select(ComptaEcriture)
        .options(selectinload(ComptaEcriture.lignes))
        .where(
            ComptaEcriture.module_origine == module_origine,
            ComptaEcriture.type_origine == type_origine,
            ComptaEcriture.objet_origine_id == objet_origine_id,
        )
    )
    return res.scalar_one_or_none()


# ── Sortie de fonds ────────────────────────────────────────────────────────


async def _requisition_source(db, org, *, poste, service, montant=Decimal("120")):
    """Source autorisée d'une sortie : la caisse n'ouvre plus de mouvement seule."""
    req = Requisition(
        organisation_id=org.id,
        service_id=service.id,
        numero_requisition=f"REQ-{_suffix()}",
        objet="Source de test",
        mode_paiement="cash",
        type_requisition="classique",
        status="APPROUVEE",
        montant_total=montant,
        devise="USD",
    )
    db.add(req)
    await db.flush()
    db.add(LigneRequisition(
        organisation_id=org.id,
        requisition_id=req.id,
        budget_poste_id=poste.id,
        rubrique="Poste dépense",
        description="Ligne test",
        quantite=1,
        montant_unitaire=montant,
        montant_total=montant,
        devise="USD",
    ))
    await db.flush()
    return req

@pytest.mark.asyncio
async def test_sortie_sans_comptabilite_active_ne_genere_rien(db_session, monkeypatch):
    """Le cas le plus important : la quasi-totalité des organisations n'ont
    PAS activé la comptabilité — leur saisie de trésorerie ne doit jamais
    être affectée par ce branchement."""
    db = db_session
    org = await _org(db)
    poste, _ = await _depense_poste(db, org)
    service = await _service(db, org)
    caisse = await _caisse(db, org, usd=Decimal("500"))
    await db.commit()
    user = await _admin(db, org)

    async def fake_num(*a, **k):
        return f"PAY-{_suffix()}"

    monkeypatch.setattr("app.api.v1.endpoints.sorties_fonds.generate_document_number", fake_num)

    from app.api.v1.endpoints.sorties_fonds import create_sortie_fonds

    req = await _requisition_source(db, org, poste=poste, service=service, montant=Decimal("120"))
    payload = SortieFondsCreate(
        type_sortie="autre", requisition_id=req.id, montant_paye=Decimal("120"), mode_paiement="cash",
        devise="USD", canal="CAISSE", motif="Sans compta", beneficiaire="Fournisseur",
        service_id=service.id, budget_poste_id=poste.id,
    )
    sortie = await create_sortie_fonds(
        payload=payload,
        request=_FakeRequest(),
        background_tasks=BackgroundTasks(),
        user=user,
        tenant_id=org.id,
        db=db,
    )

    ecriture = await _ecriture_pour(db, "sorties_fonds", "sortie_fonds", str(sortie.id))
    assert ecriture is None
    await db.refresh(caisse)
    assert Decimal(str(caisse.solde_usd)) == Decimal("380")


@pytest.mark.asyncio
async def test_sortie_simple_genere_ecriture_si_comptabilite_active(db_session, monkeypatch):
    db = db_session
    org = await _org(db)
    poste, _ = await _depense_poste(db, org)
    service = await _service(db, org)
    caisse = await _caisse(db, org, usd=Decimal("500"))
    await _activer_comptabilite(db, org)
    await db.commit()
    user = await _admin(db, org)

    async def fake_num(*a, **k):
        return f"PAY-{_suffix()}"

    monkeypatch.setattr("app.api.v1.endpoints.sorties_fonds.generate_document_number", fake_num)

    from app.api.v1.endpoints.sorties_fonds import create_sortie_fonds

    req = await _requisition_source(db, org, poste=poste, service=service, montant=Decimal("120"))
    payload = SortieFondsCreate(
        type_sortie="autre", requisition_id=req.id, montant_paye=Decimal("120"), mode_paiement="cash",
        devise="USD", canal="CAISSE", motif="Achat fournitures", beneficiaire="Fournisseur",
        service_id=service.id, budget_poste_id=poste.id,
    )
    sortie = await create_sortie_fonds(
        payload=payload,
        request=_FakeRequest(),
        background_tasks=BackgroundTasks(),
        user=user,
        tenant_id=org.id,
        db=db,
    )

    ecriture = await _ecriture_pour(db, "sorties_fonds", "sortie_fonds", str(sortie.id))
    assert ecriture is not None
    assert ecriture.statut == "BROUILLON"
    total_debit = sum((l.debit for l in ecriture.lignes), Decimal("0"))
    total_credit = sum((l.credit for l in ecriture.lignes), Decimal("0"))
    assert total_debit == total_credit == Decimal("120")


@pytest.mark.asyncio
async def test_sortie_bloque_si_mapping_manquant_et_transaction_annulee(db_session, monkeypatch):
    """Comptabilité activée mais mapping non fait (organisation n'ayant pas
    encore été couverte par le backfill) : échec bloquant, ET la sortie de
    fonds entière est annulée (pas de sortie sans écriture)."""
    db = db_session
    org = await _org(db)
    poste, _ = await _depense_poste(db, org)
    poste_id = poste.id
    service = await _service(db, org)
    caisse = await _caisse(db, org, usd=Decimal("500"))
    await _activer_comptabilite(db, org, mapper=False)
    await db.commit()
    user = await _admin(db, org)

    async def fake_num(*a, **k):
        return f"PAY-{_suffix()}"

    monkeypatch.setattr("app.api.v1.endpoints.sorties_fonds.generate_document_number", fake_num)

    from app.api.v1.endpoints.sorties_fonds import create_sortie_fonds

    req = await _requisition_source(db, org, poste=poste, service=service, montant=Decimal("120"))
    payload = SortieFondsCreate(
        type_sortie="autre", requisition_id=req.id, montant_paye=Decimal("120"), mode_paiement="cash",
        devise="USD", canal="CAISSE", motif="Achat fournitures", beneficiaire="Fournisseur",
        service_id=service.id, budget_poste_id=poste_id,
    )
    with pytest.raises(HTTPException) as exc:
        await create_sortie_fonds(
            payload=payload,
            request=_FakeRequest(),
            background_tasks=BackgroundTasks(),
            user=user,
            tenant_id=org.id,
            db=db,
        )
    assert exc.value.status_code == 400

    await db.rollback()
    await db.refresh(caisse)
    assert Decimal(str(caisse.solde_usd)) == Decimal("500")  # inchangé : transaction annulée
    res = await db.execute(select(BudgetPoste).where(BudgetPoste.id == poste_id))
    assert Decimal(str(res.scalar_one().montant_paye or 0)) == Decimal("0")


@pytest.mark.asyncio
async def test_versement_banque_genere_ecriture_transfert_interne(db_session, monkeypatch):
    db = db_session
    org = await _org(db)
    caisse = await _caisse(db, org, usd=Decimal("1000"))
    banque = await _banque(db, org, solde=Decimal("200"))
    await _activer_comptabilite(db, org)
    await db.commit()
    user = await _admin(db, org)

    async def fake_num(*a, **k):
        return f"PAY-{_suffix()}"

    monkeypatch.setattr("app.api.v1.endpoints.sorties_fonds.generate_document_number", fake_num)

    from app.api.v1.endpoints.sorties_fonds import create_sortie_fonds

    payload = SortieFondsCreate(
        type_sortie="versement_banque", montant_paye=Decimal("300"), mode_paiement="cash",
        devise="USD", canal="CAISSE", compte_bancaire_id=banque.id,
        motif="Dépôt banque", beneficiaire="Banque",
    )
    sortie = await create_sortie_fonds(
        payload=payload,
        request=_FakeRequest(),
        background_tasks=BackgroundTasks(),
        user=user,
        tenant_id=org.id,
        db=db,
    )

    ecriture = await _ecriture_pour(db, "sorties_fonds", "transfert_interne", str(sortie.id))
    assert ecriture is not None
    from app.modules.comptabilite.models import ComptaJournal
    journal = await db.get(ComptaJournal, ecriture.journal_id)
    assert journal.code == "OD"
    total_debit = sum((l.debit for l in ecriture.lignes), Decimal("0"))
    assert total_debit == Decimal("300")


@pytest.mark.asyncio
async def test_decaissement_progressif_multi_postes_genere_ecriture_multi_lignes(db_session, monkeypatch):
    db = db_session
    org = await _org(db)
    poste_a, exercice = await _depense_poste(db, org, montant_prevu=100000)
    poste_b = BudgetPoste(
        organisation_id=org.id, exercice_id=exercice.id, code=f"DEP-{_suffix()}",
        libelle="Poste dépense B", type="DEPENSE", active=True,
        montant_prevu=100000, montant_engage=0, montant_paye=0, is_deleted=False,
    )
    db.add(poste_b)
    await db.flush()
    service = await _service(db, org)
    caisse = await _caisse(db, org, usd=Decimal("2000"))
    user = await _admin(db, org)
    await _activer_comptabilite(db, org)
    req = Requisition(
        organisation_id=org.id, service_id=service.id,
        numero_requisition=f"REQ-{_suffix()}", reference_numero=f"REF-{_suffix()}",
        objet="Progressif multi-postes", mode_paiement="cash", type_requisition="classique",
        status="APPROUVEE", montant_total=Decimal("1000"), devise="USD",
        decaissement_progressif=True, created_by=user.id,
    )
    db.add(req)
    await db.flush()
    for poste, montant in ((poste_a, "600"), (poste_b, "400")):
        db.add(LigneRequisition(
            organisation_id=org.id, requisition_id=req.id, budget_poste_id=poste.id,
            rubrique="R", description="R", quantite=1,
            montant_unitaire=Decimal(montant), montant_total=Decimal(montant), devise="USD",
        ))
    await db.commit()
    req_id, poste_a_id, poste_b_id, service_id = req.id, poste_a.id, poste_b.id, service.id

    async def fake_num(*a, **k):
        return f"DOC-{_suffix()}"

    monkeypatch.setattr("app.api.v1.endpoints.ordres_decaissement.generate_document_number", fake_num)
    monkeypatch.setattr("app.api.v1.endpoints.sorties_fonds.generate_document_number", fake_num)

    async def fake_perm(*a, **k):
        return True

    monkeypatch.setattr("app.api.v1.endpoints.ordres_decaissement._user_has_permission", fake_perm)

    from app.models.ordre_decaissement import OrdreDecaissement
    from app.api.v1.endpoints.ordres_decaissement import create_ordre_decaissement
    from app.api.v1.endpoints.sorties_fonds import create_sortie_fonds
    from app.schemas.ordre_decaissement import OrdreDecaissementCreate

    await create_ordre_decaissement(
        payload=OrdreDecaissementCreate(
            requisition_id=req_id, beneficiaire="Bénéf", montant=Decimal("500"), devise="USD",
            lignes=[
                {"budget_poste_id": poste_a_id, "montant": Decimal("300")},
                {"budget_poste_id": poste_b_id, "montant": Decimal("200")},
            ],
        ),
        request=_FakeRequest(), user=user, tenant_id=org.id, db=db,
    )
    ordre = (await db.execute(
        select(OrdreDecaissement).where(OrdreDecaissement.requisition_id == req_id)
    )).scalar_one()

    payload = SortieFondsCreate(
        type_sortie="requisition", requisition_id=req_id, ordre_decaissement_id=ordre.id,
        montant_paye=Decimal("500"), mode_paiement="cash", devise="USD", canal="CAISSE",
        motif="Tranche répartie", beneficiaire="Bénéf", service_id=service_id,
    )
    sortie = await create_sortie_fonds(
        payload=payload,
        request=_FakeRequest(),
        background_tasks=BackgroundTasks(),
        user=user,
        tenant_id=org.id,
        db=db,
    )

    ecriture = await _ecriture_pour(db, "sorties_fonds", "sortie_fonds", str(sortie.id))
    assert ecriture is not None
    assert len(ecriture.lignes) == 3  # 2 débits (postes) + 1 crédit (caisse)
    total_debit = sum((l.debit for l in ecriture.lignes), Decimal("0"))
    total_credit = sum((l.credit for l in ecriture.lignes), Decimal("0"))
    assert total_debit == total_credit == Decimal("500")


# ── Encaissement ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_encaissement_simple_genere_ecriture_si_comptabilite_active(db_session, monkeypatch):
    db = db_session
    org = await _org(db)
    _, exercice = await _depense_poste(db, org)
    poste_recette = await _recette_poste(db, org, exercice)
    caisse = await _caisse(db, org, usd=Decimal("0"))
    await _activer_comptabilite(db, org)
    await db.commit()
    user = await _admin(db, org)

    async def fake_recu(*a, **k):
        return f"REC-{_suffix()}"

    monkeypatch.setattr("app.api.v1.endpoints.encaissements._generate_numero_recu", fake_recu)

    async def fake_schedule(*a, **k):
        return None

    monkeypatch.setattr("app.api.v1.endpoints.encaissements.schedule_client_payment_email", fake_schedule)

    from app.api.v1.endpoints.encaissements import create_encaissement

    payload = EncaissementCreate(
        type_client="client_externe", client_nom="Client Test", libelle="Cotisation",
        montant=Decimal("300"), montant_total=Decimal("300"), montant_paye=Decimal("300"),
        montant_percu=Decimal("300"), devise_perception="USD", mode_paiement="cash",
        canal="CAISSE", budget_poste_id=poste_recette.id,
    )
    result = await create_encaissement(
        payload=payload, background_tasks=BackgroundTasks(), user=user, tenant_id=org.id, db=db,
    )
    encaissement_id = str(result["id"])

    payment = (
        await db.execute(
            select(PaymentHistory).where(PaymentHistory.encaissement_id == uuid.UUID(encaissement_id))
        )
    ).scalar_one()
    ecriture = await _ecriture_pour(db, "encaissements", "payment_history", str(payment.id))
    assert ecriture is not None
    total_debit = sum((l.debit for l in ecriture.lignes), Decimal("0"))
    total_credit = sum((l.credit for l in ecriture.lignes), Decimal("0"))
    assert total_debit == total_credit == Decimal("300")
    await db.refresh(caisse)
    assert Decimal(str(caisse.solde_usd)) == Decimal("300")
