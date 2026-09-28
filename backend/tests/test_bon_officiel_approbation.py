"""Le PDF officiel d'une réquisition est figé à son approbation.

`ensure_requisition_official_pdf` existait sans être appelé : les réquisitions
APPROUVEE, PAYEE ou EN_DECAISSEMENT n'avaient de `pdf_path` que si le navigateur
avait réussi à téléverser son bon à la création. Le PDF est désormais produit
côté serveur au passage à APPROUVEE — juste après le snapshot historique, dont
il dépend — et jamais plus tôt : une pièce en examen ou seulement autorisée
peut encore être rejetée.
"""

import logging
import os
import uuid
from decimal import Decimal

import pytest

import app.main as app_main
from app.models.ligne_requisition import LigneRequisition
from app.models.organisation import Organisation
from app.models.print_settings import PrintSettings
from app.models.requisition import Requisition
from app.models.service import Service
from app.models.user import User
from app.services import official_pdf
from app.services import requisition_service
from app.services.requisition_service import validate_requisition_logic, vise_requisition_logic


class _FakeRequest:
    headers: dict = {}
    client = None


def _workflow(*, visa: bool):
    return {
        "preset": "personnalise",
        "steps": {
            "signature_service": {"enabled": False},
            "examen": {"enabled": False},
            "validation_1": {"enabled": True},
            "validation_2": {"enabled": visa},
        },
    }


async def _contexte(db):
    org = Organisation(nom="Bon officiel", slug=f"bon-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    service = Service(organisation_id=org.id, code=f"S{uuid.uuid4().hex[:4]}", libelle="Service", is_active=True)
    db.add(service)
    users = []
    for prenom in ("Alice", "Bruno"):
        user = User(
            id=uuid.uuid4(),
            email=f"{uuid.uuid4().hex[:8]}@example.com",
            nom="Validateur",
            prenom=prenom,
            role="admin",
            organisation_id=org.id,
            active=True,
        )
        db.add(user)
        users.append(user)
    db.add(
        PrintSettings(
            organisation_id=org.id,
            organization_name="ONEC Test",
            req_titre_officiel="BON DE REQUISITION",
            req_label_gauche="Etabli par",
            req_nom_gauche="Alice A",
            req_label_droite="Approuve par",
            req_nom_droite="President",
            default_currency="USD",
            secondary_currency="CDF",
            exchange_rate_cdf=Decimal("2800"),
        )
    )
    await db.flush()
    return org, service, users


async def _requisition(db, org, service, user, *, visa: bool):
    req = Requisition(
        organisation_id=org.id,
        service_id=service.id,
        numero_requisition=f"REQ-{uuid.uuid4().hex[:8]}",
        reference_numero=f"REF-{uuid.uuid4().hex[:8]}",
        objet="Achat de fournitures",
        mode_paiement="cash",
        type_requisition="classique",
        status="EN_ATTENTE",
        examen_status="EXAMINE",
        montant_total=Decimal("150"),
        devise="USD",
        created_by=user.id,
        workflow_snapshot=_workflow(visa=visa),
    )
    db.add(req)
    await db.flush()
    db.add(
        LigneRequisition(
            organisation_id=org.id,
            requisition_id=req.id,
            rubrique="Fournitures",
            description="Papier",
            quantite=1,
            montant_unitaire=Decimal("150"),
            montant_total=Decimal("150"),
            devise="USD",
        )
    )
    await db.commit()
    return req


def _fichier(pdf_path: str) -> str:
    return os.path.join(official_pdf.UPLOAD_ROOT, pdf_path.replace("/uploads/", "", 1))


async def _valider(db, req, org, user):
    return await validate_requisition_logic(
        db=db, requisition_id=req.id, user=user, tenant_id=org.id, request=_FakeRequest()
    )


@pytest.mark.asyncio
async def test_la_premiere_validation_qui_approuve_fige_le_pdf(db_session):
    org, service, (alice, _) = await _contexte(db_session)
    req = await _requisition(db_session, org, service, alice, visa=False)

    req = await _valider(db_session, req, org, alice)

    assert req.status == "APPROUVEE"
    assert req.pdf_path and req.pdf_path.startswith(f"/uploads/tenants/{org.uuid}/requisitions/")
    with open(_fichier(req.pdf_path), "rb") as handle:
        assert handle.read(5) == b"%PDF-"


@pytest.mark.asyncio
async def test_rien_n_est_fige_tant_que_le_visa_manque(db_session):
    org, service, (alice, _) = await _contexte(db_session)
    req = await _requisition(db_session, org, service, alice, visa=True)

    req = await _valider(db_session, req, org, alice)

    assert req.status == "AUTORISEE"
    assert req.pdf_path is None


@pytest.mark.asyncio
async def test_le_visa_fige_le_pdf(db_session):
    org, service, (alice, bruno) = await _contexte(db_session)
    req = await _requisition(db_session, org, service, alice, visa=True)
    await _valider(db_session, req, org, alice)

    req = await vise_requisition_logic(
        db=db_session, requisition_id=req.id, user=bruno, tenant_id=org.id, request=_FakeRequest()
    )

    assert req.status == "APPROUVEE"
    assert req.pdf_path
    assert os.path.exists(_fichier(req.pdf_path))


@pytest.mark.asyncio
async def test_un_echec_du_pdf_ne_defait_pas_l_approbation(db_session, monkeypatch, caplog):
    async def _echoue(*args, **kwargs):
        raise OSError("disque en lecture seule")

    monkeypatch.setattr(requisition_service, "ensure_requisition_official_pdf", _echoue)
    org, service, (alice, _) = await _contexte(db_session)
    req = await _requisition(db_session, org, service, alice, visa=False)

    with caplog.at_level(logging.ERROR):
        req = await _valider(db_session, req, org, alice)

    assert req.status == "APPROUVEE"
    assert req.pdf_path is None
    assert "PDF officiel non généré" in caplog.text


def test_le_demarrage_signale_un_dossier_de_fichiers_non_inscriptible(monkeypatch, caplog, tmp_path):
    monkeypatch.setattr(app_main, "UPLOAD_DIR", str(tmp_path / "absent"))

    with caplog.at_level(logging.ERROR):
        app_main._verifier_ecriture_uploads()

    assert "UPLOAD_DIR non accessible en écriture" in caplog.text


def test_le_demarrage_accepte_un_dossier_inscriptible(monkeypatch, caplog, tmp_path):
    monkeypatch.setattr(app_main, "UPLOAD_DIR", str(tmp_path))

    with caplog.at_level(logging.INFO):
        app_main._verifier_ecriture_uploads()

    assert "UPLOAD_DIR non accessible" not in caplog.text
    assert list(tmp_path.iterdir()) == []
