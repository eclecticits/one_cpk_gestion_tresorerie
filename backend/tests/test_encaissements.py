import asyncio
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete, select
from fastapi import BackgroundTasks, HTTPException

from app.api.v1.endpoints.encaissements import (
    cancel_encaissement_operation,
    create_encaissement,
    list_encaissements,
    restore_encaissement,
    soft_delete_encaissement,
)
from app.api.v1.endpoints.payments import create_payment
from app.core.audit_context import set_audit_org_id, set_audit_user_id
from app.models.audit_log import AuditLog
from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.encaissement import Encaissement
from app.models.expert_comptable import ExpertComptable
from app.models.organisation import Organisation
from app.models.organisation_settings import OrganisationSettings
from app.models.payment_history import PaymentHistory
from app.models.user import User
from app.modules.comptabilite.models import (
    ComptaEcriture,
    ComptaExercice,
    ComptaJournal,
    ComptaReferentiel,
    ComptaSociete,
)
from app.schemas.payment import EncaissementCancelPayload, EncaissementCreate, PaymentHistoryCreate
from app.services.encaissement_payments import cancel_encaissement_payment, record_encaissement_payment


class _FakeRequest:
    headers: dict = {}
    client = None


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


async def _enc_org(db_session, *, name: str = "Encaissement Integrity") -> Organisation:
    org = Organisation(nom=name, slug=f"enc-int-{_suffix()}", is_active=True)
    db_session.add(org)
    await db_session.flush()
    return org


async def _enc_user(db_session, org: Organisation) -> User:
    user = User(id=uuid.uuid4(), email=f"user-{_suffix()}@example.com", role="admin", organisation_id=org.id)
    db_session.add(user)
    await db_session.flush()
    return user


async def _enc_budget_poste(db_session, org: Organisation, *, paid=Decimal("0")) -> BudgetPoste:
    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
    db_session.add(exercice)
    await db_session.flush()
    poste = BudgetPoste(
        organisation_id=org.id,
        exercice_id=exercice.id,
        code=f"REC-{_suffix()}",
        libelle="Poste recette",
        type="RECETTE",
        active=True,
        montant_prevu=Decimal("10000"),
        montant_engage=Decimal("0"),
        montant_paye=paid,
        is_deleted=False,
    )
    db_session.add(poste)
    await db_session.flush()
    return poste


async def _encaissement_row(
    db_session,
    org: Organisation,
    user: User,
    *,
    poste: BudgetPoste | None = None,
    montant_paye=Decimal("0"),
    est_proforma: bool = False,
    is_deleted: bool = False,
    canal: str = "CAISSE",
    devise: str = "USD",
    compte_bancaire_id: int | None = None,
) -> Encaissement:
    enc = Encaissement(
        numero_recu=None if est_proforma else f"ND-{_suffix()}",
        numero_proforma=f"PF-{_suffix()}" if est_proforma else None,
        est_proforma=est_proforma,
        organisation_id=org.id,
        type_client="client_externe",
        client_nom="Client intégrité",
        libelle="Encaissement intégrité",
        montant=Decimal("500"),
        montant_total=Decimal("500"),
        montant_paye=Decimal(str(montant_paye)),
        montant_percu=Decimal(str(montant_paye)),
        devise_perception=devise,
        taux_change_applique=Decimal("1"),
        canal=canal,
        compte_bancaire_id=compte_bancaire_id,
        budget_poste_id=poste.id if poste else None,
        statut_paiement="complet" if Decimal(str(montant_paye)) >= Decimal("500") else "non_paye",
        mode_paiement="cash",
        date_encaissement=datetime(2026, 1, 27, tzinfo=timezone.utc),
        date_paiement=datetime(2026, 1, 27, tzinfo=timezone.utc) if Decimal(str(montant_paye)) > 0 else None,
        created_by=user.id,
        is_deleted=is_deleted,
        deleted_at=datetime.now(timezone.utc) if is_deleted else None,
        deleted_by=user.id if is_deleted else None,
    )
    db_session.add(enc)
    await db_session.flush()
    return enc


async def _audit_count(db_session, encaissement_id: uuid.UUID, action: str) -> int:
    res = await db_session.execute(
        select(AuditLog).where(
            AuditLog.entity_type == "encaissements",
            AuditLog.entity_id == str(encaissement_id),
            AuditLog.action == action,
        )
    )
    return len(res.scalars().all())


async def _prepare_audit_context(org: Organisation, user: User) -> None:
    set_audit_org_id(org.id)
    set_audit_user_id(user.id)


async def _minimal_compta_ecriture(db_session, org: Organisation, enc: Encaissement) -> ComptaEcriture:
    societe = ComptaSociete(organisation_id=org.id, code=f"SOC-{_suffix()}", raison_sociale=org.nom, is_default=True)
    db_session.add(societe)
    await db_session.flush()
    referentiel = ComptaReferentiel(
        organisation_id=org.id,
        code=f"REF-{_suffix()}",
        libelle="Référentiel test",
        type_referentiel="SYSCEBNL",
        is_default=True,
    )
    db_session.add(referentiel)
    await db_session.flush()
    exercice = ComptaExercice(
        organisation_id=org.id,
        societe_id=societe.id,
        code=f"EX-{_suffix()}",
        date_debut=date(2026, 1, 1),
        date_fin=date(2026, 12, 31),
        referentiel_id=referentiel.id,
        statut="OUVERT",
    )
    journal = ComptaJournal(
        organisation_id=org.id,
        societe_id=societe.id,
        code=f"J{_suffix()[:4]}",
        libelle="Journal test",
        type_journal="CA",
    )
    db_session.add_all([exercice, journal])
    await db_session.flush()
    ecriture = ComptaEcriture(
        organisation_id=org.id,
        societe_id=societe.id,
        exercice_id=exercice.id,
        journal_id=journal.id,
        date_ecriture=date(2026, 1, 27),
        libelle="Écriture liée encaissement",
        statut="BROUILLON",
        devise="USD",
        module_origine="encaissements",
        type_origine="encaissement",
        objet_origine_id=str(enc.id),
        est_automatique=True,
    )
    db_session.add(ecriture)
    await db_session.flush()
    return ecriture


async def _fake_payment_ecriture(
    db_session,
    *,
    organisation_id: int,
    encaissement_id: str,
    date_operation,
    montant: Decimal,
    devise: str,
    canal: str,
    compte_bancaire_id: int | None,
    budget_poste_id: int | None,
    libelle: str,
    created_by=None,
    type_origine: str = "encaissement",
    objet_origine_id: str | None = None,
    rubrique_produit_defaut: str | None = None,
) -> ComptaEcriture:
    origin_id = objet_origine_id or encaissement_id
    existing = (
        await db_session.execute(
            select(ComptaEcriture).where(
                ComptaEcriture.organisation_id == organisation_id,
                ComptaEcriture.module_origine == "encaissements",
                ComptaEcriture.type_origine == type_origine,
                ComptaEcriture.objet_origine_id == origin_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    org = await db_session.get(Organisation, organisation_id)
    societe = ComptaSociete(organisation_id=organisation_id, code=f"SOC-{_suffix()}", raison_sociale=org.nom, is_default=True)
    db_session.add(societe)
    await db_session.flush()
    referentiel = ComptaReferentiel(
        organisation_id=organisation_id,
        code=f"REF-{_suffix()}",
        libelle="Référentiel test",
        type_referentiel="SYSCEBNL",
        is_default=True,
    )
    db_session.add(referentiel)
    await db_session.flush()
    exercice = ComptaExercice(
        organisation_id=organisation_id,
        societe_id=societe.id,
        code=f"EX-{_suffix()}",
        date_debut=date(2026, 1, 1),
        date_fin=date(2026, 12, 31),
        referentiel_id=referentiel.id,
        statut="OUVERT",
    )
    journal = ComptaJournal(
        organisation_id=organisation_id,
        societe_id=societe.id,
        code=f"J{_suffix()[:4]}",
        libelle="Journal test",
        type_journal="CA" if canal == "CAISSE" else "BQ",
    )
    db_session.add_all([exercice, journal])
    await db_session.flush()
    ecriture = ComptaEcriture(
        organisation_id=organisation_id,
        societe_id=societe.id,
        exercice_id=exercice.id,
        journal_id=journal.id,
        date_ecriture=date_operation,
        libelle=libelle,
        statut="BROUILLON",
        devise=devise,
        module_origine="encaissements",
        type_origine=type_origine,
        objet_origine_id=origin_id,
        est_automatique=True,
        created_by=created_by,
    )
    db_session.add(ecriture)
    await db_session.flush()
    return ecriture


@pytest.mark.asyncio
async def test_create_and_list_encaissement_with_expert(db_session, monkeypatch):
    await db_session.execute(delete(Encaissement))
    await db_session.execute(delete(ExpertComptable))
    await db_session.commit()

    org = Organisation(nom="Encaissement Test", slug=f"enc-{uuid.uuid4().hex[:8]}", is_active=True)
    db_session.add(org)
    await db_session.flush()
    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
    db_session.add(exercice)
    await db_session.flush()
    poste = BudgetPoste(
        organisation_id=org.id,
        exercice_id=exercice.id,
        code="ENC-001",
        libelle="Poste encaissement",
        type="RECETTE",
        active=True,
        montant_prevu=1000,
        montant_engage=0,
        montant_paye=0,
        is_deleted=False,
    )
    db_session.add(poste)
    await db_session.flush()

    expert_numero = f"EC-{uuid.uuid4().hex[:8]}"
    expert = ExpertComptable(
        numero_ordre=expert_numero,
        nom_denomination="Cabinet Alpha",
        type_ec="EC",
        active=True,
    )
    db_session.add(expert)
    await db_session.commit()
    await db_session.refresh(expert)

    user = User(id=uuid.uuid4(), email="tester@example.com", role="admin", organisation_id=org.id)
    db_session.add(CaisseCentrale(organisation_id=org.id, est_ouverte=True))
    await db_session.flush()

    async def fake_generate_numero_recu(*args, **kwargs):
        return "REC-20260127-0001"

    monkeypatch.setattr("app.api.v1.endpoints.encaissements._generate_numero_recu", fake_generate_numero_recu)

    payload = EncaissementCreate(
        numero_recu="REC-20260127-0001",
        type_client="expert_comptable",
        expert_comptable_id=str(expert.id),
        client_nom=None,
        libelle="Cotisation annuelle",
        description="Test encaissement",
        montant=100,
        montant_total=100,
        montant_paye=100,
        statut_paiement="complet",
        mode_paiement="cash",
        reference="REF-001",
        budget_poste_id=poste.id,
        date_encaissement=datetime(2026, 1, 27, tzinfo=timezone.utc),
    )

    created = await create_encaissement(payload=payload, background_tasks=BackgroundTasks(), user=user, tenant_id=org.id, db=db_session)
    assert created["numero_recu"] == "REC-20260127-0001"
    assert created["expert_comptable"]["numero_ordre"] == expert_numero

    results = await list_encaissements(
        include="expert_comptable",
        date_debut=None,
        date_fin=None,
        statut_paiement=None,
        numero_recu=None,
        client=None,
        budget_poste_id=None,
        type_client=None,
        mode_paiement=None,
        canal=None,
        compte_bancaire_id=None,
        expert_comptable_id=None,
        operation_status="ACTIVE",
        est_proforma=False,
        order=None,
        limit=10,
        offset=0,
        include_summary=False,
        tenant_id=org.id,
        user=user,
        db=db_session,
    )

    assert len(results) == 1
    assert results[0]["expert_comptable"]["nom_denomination"] == "Cabinet Alpha"


@pytest.mark.asyncio
async def test_filters_and_pagination(db_session, monkeypatch):
    await db_session.execute(delete(Encaissement))
    await db_session.execute(delete(ExpertComptable))
    await db_session.commit()

    org = Organisation(nom="Encaissement List", slug=f"enc-list-{uuid.uuid4().hex[:8]}", is_active=True)
    db_session.add(org)
    await db_session.flush()
    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
    db_session.add(exercice)
    await db_session.flush()
    poste = BudgetPoste(
        organisation_id=org.id,
        exercice_id=exercice.id,
        code="ENC-LIST-001",
        libelle="Poste liste",
        type="RECETTE",
        active=True,
        montant_prevu=1000,
        montant_engage=0,
        montant_paye=0,
        is_deleted=False,
    )
    db_session.add(poste)
    await db_session.flush()

    user = User(id=uuid.uuid4(), email="tester2@example.com", role="admin", organisation_id=org.id)

    async def fake_generate_numero_recu(*args, **kwargs):
        return "REC-20260127-0001"

    monkeypatch.setattr("app.api.v1.endpoints.encaissements._generate_numero_recu", fake_generate_numero_recu)

    for idx in range(3):
        enc = Encaissement(
            numero_recu=f"REC-20260127-00{idx+2}",
            organisation_id=org.id,
            type_client="client_externe",
            client_nom=f"Client {idx}",
            libelle=f"Libellé {idx}",
            description=None,
            montant=50,
            montant_total=50,
            montant_paye=25 if idx == 0 else 50,
            statut_paiement="partiel" if idx == 0 else "complet",
            mode_paiement="cash",
            reference=None,
            date_encaissement=datetime(2026, 1, 27, tzinfo=timezone.utc),
            created_by=user.id,
            budget_poste_id=poste.id,
        )
        db_session.add(enc)
    await db_session.commit()

    results = await list_encaissements(
        include=None,
        date_debut=None,
        date_fin=None,
        statut_paiement=None,
        numero_recu=None,
        client=None,
        budget_poste_id=None,
        type_client=None,
        mode_paiement=None,
        canal=None,
        compte_bancaire_id=None,
        expert_comptable_id=None,
        operation_status="ACTIVE",
        est_proforma=False,
        order=None,
        limit=10,
        offset=0,
        include_summary=False,
        tenant_id=org.id,
        user=user,
        db=db_session,
    )
    assert len(results) == 3

    paged = await list_encaissements(
        include=None,
        date_debut=None,
        date_fin=None,
        statut_paiement=None,
        numero_recu=None,
        client=None,
        budget_poste_id=None,
        type_client=None,
        mode_paiement=None,
        canal=None,
        compte_bancaire_id=None,
        expert_comptable_id=None,
        operation_status="ACTIVE",
        est_proforma=False,
        limit=1,
        offset=1,
        order="numero_recu.asc",
        include_summary=False,
        tenant_id=org.id,
        user=user,
        db=db_session,
    )
    assert len(paged) == 1

    filtered = await list_encaissements(
        include=None,
        date_debut=None,
        date_fin=None,
        statut_paiement=None,
        client=None,
        budget_poste_id=None,
        type_client=None,
        mode_paiement=None,
        canal=None,
        compte_bancaire_id=None,
        expert_comptable_id=None,
        operation_status="ACTIVE",
        est_proforma=False,
        order=None,
        numero_recu="REC-20260127-003",
        limit=10,
        offset=0,
        include_summary=False,
        tenant_id=org.id,
        user=user,
        db=db_session,
    )
    assert len(filtered) == 1


@pytest.mark.asyncio
async def test_create_encaissement_retries_on_duplicate_numero(db_session, monkeypatch):
    await db_session.execute(delete(Encaissement))
    await db_session.execute(delete(ExpertComptable))
    await db_session.commit()

    org = Organisation(nom="Encaissement Retry", slug=f"enc-retry-{uuid.uuid4().hex[:8]}", is_active=True)
    db_session.add(org)
    await db_session.flush()
    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
    db_session.add(exercice)
    await db_session.flush()
    poste = BudgetPoste(
        organisation_id=org.id,
        exercice_id=exercice.id,
        code="ENC-RETRY-001",
        libelle="Poste retry",
        type="RECETTE",
        active=True,
        montant_prevu=1000,
        montant_engage=0,
        montant_paye=0,
        is_deleted=False,
    )
    db_session.add(poste)
    await db_session.flush()

    user = User(id=uuid.uuid4(), email="tester3@example.com", role="admin", organisation_id=org.id)
    db_session.add(CaisseCentrale(organisation_id=org.id, est_ouverte=True))
    await db_session.flush()

    existing = Encaissement(
        numero_recu="REC-20260127-0001",
        organisation_id=org.id,
        type_client="client_externe",
        client_nom="Client A",
        libelle="Formation",
        description=None,
        montant=100,
        montant_total=100,
        montant_paye=0,
        statut_paiement="non_paye",
        mode_paiement="cash",
        reference=None,
        date_encaissement=datetime(2026, 1, 27, tzinfo=timezone.utc),
        created_by=user.id,
        budget_poste_id=poste.id,
    )
    db_session.add(existing)
    await db_session.commit()

    attempts = {"count": 0}

    async def fake_generate_numero_recu(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] < 3:
            return "REC-20260127-0001"
        return "REC-20260127-0002"

    monkeypatch.setattr("app.api.v1.endpoints.encaissements._generate_numero_recu", fake_generate_numero_recu)

    payload = EncaissementCreate(
        numero_recu="",
        type_client="client_externe",
        client_nom="Client B",
        libelle="Formation",
        description=None,
        montant=100,
        montant_total=100,
        montant_paye=0,
        statut_paiement="non_paye",
        mode_paiement="cash",
        reference=None,
        budget_poste_id=poste.id,
        date_encaissement=datetime(2026, 1, 27, tzinfo=timezone.utc),
    )

    try:
        created = await create_encaissement(payload=payload, background_tasks=BackgroundTasks(), user=user, tenant_id=org.id, db=db_session)
        assert created["numero_recu"] == "REC-20260127-0002"
    except HTTPException as exc:
        assert exc.status_code == 409


@pytest.mark.asyncio
async def test_encaissement_manual_accounting_mode_accepts_unmapped_poste(db_session, monkeypatch):
    await db_session.execute(delete(ComptaEcriture))
    await db_session.execute(delete(Encaissement))
    await db_session.execute(delete(ExpertComptable))
    await db_session.commit()

    org = Organisation(nom="Encaissement Compta Manuel", slug=f"enc-manual-{uuid.uuid4().hex[:8]}", is_active=True)
    db_session.add(org)
    await db_session.flush()
    db_session.add(OrganisationSettings(organisation_id=org.id, accounting_integration_mode="manual"))
    db_session.add(ComptaSociete(organisation_id=org.id, code="ORG", raison_sociale=org.nom, is_default=True))
    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
    db_session.add(exercice)
    await db_session.flush()
    poste = BudgetPoste(
        organisation_id=org.id,
        exercice_id=exercice.id,
        code="REC-MAN-001",
        libelle="Recette sans mapping",
        type="RECETTE",
        active=True,
        montant_prevu=1000,
        montant_engage=0,
        montant_paye=0,
        is_deleted=False,
    )
    db_session.add(poste)
    db_session.add(CaisseCentrale(organisation_id=org.id, est_ouverte=True))
    await db_session.flush()

    user = User(id=uuid.uuid4(), email="manual@example.com", role="admin", organisation_id=org.id)

    async def fake_generate_numero_recu(*args, **kwargs):
        return "REC-MAN-0001"

    monkeypatch.setattr("app.api.v1.endpoints.encaissements._generate_numero_recu", fake_generate_numero_recu)

    payload = EncaissementCreate(
        numero_recu="",
        type_client="client_externe",
        client_nom="Client manuel",
        libelle="Recette manuelle",
        montant=100,
        montant_total=100,
        montant_paye=100,
        statut_paiement="complet",
        mode_paiement="cash",
        budget_poste_id=poste.id,
        date_encaissement=datetime(2026, 1, 27, tzinfo=timezone.utc),
    )

    created = await create_encaissement(
        payload=payload,
        background_tasks=BackgroundTasks(),
        user=user,
        tenant_id=org.id,
        db=db_session,
    )

    assert created["numero_recu"] == "REC-MAN-0001"
    assert created["statut_comptabilisation"] == "A_COMPTABILISER_MANUELLEMENT"
    ecritures = (await db_session.execute(select(ComptaEcriture).where(ComptaEcriture.organisation_id == org.id))).scalars().all()
    assert ecritures == []


@pytest.mark.asyncio
async def test_payment_initial_uses_payment_history_accounting_origin(db_session, monkeypatch):
    org = await _enc_org(db_session)
    user = await _enc_user(db_session, org)
    poste = await _enc_budget_poste(db_session, org)
    caisse = CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("0"), est_ouverte=True)
    db_session.add(caisse)
    await _prepare_audit_context(org, user)
    await db_session.flush()

    async def fake_numero(*args, **kwargs):
        return f"ND-{_suffix()}"

    async def accounting_automatic(*args, **kwargs):
        return "automatic"

    async def no_email(*args, **kwargs):
        return None

    monkeypatch.setattr("app.api.v1.endpoints.encaissements._generate_numero_recu", fake_numero)
    monkeypatch.setattr("app.services.encaissement_payments.get_accounting_integration_mode", accounting_automatic)
    monkeypatch.setattr("app.services.encaissement_payments.generer_ecriture_encaissement", _fake_payment_ecriture)
    monkeypatch.setattr("app.api.v1.endpoints.encaissements.schedule_client_payment_email", no_email)

    created = await create_encaissement(
        payload=EncaissementCreate(
            type_client="client_externe",
            client_nom="Client initial",
            libelle="Paiement initial",
            montant=Decimal("1000"),
            montant_total=Decimal("1000"),
            montant_paye=Decimal("1000"),
            statut_paiement="complet",
            mode_paiement="cash",
            budget_poste_id=poste.id,
            date_encaissement=datetime(2026, 1, 27, tzinfo=timezone.utc),
        ),
        background_tasks=BackgroundTasks(),
        user=user,
        tenant_id=org.id,
        db=db_session,
    )

    enc_id = uuid.UUID(created["id"])
    payments = (await db_session.execute(select(PaymentHistory).where(PaymentHistory.encaissement_id == enc_id))).scalars().all()
    assert len(payments) == 1
    assert payments[0].statut == "ACTIF"
    assert payments[0].statut_comptabilisation == "COMPTABILISE"
    ecritures = (await db_session.execute(select(ComptaEcriture).where(ComptaEcriture.organisation_id == org.id))).scalars().all()
    assert len(ecritures) == 1
    assert ecritures[0].type_origine == "payment_history"
    assert ecritures[0].objet_origine_id == str(payments[0].id)
    assert Decimal(str(caisse.solde_usd)) == Decimal("1000.00")
    await db_session.refresh(poste)
    assert poste.montant_paye == Decimal("1000.00")


@pytest.mark.asyncio
async def test_fractional_payments_create_one_entry_per_payment_and_partial_cancel(db_session, monkeypatch):
    org = await _enc_org(db_session)
    user = await _enc_user(db_session, org)
    poste = await _enc_budget_poste(db_session, org)
    caisse = CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("0"), est_ouverte=True)
    db_session.add(caisse)
    await _prepare_audit_context(org, user)
    enc = await _encaissement_row(db_session, org, user, poste=poste, montant_paye=Decimal("0"))
    enc.montant = Decimal("1000")
    enc.montant_total = Decimal("1000")
    await db_session.commit()

    async def accounting_automatic(*args, **kwargs):
        return "automatic"

    async def no_email(*args, **kwargs):
        return None

    monkeypatch.setattr("app.services.encaissement_payments.get_accounting_integration_mode", accounting_automatic)
    monkeypatch.setattr("app.services.encaissement_payments.generer_ecriture_encaissement", _fake_payment_ecriture)
    monkeypatch.setattr("app.api.v1.endpoints.payments.schedule_client_payment_email", no_email)

    created_payments = []
    for amount in (Decimal("300"), Decimal("400"), Decimal("300")):
        out = await create_payment(
            payload=PaymentHistoryCreate(encaissement_id=enc.id, montant=amount, mode_paiement="cash"),
            request=_FakeRequest(),
            background_tasks=BackgroundTasks(),
            user=user,
            tenant_id=org.id,
            db=db_session,
        )
        created_payments.append(uuid.UUID(out["id"]))

    await db_session.refresh(enc)
    await db_session.refresh(caisse)
    await db_session.refresh(poste)
    assert enc.montant_paye == Decimal("1000.00")
    assert enc.statut_paiement == "complet"
    assert caisse.solde_usd == Decimal("1000.00")
    assert poste.montant_paye == Decimal("1000.00")
    payments = (await db_session.execute(select(PaymentHistory).where(PaymentHistory.encaissement_id == enc.id))).scalars().all()
    assert len(payments) == 3
    assert {p.statut for p in payments} == {"ACTIF"}
    ecritures = (
        await db_session.execute(
            select(ComptaEcriture).where(
                ComptaEcriture.organisation_id == org.id,
                ComptaEcriture.type_origine == "payment_history",
            )
        )
    ).scalars().all()
    assert len(ecritures) == 3
    assert {e.objet_origine_id for e in ecritures} == {str(pid) for pid in created_payments}

    replay = await _fake_payment_ecriture(
        db_session,
        organisation_id=org.id,
        encaissement_id=str(enc.id),
        date_operation=date(2026, 1, 27),
        montant=Decimal("400"),
        devise="USD",
        canal="CAISSE",
        compte_bancaire_id=None,
        budget_poste_id=poste.id,
        libelle="Replay",
        type_origine="payment_history",
        objet_origine_id=str(created_payments[1]),
    )
    assert replay.objet_origine_id == str(created_payments[1])
    ecritures_after_replay = (
        await db_session.execute(
            select(ComptaEcriture).where(
                ComptaEcriture.organisation_id == org.id,
                ComptaEcriture.type_origine == "payment_history",
            )
        )
    ).scalars().all()
    assert len(ecritures_after_replay) == 3

    await cancel_encaissement_payment(
        db_session,
        organisation_id=org.id,
        payment_id=created_payments[1],
        motif_annulation="Annulation paiement 400",
        user_id=user.id,
    )
    await db_session.commit()
    await db_session.refresh(enc)
    await db_session.refresh(caisse)
    await db_session.refresh(poste)
    cancelled = await db_session.get(PaymentHistory, created_payments[1])
    assert cancelled.statut == "ANNULE"
    assert enc.montant_paye == Decimal("600.00")
    assert enc.statut_paiement == "partiel"
    assert caisse.solde_usd == Decimal("600.00")
    assert poste.montant_paye == Decimal("600.00")


@pytest.mark.asyncio
async def test_total_cancel_neutralizes_all_active_payments_once(db_session, monkeypatch):
    org = await _enc_org(db_session)
    user = await _enc_user(db_session, org)
    poste = await _enc_budget_poste(db_session, org)
    caisse = CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("0"), est_ouverte=True)
    db_session.add(caisse)
    await _prepare_audit_context(org, user)
    enc = await _encaissement_row(db_session, org, user, poste=poste, montant_paye=Decimal("0"))
    enc.montant = Decimal("1000")
    enc.montant_total = Decimal("1000")
    await db_session.commit()

    async def no_email(*args, **kwargs):
        return None

    async def always_allowed(*args, **kwargs):
        return True

    monkeypatch.setattr("app.api.v1.endpoints.payments.schedule_client_payment_email", no_email)
    monkeypatch.setattr("app.api.v1.endpoints.encaissements._user_has_permission", always_allowed)

    for amount in (Decimal("300"), Decimal("400"), Decimal("300")):
        await create_payment(
            payload=PaymentHistoryCreate(encaissement_id=enc.id, montant=amount, mode_paiement="cash"),
            request=_FakeRequest(),
            background_tasks=BackgroundTasks(),
            user=user,
            tenant_id=org.id,
            db=db_session,
        )

    await cancel_encaissement_operation(
        str(enc.id),
        payload=EncaissementCancelPayload(motif_annulation="Annulation totale"),
        request=_FakeRequest(),
        user=user,
        tenant_id=org.id,
        db=db_session,
    )

    await db_session.refresh(enc)
    await db_session.refresh(caisse)
    await db_session.refresh(poste)
    payments = (await db_session.execute(select(PaymentHistory).where(PaymentHistory.encaissement_id == enc.id))).scalars().all()
    assert len(payments) == 3
    assert {p.statut for p in payments} == {"ANNULE"}
    assert enc.statut_operation == "ANNULEE"
    assert enc.montant_paye == Decimal("0.00")
    assert enc.statut_paiement == "non_paye"
    assert caisse.solde_usd == Decimal("0.00")
    assert poste.montant_paye == Decimal("0.00")


@pytest.mark.asyncio
async def test_payment_accounting_failure_rolls_back_all_financial_effects(db_session, monkeypatch):
    org = await _enc_org(db_session)
    user = await _enc_user(db_session, org)
    poste = await _enc_budget_poste(db_session, org)
    caisse = CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("0"), est_ouverte=True)
    db_session.add(caisse)
    await _prepare_audit_context(org, user)
    enc = await _encaissement_row(db_session, org, user, poste=poste, montant_paye=Decimal("0"))
    enc.montant = Decimal("1000")
    enc.montant_total = Decimal("1000")
    await db_session.commit()

    async def accounting_automatic(*args, **kwargs):
        return "automatic"

    async def fail_accounting(*args, **kwargs):
        raise HTTPException(status_code=400, detail="mapping manquant")

    monkeypatch.setattr("app.services.encaissement_payments.get_accounting_integration_mode", accounting_automatic)
    monkeypatch.setattr("app.services.encaissement_payments.generer_ecriture_encaissement", fail_accounting)

    with pytest.raises(HTTPException):
        await create_payment(
            payload=PaymentHistoryCreate(encaissement_id=enc.id, montant=Decimal("300"), mode_paiement="cash"),
            request=_FakeRequest(),
            background_tasks=BackgroundTasks(),
            user=user,
            tenant_id=org.id,
            db=db_session,
        )
    await db_session.rollback()
    await db_session.refresh(enc)
    await db_session.refresh(caisse)
    await db_session.refresh(poste)
    payment_count = (await db_session.execute(select(PaymentHistory).where(PaymentHistory.encaissement_id == enc.id))).scalars().all()
    assert payment_count == []
    assert enc.montant_paye == Decimal("0.00")
    assert caisse.solde_usd == Decimal("0.00")
    assert poste.montant_paye == Decimal("0.00")


@pytest.mark.asyncio
async def test_manual_mode_records_payment_without_auto_entry(db_session, monkeypatch):
    org = await _enc_org(db_session)
    user = await _enc_user(db_session, org)
    poste = await _enc_budget_poste(db_session, org)
    db_session.add(CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("0"), est_ouverte=True))
    await _prepare_audit_context(org, user)
    enc = await _encaissement_row(db_session, org, user, poste=poste, montant_paye=Decimal("0"))
    await db_session.commit()

    async def accounting_manual(*args, **kwargs):
        return "manual"

    monkeypatch.setattr("app.services.encaissement_payments.get_accounting_integration_mode", accounting_manual)

    out = await create_payment(
        payload=PaymentHistoryCreate(encaissement_id=enc.id, montant=Decimal("200"), mode_paiement="cash"),
        request=_FakeRequest(),
        background_tasks=BackgroundTasks(),
        user=user,
        tenant_id=org.id,
        db=db_session,
    )
    payment = await db_session.get(PaymentHistory, uuid.UUID(out["id"]))
    ecritures = (await db_session.execute(select(ComptaEcriture).where(ComptaEcriture.organisation_id == org.id))).scalars().all()
    assert ecritures == []
    assert payment.statut_comptabilisation == "EN_ATTENTE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("canal", "devise"),
    [("CAISSE", "CDF"), ("BANQUE", "USD")],
)
async def test_payment_snapshots_channel_and_currency(db_session, monkeypatch, canal, devise):
    org = await _enc_org(db_session)
    user = await _enc_user(db_session, org)
    poste = await _enc_budget_poste(db_session, org)
    compte_id = None
    if canal == "CAISSE":
        caisse = CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("0"), solde_cdf=Decimal("0"), est_ouverte=True)
        db_session.add(caisse)
    else:
        compte = CompteBancaire(
            organisation_id=org.id,
            intitule="Compte banque",
            numero_compte=f"BK-{_suffix()}",
            devise=devise,
            solde_initial=Decimal("0"),
            solde_actuel=Decimal("0"),
            is_active=True,
            account_type="BANK",
        )
        db_session.add(compte)
        await db_session.flush()
        compte_id = compte.id
    await _prepare_audit_context(org, user)
    enc = await _encaissement_row(
        db_session,
        org,
        user,
        poste=poste,
        montant_paye=Decimal("0"),
        canal=canal,
        devise=devise,
        compte_bancaire_id=compte_id,
    )
    enc.montant = Decimal("500")
    enc.montant_total = Decimal("500")
    await db_session.commit()

    async def no_email(*args, **kwargs):
        return None

    monkeypatch.setattr("app.api.v1.endpoints.payments.schedule_client_payment_email", no_email)

    out = await create_payment(
        payload=PaymentHistoryCreate(encaissement_id=enc.id, montant=Decimal("120"), mode_paiement="cash"),
        request=_FakeRequest(),
        background_tasks=BackgroundTasks(),
        user=user,
        tenant_id=org.id,
        db=db_session,
    )
    payment = await db_session.get(PaymentHistory, uuid.UUID(out["id"]))
    assert payment.devise == devise
    assert payment.canal == canal
    assert payment.budget_poste_id == poste.id
    if canal == "CAISSE":
        await db_session.refresh(caisse)
        assert caisse.solde_cdf == Decimal("120.00")
    else:
        await db_session.refresh(compte)
        assert payment.compte_bancaire_id == compte.id
        assert compte.solde_actuel == Decimal("120.00")


@pytest.mark.asyncio
async def test_payment_is_tenant_isolated(db_session):
    org_a = await _enc_org(db_session, name="Tenant paiement A")
    org_b = await _enc_org(db_session, name="Tenant paiement B")
    user_a = await _enc_user(db_session, org_a)
    user_b = await _enc_user(db_session, org_b)
    poste_b = await _enc_budget_poste(db_session, org_b)
    db_session.add(CaisseCentrale(organisation_id=org_b.id, solde_usd=Decimal("0"), est_ouverte=True))
    enc_b = await _encaissement_row(db_session, org_b, user_b, poste=poste_b, montant_paye=Decimal("0"))
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await create_payment(
            payload=PaymentHistoryCreate(encaissement_id=enc_b.id, montant=Decimal("100"), mode_paiement="cash"),
            request=_FakeRequest(),
            background_tasks=BackgroundTasks(),
            user=user_a,
            tenant_id=org_a.id,
            db=db_session,
        )

    assert exc.value.status_code == 404
    await db_session.rollback()
    await db_session.refresh(enc_b)
    await db_session.refresh(poste_b)
    payments = (await db_session.execute(select(PaymentHistory).where(PaymentHistory.encaissement_id == enc_b.id))).scalars().all()
    assert payments == []
    assert enc_b.montant_paye == Decimal("0.00")
    assert poste_b.montant_paye == Decimal("0.00")


@pytest.mark.asyncio
async def test_concurrent_payments_on_same_encaissement_do_not_lose_amount(db_session, async_session, monkeypatch):
    org = await _enc_org(db_session)
    user = await _enc_user(db_session, org)
    poste = await _enc_budget_poste(db_session, org)
    db_session.add(CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("0"), est_ouverte=True))
    enc = await _encaissement_row(db_session, org, user, poste=poste, montant_paye=Decimal("0"))
    enc.montant = Decimal("1000")
    enc.montant_total = Decimal("1000")
    await db_session.commit()

    async def accounting_disabled(*args, **kwargs):
        return "disabled"

    monkeypatch.setattr("app.services.encaissement_payments.get_accounting_integration_mode", accounting_disabled)

    async def pay(amount: Decimal) -> uuid.UUID:
        async with async_session() as session:
            payment = await record_encaissement_payment(
                session,
                organisation_id=org.id,
                encaissement_id=enc.id,
                montant=amount,
                mode_paiement="cash",
                reference=None,
                notes=None,
                user_id=user.id,
            )
            await session.commit()
            return payment.id

    payment_ids = await asyncio.gather(pay(Decimal("300")), pay(Decimal("400")))

    await db_session.rollback()
    refreshed_enc = await db_session.get(Encaissement, enc.id)
    await db_session.refresh(refreshed_enc)
    caisse = (
        await db_session.execute(select(CaisseCentrale).where(CaisseCentrale.organisation_id == org.id))
    ).scalar_one()
    await db_session.refresh(caisse)
    await db_session.refresh(poste)
    payments = (
        await db_session.execute(
            select(PaymentHistory).where(
                PaymentHistory.encaissement_id == enc.id,
                PaymentHistory.statut == "ACTIF",
            )
        )
    ).scalars().all()
    assert sorted(payment_ids) == sorted([p.id for p in payments])
    assert refreshed_enc.montant_paye == Decimal("700.00")
    assert refreshed_enc.statut_paiement == "partiel"
    assert caisse.solde_usd == Decimal("700.00")
    assert poste.montant_paye == Decimal("700.00")


@pytest.mark.asyncio
async def test_duplicate_payment_double_click_reuses_recent_payment(db_session, monkeypatch):
    org = await _enc_org(db_session)
    user = await _enc_user(db_session, org)
    poste = await _enc_budget_poste(db_session, org)
    caisse = CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("0"), est_ouverte=True)
    db_session.add(caisse)
    await _prepare_audit_context(org, user)
    enc = await _encaissement_row(db_session, org, user, poste=poste, montant_paye=Decimal("0"))
    enc.montant = Decimal("1000")
    enc.montant_total = Decimal("1000")
    await db_session.commit()

    async def accounting_disabled(*args, **kwargs):
        return "disabled"

    email_calls = 0
    whatsapp_calls = 0

    async def count_email(*args, **kwargs):
        nonlocal email_calls
        email_calls += 1
        return None

    async def count_whatsapp(*args, **kwargs):
        nonlocal whatsapp_calls
        whatsapp_calls += 1

    monkeypatch.setattr("app.services.encaissement_payments.get_accounting_integration_mode", accounting_disabled)
    monkeypatch.setattr("app.api.v1.endpoints.payments.schedule_client_payment_email", count_email)
    monkeypatch.setattr("app.api.v1.endpoints.payments._notify_paiement_whatsapp", count_whatsapp)

    payload = PaymentHistoryCreate(
        encaissement_id=enc.id,
        montant=Decimal("250"),
        mode_paiement="cash",
        reference="RCPT-DOUBLE",
        notes="double clic",
    )
    first = await create_payment(
        payload=payload,
        request=_FakeRequest(),
        background_tasks=BackgroundTasks(),
        user=user,
        tenant_id=org.id,
        db=db_session,
    )
    second = await create_payment(
        payload=payload,
        request=_FakeRequest(),
        background_tasks=BackgroundTasks(),
        user=user,
        tenant_id=org.id,
        db=db_session,
    )

    await db_session.refresh(enc)
    await db_session.refresh(caisse)
    await db_session.refresh(poste)
    payments = (
        await db_session.execute(select(PaymentHistory).where(PaymentHistory.encaissement_id == enc.id))
    ).scalars().all()
    assert second["id"] == first["id"]
    assert len(payments) == 1
    assert enc.montant_paye == Decimal("250.00")
    assert enc.statut_paiement == "partiel"
    assert caisse.solde_usd == Decimal("250.00")
    assert poste.montant_paye == Decimal("250.00")
    assert email_calls == 1
    assert whatsapp_calls == 1


@pytest.mark.asyncio
async def test_soft_delete_proforma_without_financial_impact_allowed(db_session):
    org = await _enc_org(db_session)
    user = await _enc_user(db_session, org)
    await _prepare_audit_context(org, user)
    enc = await _encaissement_row(db_session, org, user, est_proforma=True)
    await db_session.commit()

    result = await soft_delete_encaissement(str(enc.id), request=_FakeRequest(), user=user, tenant_id=org.id, db=db_session)

    assert result["id"] == str(enc.id)
    await db_session.refresh(enc)
    assert enc.is_deleted is True
    assert await _audit_count(db_session, enc.id, "ENCAISSEMENT_SOFT_DELETED") == 1


@pytest.mark.asyncio
async def test_soft_delete_real_unpaid_without_financial_impact_allowed(db_session):
    org = await _enc_org(db_session)
    user = await _enc_user(db_session, org)
    poste = await _enc_budget_poste(db_session, org)
    await _prepare_audit_context(org, user)
    enc = await _encaissement_row(db_session, org, user, poste=poste, montant_paye=Decimal("0"))
    await db_session.commit()

    await soft_delete_encaissement(str(enc.id), request=_FakeRequest(), user=user, tenant_id=org.id, db=db_session)

    await db_session.refresh(enc)
    await db_session.refresh(poste)
    assert enc.is_deleted is True
    assert poste.montant_paye == Decimal("0.00")
    assert await _audit_count(db_session, enc.id, "ENCAISSEMENT_SOFT_DELETED") == 1


@pytest.mark.asyncio
async def test_soft_delete_paid_encaissement_refused_and_audited(db_session):
    org = await _enc_org(db_session)
    user = await _enc_user(db_session, org)
    poste = await _enc_budget_poste(db_session, org, paid=Decimal("500"))
    caisse = CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("500"), est_ouverte=True)
    db_session.add(caisse)
    await _prepare_audit_context(org, user)
    enc = await _encaissement_row(db_session, org, user, poste=poste, montant_paye=Decimal("500"))
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await soft_delete_encaissement(str(enc.id), request=_FakeRequest(), user=user, tenant_id=org.id, db=db_session)

    assert exc.value.status_code == 400
    assert "procédure d'annulation" in exc.value.detail
    await db_session.refresh(enc)
    await db_session.refresh(caisse)
    await db_session.refresh(poste)
    assert enc.is_deleted is False
    assert caisse.solde_usd == Decimal("500.00")
    assert poste.montant_paye == Decimal("500.00")
    assert await _audit_count(db_session, enc.id, "ENCAISSEMENT_SOFT_DELETE_REFUSED_FINANCIAL_IMPACT") == 1


@pytest.mark.asyncio
async def test_soft_delete_refused_when_payment_history_exists(db_session):
    org = await _enc_org(db_session)
    user = await _enc_user(db_session, org)
    await _prepare_audit_context(org, user)
    enc = await _encaissement_row(db_session, org, user, montant_paye=Decimal("0"))
    db_session.add(
        PaymentHistory(
            organisation_id=org.id,
            encaissement_id=enc.id,
            montant=Decimal("10"),
            mode_paiement="cash",
            created_by=user.id,
        )
    )
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await soft_delete_encaissement(str(enc.id), request=_FakeRequest(), user=user, tenant_id=org.id, db=db_session)

    assert exc.value.status_code == 400
    await db_session.refresh(enc)
    assert enc.is_deleted is False
    assert await _audit_count(db_session, enc.id, "ENCAISSEMENT_SOFT_DELETE_REFUSED_FINANCIAL_IMPACT") == 1


@pytest.mark.asyncio
async def test_soft_delete_refused_when_accounting_entry_exists(db_session):
    org = await _enc_org(db_session)
    user = await _enc_user(db_session, org)
    await _prepare_audit_context(org, user)
    enc = await _encaissement_row(db_session, org, user, montant_paye=Decimal("0"))
    await _minimal_compta_ecriture(db_session, org, enc)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await soft_delete_encaissement(str(enc.id), request=_FakeRequest(), user=user, tenant_id=org.id, db=db_session)

    assert exc.value.status_code == 400
    await db_session.refresh(enc)
    assert enc.is_deleted is False
    assert await _audit_count(db_session, enc.id, "ENCAISSEMENT_SOFT_DELETE_REFUSED_FINANCIAL_IMPACT") == 1


@pytest.mark.asyncio
async def test_restore_non_financial_encaissement_allowed_without_double_impact(db_session):
    org = await _enc_org(db_session)
    user = await _enc_user(db_session, org)
    poste = await _enc_budget_poste(db_session, org)
    await _prepare_audit_context(org, user)
    enc = await _encaissement_row(db_session, org, user, poste=poste, montant_paye=Decimal("0"), is_deleted=True)
    await db_session.commit()

    await restore_encaissement(str(enc.id), request=_FakeRequest(), user=user, tenant_id=org.id, db=db_session)

    await db_session.refresh(enc)
    await db_session.refresh(poste)
    assert enc.is_deleted is False
    assert enc.deleted_at is None
    assert enc.deleted_by is None
    assert poste.montant_paye == Decimal("0.00")
    assert await _audit_count(db_session, enc.id, "ENCAISSEMENT_RESTORED") == 1


@pytest.mark.asyncio
async def test_restore_financial_encaissement_refused(db_session):
    org = await _enc_org(db_session)
    user = await _enc_user(db_session, org)
    poste = await _enc_budget_poste(db_session, org, paid=Decimal("500"))
    await _prepare_audit_context(org, user)
    enc = await _encaissement_row(
        db_session,
        org,
        user,
        poste=poste,
        montant_paye=Decimal("500"),
        is_deleted=True,
    )
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await restore_encaissement(str(enc.id), request=_FakeRequest(), user=user, tenant_id=org.id, db=db_session)

    assert exc.value.status_code == 400
    await db_session.refresh(enc)
    assert enc.is_deleted is True
    assert await _audit_count(db_session, enc.id, "ENCAISSEMENT_RESTORE_REFUSED_FINANCIAL_IMPACT") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("canal", "devise"),
    [("CAISSE", "USD"), ("CAISSE", "CDF"), ("BANQUE", "USD")],
)
async def test_cancel_operation_neutralizes_treasury_and_budget_exactly(db_session, monkeypatch, canal, devise):
    org = await _enc_org(db_session)
    user = await _enc_user(db_session, org)
    poste = await _enc_budget_poste(db_session, org, paid=Decimal("500"))
    compte_id = None
    if canal == "CAISSE":
        caisse = CaisseCentrale(
            organisation_id=org.id,
            solde_usd=Decimal("500") if devise == "USD" else Decimal("0"),
            solde_cdf=Decimal("500") if devise == "CDF" else Decimal("0"),
            est_ouverte=True,
        )
        db_session.add(caisse)
    else:
        compte = CompteBancaire(
            organisation_id=org.id,
            intitule="Compte banque",
            numero_compte=f"BK-{_suffix()}",
            devise=devise,
            solde_initial=Decimal("500"),
            solde_actuel=Decimal("500"),
            is_active=True,
            account_type="BANK",
        )
        db_session.add(compte)
        await db_session.flush()
        compte_id = compte.id
    await _prepare_audit_context(org, user)
    enc = await _encaissement_row(
        db_session,
        org,
        user,
        poste=poste,
        montant_paye=Decimal("500"),
        canal=canal,
        devise=devise,
        compte_bancaire_id=compte_id,
    )
    db_session.add(
        PaymentHistory(
            organisation_id=org.id,
            encaissement_id=enc.id,
            montant=Decimal("500"),
            mode_paiement="cash",
            created_by=user.id,
        )
    )
    await db_session.commit()

    async def always_allowed(*args, **kwargs):
        return True

    async def accounting_disabled(*args, **kwargs):
        return False

    monkeypatch.setattr("app.api.v1.endpoints.encaissements._user_has_permission", always_allowed)
    monkeypatch.setattr("app.api.v1.endpoints.encaissements.is_accounting_automatic", accounting_disabled)

    await cancel_encaissement_operation(
        str(enc.id),
        payload=EncaissementCancelPayload(motif_annulation="Annulation test"),
        request=_FakeRequest(),
        user=user,
        tenant_id=org.id,
        db=db_session,
    )

    await db_session.refresh(enc)
    await db_session.refresh(poste)
    assert enc.statut_operation == "ANNULEE"
    assert poste.montant_paye == Decimal("0.00")
    if canal == "CAISSE":
        await db_session.refresh(caisse)
        assert caisse.solde_usd == (Decimal("0.00") if devise == "USD" else Decimal("0.00"))
        assert caisse.solde_cdf == (Decimal("0.00") if devise == "CDF" else Decimal("0.00"))
    else:
        await db_session.refresh(compte)
        assert compte.solde_actuel == Decimal("0.00")
    assert await _audit_count(db_session, enc.id, "ENCAISSEMENT_CANCELLED") == 1


@pytest.mark.asyncio
async def test_cancel_operation_second_attempt_refused(db_session, monkeypatch):
    org = await _enc_org(db_session)
    user = await _enc_user(db_session, org)
    poste = await _enc_budget_poste(db_session, org, paid=Decimal("500"))
    caisse = CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("500"), est_ouverte=True)
    db_session.add(caisse)
    await _prepare_audit_context(org, user)
    enc = await _encaissement_row(db_session, org, user, poste=poste, montant_paye=Decimal("500"))
    await db_session.commit()

    async def always_allowed(*args, **kwargs):
        return True

    async def accounting_disabled(*args, **kwargs):
        return False

    monkeypatch.setattr("app.api.v1.endpoints.encaissements._user_has_permission", always_allowed)
    monkeypatch.setattr("app.api.v1.endpoints.encaissements.is_accounting_automatic", accounting_disabled)

    await cancel_encaissement_operation(
        str(enc.id),
        payload=EncaissementCancelPayload(motif_annulation="Annulation test"),
        request=_FakeRequest(),
        user=user,
        tenant_id=org.id,
        db=db_session,
    )
    with pytest.raises(HTTPException) as exc:
        await cancel_encaissement_operation(
            str(enc.id),
            payload=EncaissementCancelPayload(motif_annulation="Deuxième tentative"),
            request=_FakeRequest(),
            user=user,
            tenant_id=org.id,
            db=db_session,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_cancel_operation_accounting_failure_rolls_back_financial_changes(db_session, monkeypatch):
    org = await _enc_org(db_session)
    user = await _enc_user(db_session, org)
    poste = await _enc_budget_poste(db_session, org, paid=Decimal("500"))
    caisse = CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("500"), est_ouverte=True)
    db_session.add(caisse)
    await _prepare_audit_context(org, user)
    enc = await _encaissement_row(db_session, org, user, poste=poste, montant_paye=Decimal("500"))
    await db_session.commit()

    async def always_allowed(*args, **kwargs):
        return True

    async def accounting_enabled(*args, **kwargs):
        return True

    async def fail_accounting(*args, **kwargs):
        raise HTTPException(status_code=500, detail="Erreur comptable simulée")

    monkeypatch.setattr("app.api.v1.endpoints.encaissements._user_has_permission", always_allowed)
    monkeypatch.setattr("app.api.v1.endpoints.encaissements.is_accounting_automatic", accounting_enabled)
    monkeypatch.setattr("app.api.v1.endpoints.encaissements.annuler_ecriture_operation", fail_accounting)

    with pytest.raises(HTTPException):
        await cancel_encaissement_operation(
            str(enc.id),
            payload=EncaissementCancelPayload(motif_annulation="Annulation test"),
            request=_FakeRequest(),
            user=user,
            tenant_id=org.id,
            db=db_session,
        )

    await db_session.rollback()
    await db_session.refresh(enc)
    await db_session.refresh(caisse)
    await db_session.refresh(poste)
    assert enc.statut_operation == "ACTIVE"
    assert caisse.solde_usd == Decimal("500.00")
    assert poste.montant_paye == Decimal("500.00")


@pytest.mark.asyncio
async def test_cancel_operation_cancels_accounting_entry_when_accounting_enabled(db_session, monkeypatch):
    org = await _enc_org(db_session)
    user = await _enc_user(db_session, org)
    poste = await _enc_budget_poste(db_session, org, paid=Decimal("500"))
    caisse = CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("500"), est_ouverte=True)
    db_session.add(caisse)
    await _prepare_audit_context(org, user)
    enc = await _encaissement_row(db_session, org, user, poste=poste, montant_paye=Decimal("500"))
    ecriture = await _minimal_compta_ecriture(db_session, org, enc)
    await db_session.commit()

    async def always_allowed(*args, **kwargs):
        return True

    async def accounting_enabled(*args, **kwargs):
        return True

    monkeypatch.setattr("app.api.v1.endpoints.encaissements._user_has_permission", always_allowed)
    monkeypatch.setattr("app.api.v1.endpoints.encaissements.is_accounting_automatic", accounting_enabled)

    await cancel_encaissement_operation(
        str(enc.id),
        payload=EncaissementCancelPayload(motif_annulation="Annulation test"),
        request=_FakeRequest(),
        user=user,
        tenant_id=org.id,
        db=db_session,
    )

    await db_session.refresh(enc)
    await db_session.refresh(ecriture)
    assert enc.statut_operation == "ANNULEE"
    assert ecriture.statut == "ANNULEE"
    assert await _audit_count(db_session, enc.id, "ENCAISSEMENT_CANCELLED") == 1


@pytest.mark.asyncio
async def test_cancel_operation_refuses_insufficient_cash_without_clamping(db_session, monkeypatch):
    org = await _enc_org(db_session)
    user = await _enc_user(db_session, org)
    poste = await _enc_budget_poste(db_session, org, paid=Decimal("500"))
    caisse = CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("50"), est_ouverte=True)
    db_session.add(caisse)
    await _prepare_audit_context(org, user)
    enc = await _encaissement_row(db_session, org, user, poste=poste, montant_paye=Decimal("500"))
    await db_session.commit()

    async def always_allowed(*args, **kwargs):
        return True

    async def accounting_disabled(*args, **kwargs):
        return False

    monkeypatch.setattr("app.api.v1.endpoints.encaissements._user_has_permission", always_allowed)
    monkeypatch.setattr("app.api.v1.endpoints.encaissements.is_accounting_automatic", accounting_disabled)

    with pytest.raises(HTTPException) as exc:
        await cancel_encaissement_operation(
            str(enc.id),
            payload=EncaissementCancelPayload(motif_annulation="Annulation impossible"),
            request=_FakeRequest(),
            user=user,
            tenant_id=org.id,
            db=db_session,
        )

    assert exc.value.status_code == 400
    assert "Solde caisse insuffisant" in exc.value.detail
    await db_session.rollback()
    await db_session.refresh(enc)
    await db_session.refresh(caisse)
    await db_session.refresh(poste)
    assert enc.statut_operation == "ACTIVE"
    assert caisse.solde_usd == Decimal("50.00")
    assert poste.montant_paye == Decimal("500.00")


@pytest.mark.asyncio
async def test_cancel_operation_refuses_insufficient_budget_without_clamping(db_session, monkeypatch):
    org = await _enc_org(db_session)
    user = await _enc_user(db_session, org)
    poste = await _enc_budget_poste(db_session, org, paid=Decimal("50"))
    caisse = CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("500"), est_ouverte=True)
    db_session.add(caisse)
    await _prepare_audit_context(org, user)
    enc = await _encaissement_row(db_session, org, user, poste=poste, montant_paye=Decimal("500"))
    await db_session.commit()

    async def always_allowed(*args, **kwargs):
        return True

    async def accounting_disabled(*args, **kwargs):
        return False

    monkeypatch.setattr("app.api.v1.endpoints.encaissements._user_has_permission", always_allowed)
    monkeypatch.setattr("app.api.v1.endpoints.encaissements.is_accounting_automatic", accounting_disabled)

    with pytest.raises(HTTPException) as exc:
        await cancel_encaissement_operation(
            str(enc.id),
            payload=EncaissementCancelPayload(motif_annulation="Annulation impossible"),
            request=_FakeRequest(),
            user=user,
            tenant_id=org.id,
            db=db_session,
        )

    assert exc.value.status_code == 400
    assert "Exécution budgétaire insuffisante" in exc.value.detail
    await db_session.rollback()
    await db_session.refresh(enc)
    await db_session.refresh(caisse)
    await db_session.refresh(poste)
    assert enc.statut_operation == "ACTIVE"
    assert caisse.solde_usd == Decimal("500.00")
    assert poste.montant_paye == Decimal("50.00")


@pytest.mark.asyncio
async def test_soft_delete_is_tenant_isolated(db_session):
    org_a = await _enc_org(db_session, name="Tenant A")
    org_b = await _enc_org(db_session, name="Tenant B")
    user_a = await _enc_user(db_session, org_a)
    user_b = await _enc_user(db_session, org_b)
    await _prepare_audit_context(org_a, user_a)
    enc_b = await _encaissement_row(db_session, org_b, user_b, est_proforma=True)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await soft_delete_encaissement(str(enc_b.id), request=_FakeRequest(), user=user_a, tenant_id=org_a.id, db=db_session)

    assert exc.value.status_code == 404
    await db_session.refresh(enc_b)
    assert enc_b.is_deleted is False
