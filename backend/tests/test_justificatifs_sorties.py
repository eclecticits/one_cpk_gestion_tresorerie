"""Bénéficiaire identifié, justificatif attendu et relance unique des sorties de fonds."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select

from app.models.beneficiaire_externe import BeneficiaireExterne
from app.models.sortie_fonds import SortieFonds
from app.models.system_settings import SystemSettings
from app.schemas.sortie_fonds import JustificatifDecision, SortieFondsCreate
from app.services import beneficiaires, justificatifs
from app.services.notifications import events, templates

from tests.test_treasury_flows import (
    _FakeRequest,
    _admin,
    _caisse,
    _depense_poste,
    _org,
    _requisition_source,
    _service,
)


# ── Règles pures ─────────────────────────────────────────────────────────────


def test_un_code_coche_couvre_ses_sous_postes_et_pas_ses_voisins():
    codes = ["II.2.3"]
    assert justificatifs.code_exige_justificatif(codes, "II.2.3")
    assert justificatifs.code_exige_justificatif(codes, "II.2.3.1.1")
    assert not justificatifs.code_exige_justificatif(codes, "II.2.30")
    assert not justificatifs.code_exige_justificatif(codes, "II.2")
    assert not justificatifs.code_exige_justificatif([], "II.2.3")
    assert not justificatifs.code_exige_justificatif(codes, None)


def test_echeance_48h_retard_et_relance_a_j7():
    paye = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
    sortie = SortieFonds(date_paiement=paye)
    justificatifs.poser_attente(sortie, True, depart=paye)
    assert sortie.justificatif_statut == justificatifs.STATUT_ATTENDU
    assert sortie.justificatif_echeance == paye + timedelta(hours=48)
    assert justificatifs.relance_prevue_le(sortie) == paye + timedelta(days=7)
    assert justificatifs.statut_affiche(sortie, paye + timedelta(hours=47)) == justificatifs.STATUT_ATTENDU
    assert justificatifs.statut_affiche(sortie, paye + timedelta(hours=49)) == justificatifs.STATUT_EN_RETARD

    justificatifs.poser_attente(sortie, False)
    assert sortie.justificatif_statut == justificatifs.STATUT_NON_REQUIS
    assert sortie.justificatif_echeance is None
    assert justificatifs.relance_prevue_le(sortie) is None


def test_message_de_remise_ne_demande_la_piece_que_si_elle_est_attendue():
    paye = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
    base = dict(
        date_paiement=paye,
        beneficiaire="Jean Kabila",
        reference_numero="PAY-001",
        motif="Achat fournitures",
        montant_paye=Decimal("200"),
        devise="USD",
    )
    gabarit = templates.resolve(events.FUND_OUTFLOW_BENEFICIARY)

    taxi = SortieFonds(**base)
    justificatifs.poser_attente(taxi, False)
    texte = templates.render(gabarit, justificatifs._variables(taxi))
    assert "Bonjour Jean Kabila," in texte
    assert "200.00 USD" in texte
    assert "48 heures" not in texte

    achat = SortieFonds(**base)
    justificatifs.poser_attente(achat, True, depart=paye)
    texte = templates.render(gabarit, justificatifs._variables(achat))
    assert "dans les 48 heures" in texte
    assert "03/10/2026" in texte


def test_contacts_invalides_refuses_a_la_saisie():
    with pytest.raises(HTTPException):
        beneficiaires.nettoyer_email("pas-une-adresse")
    with pytest.raises(HTTPException):
        beneficiaires.nettoyer_telephone("12")
    assert beneficiaires.nettoyer_email("  ") is None
    assert beneficiaires.nettoyer_telephone("") is None


# ── Parcours en base ─────────────────────────────────────────────────────────


async def _payer(db, monkeypatch, org, user, poste, service, **extra):
    async def fake_num(*args, **kwargs):
        return f"PAY-{uuid.uuid4().hex[:8]}"

    async def accounting_disabled(*args, **kwargs):
        return "disabled"

    envoyes: list[SortieFonds] = []

    async def fake_notify(db, background_tasks, *, sortie, tenant_id):
        envoyes.append(sortie)

    monkeypatch.setattr("app.api.v1.endpoints.sorties_fonds.generate_document_number", fake_num)
    monkeypatch.setattr("app.api.v1.endpoints.sorties_fonds.get_accounting_integration_mode", accounting_disabled)
    monkeypatch.setattr("app.api.v1.endpoints.sorties_fonds._notifier_beneficiaire_sortie", fake_notify)

    from app.api.v1.endpoints.sorties_fonds import create_sortie_fonds

    req = await _requisition_source(db, org, poste=poste, service=service, montant=Decimal("100"))
    payload = SortieFondsCreate(
        type_sortie="autre",
        requisition_id=req.id,
        montant_paye=Decimal("100"),
        mode_paiement="cash",
        devise="USD",
        canal="CAISSE",
        motif="Fournitures",
        beneficiaire="Jean  Kabila",
        service_id=service.id,
        budget_poste_id=poste.id,
        **extra,
    )
    out = await create_sortie_fonds(
        payload=payload,
        request=_FakeRequest(),
        background_tasks=BackgroundTasks(),
        idempotency_key=None,
        user=user,
        tenant_id=org.id,
        db=db,
    )
    return out, envoyes


@pytest.mark.asyncio
async def test_externe_cree_une_fois_et_case_du_caissier_respectee(db_session, monkeypatch):
    db = db_session
    org = await _org(db)
    poste = await _depense_poste(db, org)
    service = await _service(db, org)
    await _caisse(db, org, usd=Decimal("1000"))
    await db.commit()
    user = await _admin(db, org)

    out, envoyes = await _payer(
        db, monkeypatch, org, user, poste, service,
        beneficiaire_type="EXTERNE",
        beneficiaire_telephone="0810000001",
        justificatif_requis=True,
    )
    assert out.beneficiaire_type == "EXTERNE"
    assert out.beneficiaire_telephone == "243810000001"
    assert out.justificatif_statut == justificatifs.STATUT_ATTENDU
    assert out.justificatif_echeance is not None
    assert len(envoyes) == 1

    # Même personne, autre graphie : la fiche est reprise, pas dupliquée.
    out2, _ = await _payer(
        db, monkeypatch, org, user, poste, service,
        beneficiaire_type="EXTERNE",
        beneficiaire_email="jean@example.org",
        justificatif_requis=False,
    )
    assert out2.justificatif_statut == justificatifs.STATUT_NON_REQUIS
    fiches = (
        await db.execute(select(BeneficiaireExterne).where(BeneficiaireExterne.organisation_id == org.id))
    ).scalars().all()
    assert len(fiches) == 1
    assert fiches[0].telephone == "243810000001"
    assert fiches[0].email == "jean@example.org"


@pytest.mark.asyncio
async def test_poste_designe_coche_d_avance_sauf_si_le_caissier_decoche(db_session, monkeypatch):
    db = db_session
    org = await _org(db)
    poste = await _depense_poste(db, org)
    service = await _service(db, org)
    await _caisse(db, org, usd=Decimal("1000"))
    db.add(SystemSettings(organisation_id=org.id, justificatif_postes_codes=[poste.code]))
    await db.commit()
    user = await _admin(db, org)

    par_defaut, _ = await _payer(db, monkeypatch, org, user, poste, service)
    assert par_defaut.justificatif_statut == justificatifs.STATUT_ATTENDU

    decoche, _ = await _payer(db, monkeypatch, org, user, poste, service, justificatif_requis=False)
    assert decoche.justificatif_statut == justificatifs.STATUT_NON_REQUIS


@pytest.mark.asyncio
async def test_relance_unique_a_j7_puis_depot_du_caissier(db_session, monkeypatch):
    db = db_session
    org = await _org(db)
    poste = await _depense_poste(db, org)
    service = await _service(db, org)
    await _caisse(db, org, usd=Decimal("1000"))
    await db.commit()
    user = await _admin(db, org)

    out, _ = await _payer(
        db, monkeypatch, org, user, poste, service,
        beneficiaire_type="EXTERNE",
        justificatif_requis=True,
    )
    sortie = (await db.execute(select(SortieFonds).where(SortieFonds.id == out.id))).scalar_one()

    # Six jours après : pas encore de relance.
    sortie.justificatif_echeance = datetime.now(timezone.utc) - timedelta(days=4)
    await db.commit()
    assert await justificatifs.sorties_a_relancer(db, org.id) == []

    # Sept jours et plus : une relance, et une seule.
    sortie.justificatif_echeance = datetime.now(timezone.utc) - timedelta(days=6)
    await db.commit()
    assert await justificatifs.sorties_a_relancer(db, org.id) == [sortie.id]

    relances: list[str] = []

    async def fake_envoyer(db, background_tasks, *, sortie, event_type, **kwargs):
        relances.append(event_type)

    monkeypatch.setattr(justificatifs, "_envoyer", fake_envoyer)
    assert await justificatifs.relancer(db, sortie_id=sortie.id, organisation_id=org.id)
    assert not await justificatifs.relancer(db, sortie_id=sortie.id, organisation_id=org.id)
    assert relances == [events.JUSTIFICATIF_RELANCE]
    assert await justificatifs.sorties_a_relancer(db, org.id) == []

    # Après la relance automatique, le caissier peut relancer quand il veut —
    # mais pas deux fois dans la même minute (double clic).
    await db.refresh(sortie)
    sortie.justificatif_derniere_relance_le = datetime.now(timezone.utc) - timedelta(minutes=5)
    await db.commit()
    assert await justificatifs.relancer_manuellement(db, sortie_id=out.id, organisation_id=org.id)
    assert not await justificatifs.relancer_manuellement(db, sortie_id=out.id, organisation_id=org.id)
    assert relances == [events.JUSTIFICATIF_RELANCE, events.JUSTIFICATIF_RELANCE]
    await db.refresh(sortie)
    assert sortie.justificatif_nb_relances == 2

    from app.api.v1.endpoints.sorties_fonds import decider_justificatif

    with pytest.raises(HTTPException) as exc:
        await decider_justificatif(
            sortie_id=str(sortie.id),
            payload=JustificatifDecision(action="dispenser"),
            request=_FakeRequest(),
            db=db,
            user=user,
            tenant_id=org.id,
        )
    assert exc.value.status_code == 400

    dispense = await decider_justificatif(
        sortie_id=str(sortie.id),
        payload=JustificatifDecision(action="dispenser", motif="Facture remise au trésorier"),
        request=_FakeRequest(),
        db=db,
        user=user,
        tenant_id=org.id,
    )
    assert dispense.justificatif_statut == justificatifs.STATUT_DISPENSE


@pytest.mark.asyncio
async def test_la_sortie_reprend_le_beneficiaire_designe_a_la_requisition(db_session, monkeypatch):
    """Désigné en amont, le bénéficiaire n'est pas ressaisi à la caisse : la
    sortie reprend son identification, même si la caisse en envoie une autre."""
    db = db_session
    org = await _org(db)
    poste = await _depense_poste(db, org)
    service = await _service(db, org)
    await _caisse(db, org, usd=Decimal("1000"))
    await db.commit()
    user = await _admin(db, org)

    externe = await beneficiaires.enregistrer_externe(
        db, org.id, nom="Fournisseur Alpha", telephone="243810000002"
    )
    await db.commit()

    async def fake_num(*args, **kwargs):
        return f"PAY-{uuid.uuid4().hex[:8]}"

    async def accounting_disabled(*args, **kwargs):
        return "disabled"

    async def fake_notify(*args, **kwargs):
        return None

    monkeypatch.setattr("app.api.v1.endpoints.sorties_fonds.generate_document_number", fake_num)
    monkeypatch.setattr("app.api.v1.endpoints.sorties_fonds.get_accounting_integration_mode", accounting_disabled)
    monkeypatch.setattr("app.api.v1.endpoints.sorties_fonds._notifier_beneficiaire_sortie", fake_notify)
    from app.api.v1.endpoints.sorties_fonds import create_sortie_fonds

    req = await _requisition_source(db, org, poste=poste, service=service, montant=Decimal("100"))
    req.beneficiaire = "Fournisseur Alpha"
    beneficiaires.appliquer(
        req,
        await beneficiaires.identifier(
            db, org.id, nom="Fournisseur Alpha", type_beneficiaire="EXTERNE",
            reference_id=str(externe.id), email=None, telephone=None,
        ),
    )
    await db.commit()

    out = await create_sortie_fonds(
        payload=SortieFondsCreate(
            type_sortie="autre", requisition_id=req.id, montant_paye=Decimal("100"),
            mode_paiement="cash", devise="USD", canal="CAISSE", motif="Achat",
            service_id=service.id, budget_poste_id=poste.id,
            beneficiaire_type="EXTERNE", beneficiaire_telephone="0899999999",
        ),
        request=_FakeRequest(), background_tasks=BackgroundTasks(),
        idempotency_key=None, user=user, tenant_id=org.id, db=db,
    )
    assert out.beneficiaire == "Fournisseur Alpha"
    assert out.beneficiaire_type == "EXTERNE"
    assert out.beneficiaire_telephone == "243810000002"


@pytest.mark.asyncio
async def test_un_utilisateur_de_l_application_se_retrouve_et_s_identifie(db_session):
    db = db_session
    org = await _org(db)
    user = await _admin(db, org)
    user.prenom, user.nom = "Grace", "Mbuyi"
    await db.commit()

    suggestions = await beneficiaires.rechercher(db, org.id, "mbuyi")
    trouve = [s for s in suggestions if s["type"] == "UTILISATEUR"]
    assert trouve and trouve[0]["nom"] == "Grace Mbuyi"
    assert trouve[0]["email"] == user.email

    identifie = await beneficiaires.identifier(
        db, org.id, nom="Grace Mbuyi", type_beneficiaire="UTILISATEUR",
        reference_id=trouve[0]["id"], email=None, telephone="0810000003",
    )
    assert identifie.utilisateur_id == user.id
    assert identifie.email == user.email
    assert identifie.telephone == "243810000003"
