from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from textwrap import wrap

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from sqlalchemy import select

from app.core.config import settings
from app.db.session import get_db
from app.models.ligne_requisition import LigneRequisition
from app.models.organisation import Organisation
from app.models.requisition import Requisition
from app.models.remboursement_transport import ParticipantTransport, RemboursementTransport
from app.models.service import Service
from app.models.user import User


UPLOAD_ROOT = Path(settings.upload_dir or "./app/uploads").resolve()


def _safe_ref(value: str, fallback: str) -> str:
    raw = (value or fallback).strip()
    cleaned = []
    for char in raw:
        if char.isalnum() or char in {"-", "_", "."}:
            cleaned.append(char)
        else:
            cleaned.append("-")
    result = "".join(cleaned).strip("-. _")
    return result or fallback


def _tenant_dir(tenant_uuid: uuid.UUID | str, *parts: str) -> Path:
    return UPLOAD_ROOT / "tenants" / str(tenant_uuid) / Path(*parts)


def _money(value: Decimal | float | int | None, suffix: str = "USD") -> str:
    amount = float(value or 0)
    return f"{amount:,.2f} {suffix}".replace(",", " ")


def _user_name(user: User | None) -> str:
    if not user:
        return "N/A"
    full_name = f"{user.prenom or ''} {user.nom or ''}".strip()
    return full_name or user.email or "N/A"


def _draw_wrapped_text(pdf: canvas.Canvas, text: str, x: float, y: float, width: int, line_height: float = 12) -> float:
    lines = wrap(text or "-", width=width) or ["-"]
    for line in lines:
        pdf.drawString(x, y, line)
        y -= line_height
    return y


def _create_requisition_pdf(
    *,
    file_path: Path,
    organisation_name: str,
    requisition: Requisition,
    service: Service | None,
    demandeur: User | None,
    lignes: list[LigneRequisition],
) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(file_path), pagesize=A4)
    width, height = A4

    y = height - 2.5 * cm
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(2 * cm, y, organisation_name)
    y -= 0.8 * cm
    pdf.setFont("Helvetica-Bold", 15)
    pdf.drawCentredString(width / 2, y, "BON DE REQUISITION DE FONDS")
    y -= 1 * cm

    pdf.setFont("Helvetica", 10)
    pdf.drawString(2 * cm, y, f"Numero : {requisition.numero_requisition}")
    pdf.drawRightString(width - 2 * cm, y, f"Date : {requisition.created_at.strftime('%d/%m/%Y')}")
    y -= 0.6 * cm
    pdf.drawString(2 * cm, y, f"Type : {requisition.type_requisition}")
    pdf.drawRightString(width - 2 * cm, y, f"Statut examen : {requisition.examen_status}")
    y -= 0.6 * cm
    pdf.drawString(2 * cm, y, f"Demandeur : {_user_name(demandeur)}")
    y -= 0.6 * cm
    pdf.drawString(2 * cm, y, f"Service : {service.code + ' - ' + service.libelle if service else 'N/A'}")
    y -= 0.8 * cm

    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(2 * cm, y, "Objet")
    y -= 0.5 * cm
    pdf.setFont("Helvetica", 10)
    y = _draw_wrapped_text(pdf, requisition.objet or "-", 2 * cm, y, width=95)
    y -= 0.5 * cm

    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(2 * cm, y, "Lignes")
    y -= 0.6 * cm
    pdf.line(2 * cm, y, width - 2 * cm, y)
    y -= 0.5 * cm

    for index, ligne in enumerate(lignes or [], start=1):
        if y < 4 * cm:
            pdf.showPage()
            y = height - 2.5 * cm
            pdf.setFont("Helvetica", 10)
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(2 * cm, y, f"{index}. {ligne.rubrique}")
        pdf.setFont("Helvetica", 9)
        pdf.drawRightString(width - 2 * cm, y, _money(ligne.montant_total, ligne.devise or "USD"))
        y -= 0.45 * cm
        y = _draw_wrapped_text(pdf, ligne.description or "-", 2.3 * cm, y, width=100, line_height=10)
        pdf.drawString(2.3 * cm, y, f"Quantite : {ligne.quantite} | PU : {_money(ligne.montant_unitaire, ligne.devise or 'USD')}")
        y -= 0.7 * cm

    if not lignes:
        pdf.setFont("Helvetica", 9)
        pdf.drawString(2 * cm, y, "Aucune ligne de requisition")
        y -= 0.7 * cm

    if y < 4 * cm:
        pdf.showPage()
        y = height - 4 * cm

    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawRightString(width - 2 * cm, y, f"Montant total : {_money(requisition.montant_total)}")
    y -= 1.5 * cm
    pdf.setFont("Helvetica", 10)
    pdf.drawString(2 * cm, y, "Etabli par")
    pdf.drawRightString(width - 2 * cm, y, "Approuve par")
    y -= 1.2 * cm
    pdf.line(2 * cm, y, 7 * cm, y)
    pdf.line(width - 7 * cm, y, width - 2 * cm, y)
    pdf.save()


def _create_remboursement_pdf(
    *,
    file_path: Path,
    organisation_name: str,
    remboursement: RemboursementTransport,
    requisition: Requisition | None,
    service: Service | None,
    participants: list[ParticipantTransport],
) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(file_path), pagesize=A4)
    width, height = A4

    y = height - 2.5 * cm
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(2 * cm, y, organisation_name)
    y -= 0.8 * cm
    pdf.setFont("Helvetica-Bold", 15)
    pdf.drawCentredString(width / 2, y, "ETAT DE FRAIS DE DEPLACEMENT")
    y -= 1 * cm

    pdf.setFont("Helvetica", 10)
    pdf.drawString(2 * cm, y, f"Numero : {remboursement.numero_remboursement}")
    pdf.drawRightString(width - 2 * cm, y, f"Date reunion : {remboursement.date_reunion.strftime('%d/%m/%Y')}")
    y -= 0.6 * cm
    pdf.drawString(2 * cm, y, f"Nature : {remboursement.nature_reunion}")
    y -= 0.6 * cm
    pdf.drawString(2 * cm, y, f"Lieu : {remboursement.lieu}")
    y -= 0.6 * cm
    pdf.drawString(2 * cm, y, f"Service : {service.code + ' - ' + service.libelle if service else 'N/A'}")
    y -= 0.6 * cm
    pdf.drawString(2 * cm, y, f"Requisition associee : {requisition.numero_requisition if requisition else 'N/A'}")
    y -= 0.9 * cm

    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(2 * cm, y, "Participants")
    y -= 0.6 * cm
    pdf.line(2 * cm, y, width - 2 * cm, y)
    y -= 0.5 * cm

    if participants:
        for index, participant in enumerate(participants, start=1):
            if y < 4 * cm:
                pdf.showPage()
                y = height - 2.5 * cm
                pdf.setFont("Helvetica", 10)
            pdf.setFont("Helvetica-Bold", 9)
            pdf.drawString(2 * cm, y, f"{index}. {participant.nom}")
            pdf.setFont("Helvetica", 9)
            pdf.drawString(8.5 * cm, y, participant.titre_fonction or "-")
            pdf.drawRightString(width - 2 * cm, y, _money(participant.montant))
            y -= 0.6 * cm
    else:
        pdf.setFont("Helvetica", 9)
        pdf.drawString(2 * cm, y, "Aucun participant enregistre")
        y -= 0.6 * cm

    if y < 4 * cm:
        pdf.showPage()
        y = height - 4 * cm

    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawRightString(width - 2 * cm, y, f"Montant total : {_money(remboursement.montant_total)}")
    y -= 1.5 * cm
    pdf.setFont("Helvetica", 10)
    pdf.drawString(2 * cm, y, "Vu par la Tresorerie")
    pdf.drawRightString(width - 2 * cm, y, "Approuve par")
    y -= 1.2 * cm
    pdf.line(2 * cm, y, 7 * cm, y)
    pdf.line(width - 7 * cm, y, width - 2 * cm, y)
    pdf.save()


async def main() -> None:
    async for db in get_db():
        org_rows = await db.execute(select(Organisation))
        organisations = {org.id: org for org in org_rows.scalars().all()}

        req_rows = await db.execute(select(Requisition).where(Requisition.pdf_path.is_(None), Requisition.is_deleted.is_(False)))
        requisitions = req_rows.scalars().all()

        generated_req = 0
        for req in requisitions:
            org = organisations.get(req.organisation_id)
            if not org:
                continue
            service = None
            if req.service_id:
                service = (await db.execute(select(Service).where(Service.id == req.service_id))).scalar_one_or_none()
            demandeur = None
            if req.created_by:
                demandeur = (await db.execute(select(User).where(User.id == req.created_by))).scalar_one_or_none()
            lignes = (
                await db.execute(
                    select(LigneRequisition)
                    .where(LigneRequisition.requisition_id == req.id)
                    .order_by(LigneRequisition.id.asc())
                )
            ).scalars().all()

            safe_ref = _safe_ref(req.numero_requisition or str(req.id), "REQ")
            target = _tenant_dir(org.uuid, "requisitions", f"{req.created_at.year:04d}", f"{req.created_at.month:02d}", f"{safe_ref}-bon.pdf")
            _create_requisition_pdf(
                file_path=target,
                organisation_name=org.nom,
                requisition=req,
                service=service,
                demandeur=demandeur,
                lignes=lignes,
            )
            rel_path = f"/uploads/tenants/{org.uuid}/requisitions/{req.created_at.year:04d}/{req.created_at.month:02d}/{safe_ref}-bon.pdf"
            req.pdf_path = rel_path
            generated_req += 1

        remb_rows = await db.execute(select(RemboursementTransport).where(RemboursementTransport.pdf_path.is_(None)))
        remboursements = remb_rows.scalars().all()

        generated_remb = 0
        for remb in remboursements:
            requisition = None
            org = None
            service = None
            if remb.requisition_id:
                requisition = (
                    await db.execute(select(Requisition).where(Requisition.id == remb.requisition_id))
                ).scalar_one_or_none()
                if requisition:
                    org = organisations.get(requisition.organisation_id)
                    if requisition.service_id:
                        service = (await db.execute(select(Service).where(Service.id == requisition.service_id))).scalar_one_or_none()
            if not org:
                continue
            participants = (
                await db.execute(
                    select(ParticipantTransport)
                    .where(ParticipantTransport.remboursement_id == remb.id)
                    .order_by(ParticipantTransport.created_at.asc())
                )
            ).scalars().all()
            safe_ref = _safe_ref(remb.reference_numero or remb.numero_remboursement or str(remb.id), "REM")
            target = _tenant_dir(org.uuid, "remboursements-transport", f"{remb.created_at.year:04d}", f"{remb.created_at.month:02d}", f"{safe_ref}.pdf")
            _create_remboursement_pdf(
                file_path=target,
                organisation_name=org.nom,
                remboursement=remb,
                requisition=requisition,
                service=service,
                participants=participants,
            )
            rel_path = f"/uploads/tenants/{org.uuid}/remboursements-transport/{remb.created_at.year:04d}/{remb.created_at.month:02d}/{safe_ref}.pdf"
            remb.pdf_path = rel_path
            generated_remb += 1

        await db.commit()
        print(f"Backfill termine: {generated_req} requisitions, {generated_remb} remboursements.")
        break


if __name__ == "__main__":
    asyncio.run(main())
