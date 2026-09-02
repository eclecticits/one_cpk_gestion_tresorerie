import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import BackgroundTasks
from fastapi import HTTPException

from app.api.v1.endpoints import requisitions as requisitions_endpoint
from app.api.v1.endpoints import dossiers_requisition as dossiers_endpoint
from app.api.v1.endpoints import remboursements_transport as remboursements_endpoint
from app.models.dossier_requisition import DossierRequisition
from app.models.ligne_requisition import LigneRequisition
from app.models.organisation import Organisation
from app.models.print_settings import PrintSettings
from app.models.requisition import Requisition
from app.models.service import Service
from app.models.sortie_fonds import SortieFonds
from app.models.system_settings import SystemSettings
from app.models.user import User
from app.schemas.remboursement_transport import RemboursementTransportCreate
from app.schemas.dossier_requisition import DossierRequisitionUpdate
from app.schemas.requisition import RequisitionCreate, RequisitionExamenPayload
from app.services import official_pdf as official_pdf_service
from app.services.requisition_service import create_requisition_logic
from app.services.requisition_service import (
    reject_requisition_examen_logic,
    reject_requisition_at_payment_logic,
    sign_commission_requisition_logic,
    submit_requisition_examen_logic,
    validate_requisition_examen_logic,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _seed_service_context(db_session):
    organisation = Organisation(
        nom="Organisation Test",
        slug=f"org-test-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(organisation)
    await db_session.flush()

    service = Service(
        code=f"SRV-{uuid.uuid4().hex[:6]}",
        libelle="Service Test",
        organisation_id=organisation.id,
    )
    db_session.add(service)
    await db_session.flush()
    await db_session.commit()
    return organisation, service


async def _create_requisition(
    db_session,
    *,
    organisation_id: int,
    service_id: int,
    status: str = "SIGNEE_SERVICE",
    examen_status: str = "NON_EXAMINE",
    dossier_id=None,
    signed_by_id=None,
    signed_at=None,
    created_by=None,
):
    req = Requisition(
        numero_requisition=f"REQ-TEST-{uuid.uuid4().hex[:8]}",
        reference_numero=f"REQ-TEST-{uuid.uuid4().hex[:8]}",
        objet="Réquisition de test",
        mode_paiement="cash",
        type_requisition="classique",
        status=status,
        examen_status=examen_status,
        montant_total=Decimal("100.00"),
        organisation_id=organisation_id,
        service_id=service_id,
        dossier_id=dossier_id,
        signed_by_id=signed_by_id,
        signed_at=signed_at,
        created_by=created_by,
        created_at=_utcnow(),
        updated_at=_utcnow(),
        is_deleted=False,
    )
    db_session.add(req)
    await db_session.flush()
    return req


async def _add_line(db_session, requisition_id):
    db_session.add(
        LigneRequisition(
            requisition_id=requisition_id,
            rubrique="Test",
            description="Ligne de test",
            quantite=1,
            montant_unitaire=Decimal("100.00"),
            montant_total=Decimal("100.00"),
            devise="USD",
        )
    )
    await db_session.commit()


async def _create_admin_user(db_session, organisation_id: int) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"admin-{uuid.uuid4().hex[:8]}@example.com",
        role="admin",
        organisation_id=organisation_id,
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest.mark.asyncio
async def test_submit_requisition_examen_ok(db_session):
    organisation, service = await _seed_service_context(db_session)
    req = await _create_requisition(
        db_session,
        organisation_id=organisation.id,
        service_id=service.id,
        signed_by_id=uuid.uuid4(),
        signed_at=_utcnow(),
    )
    await _add_line(db_session, req.id)

    result = await submit_requisition_examen_logic(
        db=db_session,
        requisition_id=req.id,
        tenant_id=organisation.id,
    )

    assert result.status == "EN_ATTENTE"
    assert result.examen_status == "EN_EXAMEN"


@pytest.mark.asyncio
async def test_schedule_bureau_notifications_uses_persisted_examinateur(db_session, monkeypatch):
    organisation, service = await _seed_service_context(db_session)
    creator = User(
        id=uuid.uuid4(),
        email=f"creator-{uuid.uuid4().hex[:8]}@example.com",
        nom="Createur",
        prenom="Alice",
        role="admin",
        organisation_id=organisation.id,
    )
    action_user = User(
        id=uuid.uuid4(),
        email=f"action-{uuid.uuid4().hex[:8]}@example.com",
        nom="Soumetteur",
        prenom="Bob",
        role="admin",
        organisation_id=organisation.id,
    )
    examiner = User(
        id=uuid.uuid4(),
        email=f"examiner-{uuid.uuid4().hex[:8]}@example.com",
        nom="Examinateur",
        prenom="Claire",
        role="admin",
        organisation_id=organisation.id,
    )
    db_session.add_all([creator, action_user, examiner])
    await db_session.flush()

    settings = SystemSettings(
        organisation_id=organisation.id,
        email_expediteur="noreply@example.com",
        email_president="president@example.com",
        email_validation_1="validation@example.com",
        smtp_host="smtp.example.com",
        smtp_port=465,
        smtp_password="secret",
    )
    db_session.add(settings)
    db_session.add(
        PrintSettings(
            organisation_id=organisation.id,
            organization_name="Organisation Test",
            req_titre_officiel="Bon de requisition",
        )
    )

    req = await _create_requisition(
        db_session,
        organisation_id=organisation.id,
        service_id=service.id,
        created_by=creator.id,
    )
    upload_root = Path("/tmp") / f"req-tests-{uuid.uuid4().hex}"
    monkeypatch.setattr(official_pdf_service, "UPLOAD_ROOT", str(upload_root))
    monkeypatch.setattr(requisitions_endpoint, "UPLOAD_ROOT", str(upload_root))
    official_pdf_path = upload_root / "requisitions" / f"{req.numero_requisition}.pdf"
    official_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    official_pdf_path.write_bytes(b"%PDF-1.4\n% test pdf\n")
    req.pdf_path = f"/uploads/requisitions/{official_pdf_path.name}"
    req.examen_par = examiner.id
    req.examen_status = "EXAMINE"
    await db_session.commit()

    monkeypatch.setattr(
        requisitions_endpoint,
        "resolve_smtp_config",
        lambda ns: type(
            "SMTPConfigStub",
            (),
            {
                "host": "smtp.example.com",
                "port": 465,
                "user": "noreply@example.com",
                "password": "secret",
                "sender": "noreply@example.com",
            },
        )(),
    )

    background_tasks = BackgroundTasks()
    await requisitions_endpoint._schedule_bureau_notifications(
        db=db_session,
        background_tasks=background_tasks,
        req=req,
        action_user=action_user,
    )

    president_task = next(task for task in background_tasks.tasks if task.func.__name__ == "send_requisition_notification")
    validation_task = next(task for task in background_tasks.tasks if task.func.__name__ == "send_requisition_workflow_email")

    assert president_task.kwargs["examinateur"] == "Claire Examinateur"
    assert "Examinée par : Claire Examinateur" in validation_task.kwargs["body_lines"]
    assert "Examinée par : Bob Soumetteur" not in validation_task.kwargs["body_lines"]
    assert req.pdf_path is not None
    assert Path(president_task.kwargs["official_pdf_path"]).exists()


@pytest.mark.asyncio
async def test_schedule_examen_submission_notification_uses_validation_email(db_session, monkeypatch):
    organisation, service = await _seed_service_context(db_session)
    creator = User(
        id=uuid.uuid4(),
        email=f"creator-{uuid.uuid4().hex[:8]}@example.com",
        nom="Createur",
        prenom="Alice",
        role="admin",
        organisation_id=organisation.id,
    )
    action_user = User(
        id=uuid.uuid4(),
        email=f"action-{uuid.uuid4().hex[:8]}@example.com",
        nom="Soumetteur",
        prenom="Bob",
        role="admin",
        organisation_id=organisation.id,
    )
    db_session.add_all([creator, action_user])
    db_session.add(
        SystemSettings(
            organisation_id=organisation.id,
            email_expediteur="noreply@example.com",
            email_validation_1="validation@example.com",
            smtp_host="smtp.example.com",
            smtp_port=465,
            smtp_password="secret",
        )
    )
    await db_session.flush()

    req = await _create_requisition(
        db_session,
        organisation_id=organisation.id,
        service_id=service.id,
        created_by=creator.id,
    )
    req.examen_status = "EN_EXAMEN"
    await db_session.commit()

    monkeypatch.setattr(
        requisitions_endpoint,
        "resolve_smtp_config",
        lambda ns: type(
            "SMTPConfigStub",
            (),
            {
                "host": "smtp.example.com",
                "port": 465,
                "user": "noreply@example.com",
                "password": "secret",
                "sender": "noreply@example.com",
            },
        )(),
    )

    background_tasks = BackgroundTasks()
    await requisitions_endpoint._schedule_examen_submission_notification(
        db=db_session,
        background_tasks=background_tasks,
        req=req,
        action_user=action_user,
    )

    assert len(background_tasks.tasks) == 1
    task = background_tasks.tasks[0]
    assert task.func.__name__ == "send_requisition_workflow_email"
    assert task.kwargs["recipient"] == "validation@example.com"
    assert task.kwargs["subject"] == f"Réquisition soumise à l'examen - {req.numero_requisition}"
    assert "Une réquisition vient d'être soumise à l'examen dans ONEC Smart." in task.kwargs["body_lines"]
    assert "Demandeur : Alice Createur" in task.kwargs["body_lines"]


@pytest.mark.asyncio
async def test_schedule_bureau_notifications_skips_without_official_pdf(db_session, monkeypatch):
    organisation, service = await _seed_service_context(db_session)
    action_user = User(
        id=uuid.uuid4(),
        email=f"action-{uuid.uuid4().hex[:8]}@example.com",
        nom="Soumetteur",
        prenom="Bob",
        role="admin",
        organisation_id=organisation.id,
    )
    db_session.add(action_user)
    await db_session.flush()

    settings = SystemSettings(
        organisation_id=organisation.id,
        email_expediteur="noreply@example.com",
        email_president="president@example.com",
        email_validation_1="validation@example.com",
        smtp_host="smtp.example.com",
        smtp_port=465,
        smtp_password="secret",
    )
    db_session.add(settings)
    db_session.add(
        PrintSettings(
            organisation_id=organisation.id,
            organization_name="Organisation Test",
            req_titre_officiel="Bon de requisition",
        )
    )

    req = await _create_requisition(
        db_session,
        organisation_id=organisation.id,
        service_id=service.id,
        created_by=action_user.id,
    )
    req.examen_status = "EXAMINE"
    upload_root = Path("/tmp") / f"req-tests-{uuid.uuid4().hex}"
    monkeypatch.setattr(official_pdf_service, "UPLOAD_ROOT", str(upload_root))
    monkeypatch.setattr(requisitions_endpoint, "UPLOAD_ROOT", str(upload_root))
    official_pdf_path = upload_root / "requisitions" / f"{req.numero_requisition}.pdf"
    official_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    official_pdf_path.write_bytes(b"%PDF-1.4\n% test pdf\n")
    req.pdf_path = f"/uploads/requisitions/{official_pdf_path.name}"
    await db_session.commit()

    monkeypatch.setattr(
        requisitions_endpoint,
        "resolve_smtp_config",
        lambda ns: type(
            "SMTPConfigStub",
            (),
            {
                "host": "smtp.example.com",
                "port": 465,
                "user": "noreply@example.com",
                "password": "secret",
                "sender": "noreply@example.com",
            },
        )(),
    )

    background_tasks = BackgroundTasks()
    await requisitions_endpoint._schedule_bureau_notifications(
        db=db_session,
        background_tasks=background_tasks,
        req=req,
        action_user=action_user,
    )

    assert len(background_tasks.tasks) == 2
    assert req.pdf_path is not None


@pytest.mark.asyncio
async def test_create_requisition_logic_generates_official_pdf(db_session, monkeypatch):
    organisation, service = await _seed_service_context(db_session)
    user = User(
        id=uuid.uuid4(),
        email=f"creator-{uuid.uuid4().hex[:8]}@example.com",
        nom="Auteur",
        prenom="Alice",
        role="admin",
        organisation_id=organisation.id,
    )
    db_session.add(user)
    db_session.add(
        PrintSettings(
            organisation_id=organisation.id,
            organization_name="Organisation Test",
            req_titre_officiel="Bon de requisition",
        )
    )
    await db_session.commit()

    upload_root = Path("/tmp") / f"req-tests-{uuid.uuid4().hex}"
    monkeypatch.setattr(official_pdf_service, "UPLOAD_ROOT", str(upload_root))

    req = await create_requisition_logic(
        db=db_session,
        payload=RequisitionCreate(
            objet="Achat de fournitures",
            mode_paiement="cash",
            type_requisition="classique",
            montant_total=Decimal("125.00"),
            service_id=service.id,
            created_by=user.id,
        ),
        user=user,
        tenant_id=organisation.id,
    )

    assert req.pdf_path is None
    assert req.organisation_id == organisation.id
    assert req.service_id == service.id


@pytest.mark.asyncio
async def test_create_remboursement_transport_generates_official_pdf(db_session, monkeypatch):
    organisation, service = await _seed_service_context(db_session)
    user = User(
        id=uuid.uuid4(),
        email=f"creator-{uuid.uuid4().hex[:8]}@example.com",
        nom="Auteur",
        prenom="Alice",
        role="admin",
        organisation_id=organisation.id,
    )
    db_session.add(user)
    db_session.add(
        PrintSettings(
            organisation_id=organisation.id,
            organization_name="Organisation Test",
            trans_titre_officiel="Ordre de remboursement transport",
        )
    )
    await db_session.commit()

    req = await create_requisition_logic(
        db=db_session,
        payload=RequisitionCreate(
            objet="Remboursement mission",
            mode_paiement="cash",
            type_requisition="remboursement_transport",
            montant_total=Decimal("80.00"),
            service_id=service.id,
            created_by=user.id,
        ),
        user=user,
        tenant_id=organisation.id,
    )

    upload_root = Path("/tmp") / f"remb-tests-{uuid.uuid4().hex}"
    monkeypatch.setattr(official_pdf_service, "UPLOAD_ROOT", str(upload_root))
    monkeypatch.setattr(remboursements_endpoint, "UPLOAD_ROOT", str(upload_root))

    response = await remboursements_endpoint.create_remboursement_transport(
        payload=RemboursementTransportCreate(
            instance="CPK",
            type_reunion="commission",
            nature_reunion="Mission",
            nature_travail=["Controle"],
            lieu="Kinshasa",
            date_reunion=datetime.now(timezone.utc),
            heure_debut="08:00",
            heure_fin="10:00",
            montant_total=Decimal("80.00"),
            requisition_id=req.id,
            created_by=user.id,
        ),
        user=user,
        db=db_session,
        tenant_id=organisation.id,
    )

    assert response.pdf_path is not None
    saved_pdf = upload_root / Path(response.pdf_path.replace("/uploads/", ""))
    assert saved_pdf.exists()


@pytest.mark.asyncio
async def test_submit_requisition_examen_rejects_dossier_bound(db_session):
    organisation, service = await _seed_service_context(db_session)
    dossier = DossierRequisition(
        organisation_id=organisation.id,
        reference=f"DOS-{uuid.uuid4().hex[:8]}",
        status="BROUILLON",
    )
    db_session.add(dossier)
    await db_session.flush()
    req = await _create_requisition(
        db_session,
        organisation_id=organisation.id,
        service_id=service.id,
        dossier_id=dossier.id,
        signed_by_id=uuid.uuid4(),
        signed_at=_utcnow(),
    )
    await _add_line(db_session, req.id)

    with pytest.raises(HTTPException) as exc_info:
        await submit_requisition_examen_logic(
            db=db_session,
            requisition_id=req.id,
            tenant_id=organisation.id,
        )

    assert exc_info.value.status_code == 400
    assert "rattachée à un dossier" in exc_info.value.detail


@pytest.mark.asyncio
async def test_validate_requisition_examen_requires_en_examen(db_session):
    organisation, service = await _seed_service_context(db_session)
    user = await _create_admin_user(db_session, organisation.id)
    req = await _create_requisition(
        db_session,
        organisation_id=organisation.id,
        service_id=service.id,
        examen_status="NON_EXAMINE",
    )
    await _add_line(db_session, req.id)

    with pytest.raises(HTTPException) as exc_info:
        await validate_requisition_examen_logic(
            db=db_session,
            requisition_id=req.id,
            payload=RequisitionExamenPayload(commentaire=None),
            user=user,
            tenant_id=organisation.id,
        )

    assert exc_info.value.status_code == 400
    assert "doit être en examen" in exc_info.value.detail


@pytest.mark.asyncio
async def test_reject_requisition_examen_requires_en_examen(db_session):
    organisation, service = await _seed_service_context(db_session)
    user = await _create_admin_user(db_session, organisation.id)
    req = await _create_requisition(
        db_session,
        organisation_id=organisation.id,
        service_id=service.id,
        examen_status="EXAMINE",
    )
    await _add_line(db_session, req.id)

    with pytest.raises(HTTPException) as exc_info:
        await reject_requisition_examen_logic(
            db=db_session,
            requisition_id=req.id,
            payload=RequisitionExamenPayload(commentaire="Retour"),
            user=user,
            tenant_id=organisation.id,
        )

    assert exc_info.value.status_code == 400
    assert "doit être en examen" in exc_info.value.detail


@pytest.mark.asyncio
async def test_validate_dossier_examen_requires_dossier_en_examen(db_session):
    organisation, service = await _seed_service_context(db_session)
    user = await _create_admin_user(db_session, organisation.id)
    dossier = DossierRequisition(
        organisation_id=organisation.id,
        reference=f"DOS-{uuid.uuid4().hex[:8]}",
        status="BROUILLON",
    )
    db_session.add(dossier)
    await db_session.flush()
    req = await _create_requisition(
        db_session,
        organisation_id=organisation.id,
        service_id=service.id,
        dossier_id=dossier.id,
        examen_status="EN_EXAMEN",
    )
    await _add_line(db_session, req.id)

    with pytest.raises(HTTPException) as exc_info:
        await dossiers_endpoint.validate_examen_dossier(
            dossier_id=str(dossier.id),
            payload=DossierRequisitionUpdate(commentaires_examen=None),
            background_tasks=BackgroundTasks(),
            db=db_session,
            user=user,
            tenant_id=organisation.id,
        )

    assert exc_info.value.status_code == 400
    assert "dossier doit être en examen" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_reject_dossier_examen_requires_child_requisitions_en_examen(db_session):
    organisation, service = await _seed_service_context(db_session)
    user = await _create_admin_user(db_session, organisation.id)
    dossier = DossierRequisition(
        organisation_id=organisation.id,
        reference=f"DOS-{uuid.uuid4().hex[:8]}",
        status="EN_EXAMEN",
    )
    db_session.add(dossier)
    await db_session.flush()
    req = await _create_requisition(
        db_session,
        organisation_id=organisation.id,
        service_id=service.id,
        dossier_id=dossier.id,
        examen_status="EXAMINE",
    )
    await _add_line(db_session, req.id)

    with pytest.raises(HTTPException) as exc_info:
        await dossiers_endpoint.reject_examen_dossier(
            dossier_id=str(dossier.id),
            payload=DossierRequisitionUpdate(commentaires_examen="Incohérent"),
            db=db_session,
            user=user,
            tenant_id=organisation.id,
        )

    assert exc_info.value.status_code == 400
    assert "réquisitions du dossier doivent être en examen" in exc_info.value.detail


@pytest.mark.asyncio
async def test_submit_requisition_examen_rejects_without_lines(db_session):
    organisation, service = await _seed_service_context(db_session)
    req = await _create_requisition(
        db_session,
        organisation_id=organisation.id,
        service_id=service.id,
        signed_by_id=uuid.uuid4(),
        signed_at=_utcnow(),
    )
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await submit_requisition_examen_logic(
            db=db_session,
            requisition_id=req.id,
            tenant_id=organisation.id,
        )

    assert exc_info.value.status_code == 400
    assert "Aucune ligne de réquisition" in exc_info.value.detail


@pytest.mark.asyncio
async def test_submit_requisition_examen_rejects_without_signer(db_session):
    organisation, service = await _seed_service_context(db_session)
    req = await _create_requisition(
        db_session,
        organisation_id=organisation.id,
        service_id=service.id,
        signed_at=_utcnow(),
    )
    await _add_line(db_session, req.id)

    with pytest.raises(HTTPException) as exc_info:
        await submit_requisition_examen_logic(
            db=db_session,
            requisition_id=req.id,
            tenant_id=organisation.id,
        )

    assert exc_info.value.status_code == 400
    assert "doit être signée" in exc_info.value.detail


@pytest.mark.asyncio
async def test_submit_requisition_examen_rejects_without_signed_at(db_session):
    organisation, service = await _seed_service_context(db_session)
    req = await _create_requisition(
        db_session,
        organisation_id=organisation.id,
        service_id=service.id,
        signed_by_id=uuid.uuid4(),
    )
    await _add_line(db_session, req.id)

    with pytest.raises(HTTPException) as exc_info:
        await submit_requisition_examen_logic(
            db=db_session,
            requisition_id=req.id,
            tenant_id=organisation.id,
        )

    assert exc_info.value.status_code == 400
    assert "date de signature" in exc_info.value.detail


@pytest.mark.asyncio
async def test_sign_requisition_rejects_without_lines(db_session):
    organisation, service = await _seed_service_context(db_session)
    signer = User(
        id=uuid.uuid4(),
        email=f"signer-{uuid.uuid4().hex[:8]}@example.com",
        role="admin",
        organisation_id=organisation.id,
    )
    db_session.add(signer)
    req = await _create_requisition(
        db_session,
        organisation_id=organisation.id,
        service_id=service.id,
        status="BROUILLON",
        signed_by_id=None,
        signed_at=None,
    )
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await sign_commission_requisition_logic(
            db=db_session,
            requisition_id=req.id,
            user=signer,
            tenant_id=organisation.id,
        )

    assert exc_info.value.status_code == 400
    assert "Aucune ligne de réquisition" in exc_info.value.detail


@pytest.mark.asyncio
async def test_reject_requisition_at_payment_ok(db_session):
    organisation, service = await _seed_service_context(db_session)
    admin = await _create_admin_user(db_session, organisation.id)
    req = await _create_requisition(
        db_session,
        organisation_id=organisation.id,
        service_id=service.id,
        status="APPROUVEE",
        signed_by_id=uuid.uuid4(),
        signed_at=_utcnow(),
    )
    req.approuvee_par = admin.id
    req.approuvee_le = _utcnow()
    await db_session.commit()

    result = await reject_requisition_at_payment_logic(
        db=db_session,
        requisition_id=req.id,
        user=admin,
        tenant_id=organisation.id,
        motif_rejet="Dossier incomplet pour paiement",
    )

    assert result.status == "REJETEE"
    assert result.motif_rejet == "Dossier incomplet pour paiement"
    assert result.approuvee_par == admin.id


@pytest.mark.asyncio
async def test_reject_requisition_at_payment_rejects_non_approved_status(db_session):
    organisation, service = await _seed_service_context(db_session)
    admin = await _create_admin_user(db_session, organisation.id)
    req = await _create_requisition(
        db_session,
        organisation_id=organisation.id,
        service_id=service.id,
        status="AUTORISEE",
        signed_by_id=uuid.uuid4(),
        signed_at=_utcnow(),
    )
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await reject_requisition_at_payment_logic(
            db=db_session,
            requisition_id=req.id,
            user=admin,
            tenant_id=organisation.id,
            motif_rejet="Non conforme",
        )

    assert exc_info.value.status_code == 400
    assert "approuvées" in exc_info.value.detail


@pytest.mark.asyncio
async def test_reject_requisition_at_payment_rejects_when_active_sortie_exists(db_session):
    organisation, service = await _seed_service_context(db_session)
    admin = await _create_admin_user(db_session, organisation.id)
    req = await _create_requisition(
        db_session,
        organisation_id=organisation.id,
        service_id=service.id,
        status="APPROUVEE",
        signed_by_id=uuid.uuid4(),
        signed_at=_utcnow(),
    )
    db_session.add(
        SortieFonds(
            type_sortie="requisition",
            organisation_id=organisation.id,
            requisition_id=req.id,
            budget_poste_id=None,
            montant_paye=Decimal("100.00"),
            date_paiement=_utcnow(),
            mode_paiement="cash",
            devise="USD",
            canal="CAISSE",
            statut="VALIDE",
            motif="Paiement",
            beneficiaire="Bénéficiaire test",
            created_by=admin.id,
        )
    )
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await reject_requisition_at_payment_logic(
            db=db_session,
            requisition_id=req.id,
            user=admin,
            tenant_id=organisation.id,
            motif_rejet="Déjà en paiement",
        )

    assert exc_info.value.status_code == 400
    assert "sortie de fonds existe déjà" in exc_info.value.detail


@pytest.mark.asyncio
async def test_reject_requisition_at_payment_cancels_draft_sortie(db_session):
    organisation, service = await _seed_service_context(db_session)
    admin = await _create_admin_user(db_session, organisation.id)
    req = await _create_requisition(
        db_session,
        organisation_id=organisation.id,
        service_id=service.id,
        status="APPROUVEE",
        signed_by_id=uuid.uuid4(),
        signed_at=_utcnow(),
    )
    draft = SortieFonds(
        type_sortie="requisition",
        organisation_id=organisation.id,
        requisition_id=req.id,
        budget_poste_id=None,
        montant_paye=Decimal("100.00"),
        date_paiement=_utcnow(),
        mode_paiement="cash",
        devise="USD",
        canal="CAISSE",
        statut="BROUILLON",
        motif="Paiement",
        beneficiaire="Bénéficiaire test",
        created_by=admin.id,
    )
    db_session.add(draft)
    await db_session.commit()

    result = await reject_requisition_at_payment_logic(
        db=db_session,
        requisition_id=req.id,
        user=admin,
        tenant_id=organisation.id,
        motif_rejet="Pièces insuffisantes",
    )

    assert result.status == "REJETEE"
    await db_session.refresh(draft)
    assert draft.statut == "ANNULEE"
    assert draft.ancien_statut == "BROUILLON"
    assert draft.annulee_par_id == admin.id
    assert "Pièces insuffisantes" in (draft.motif_annulation or "")


@pytest.mark.asyncio
async def test_requisition_non_examinee_reste_modifiable(db_session):
    """Corriger une réquisition qui attend encore son examen doit rester possible.

    L'examen conditionne le passage en validation, pas la correction de la
    pièce : l'exiger sur toute mise à jour enfermait le rédacteur dans une
    réquisition qu'il ne pouvait ni faire avancer ni amender.
    """
    from app.services.requisition_service import update_requisition_logic
    from app.schemas.requisition import RequisitionUpdate

    organisation, service = await _seed_service_context(db_session)
    user = await _create_admin_user(db_session, organisation.id)
    req = await _create_requisition(
        db_session,
        organisation_id=organisation.id,
        service_id=service.id,
        status="BROUILLON",
        examen_status="NON_EXAMINE",
    )
    # Circuit avec examen actif : c'est le cas qui bloquait.
    req.workflow_snapshot = {"steps": {"examen": {"enabled": True}}}
    await _add_line(db_session, req.id)

    modifiee = await update_requisition_logic(
        db=db_session,
        requisition_id=req.id,
        payload=RequisitionUpdate(objet="Objet corrigé avant examen"),
        user=user,
        tenant_id=organisation.id,
    )
    assert modifiee.objet == "Objet corrigé avant examen"
    assert modifiee.examen_status == "NON_EXAMINE"


@pytest.mark.asyncio
async def test_passage_en_validation_exige_toujours_l_examen(db_session):
    """Le garde-fou reste entier là où il a un sens : à l'entrée en validation."""
    from app.services.requisition_service import update_requisition_logic
    from app.schemas.requisition import RequisitionUpdate

    organisation, service = await _seed_service_context(db_session)
    user = await _create_admin_user(db_session, organisation.id)
    req = await _create_requisition(
        db_session,
        organisation_id=organisation.id,
        service_id=service.id,
        status="BROUILLON",
        examen_status="NON_EXAMINE",
    )
    req.workflow_snapshot = {"steps": {"examen": {"enabled": True}}}
    await _add_line(db_session, req.id)

    with pytest.raises(HTTPException) as exc:
        await update_requisition_logic(
            db=db_session,
            requisition_id=req.id,
            payload=RequisitionUpdate(status="APPROUVEE"),
            user=user,
            tenant_id=organisation.id,
        )
    assert exc.value.status_code == 400
    assert "Examen requis" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_requisition_modifiable_quand_l_examen_est_desactive(db_session):
    """Circuit sans examen : la pièce se modifie et s'approuve sans blocage."""
    from app.services.requisition_service import update_requisition_logic
    from app.schemas.requisition import RequisitionUpdate

    organisation, service = await _seed_service_context(db_session)
    user = await _create_admin_user(db_session, organisation.id)
    req = await _create_requisition(
        db_session,
        organisation_id=organisation.id,
        service_id=service.id,
        status="BROUILLON",
        examen_status="NON_EXAMINE",
    )
    req.workflow_snapshot = {"steps": {"examen": {"enabled": False}}}
    await _add_line(db_session, req.id)

    modifiee = await update_requisition_logic(
        db=db_session,
        requisition_id=req.id,
        payload=RequisitionUpdate(objet="Objet corrigé sans examen"),
        user=user,
        tenant_id=organisation.id,
    )
    assert modifiee.objet == "Objet corrigé sans examen"
