from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.ligne_requisition import LigneRequisition
from app.models.organisation import Organisation
from app.models.print_settings import PrintSettings
from app.models.remboursement_transport import ParticipantTransport, RemboursementTransport
from app.models.requisition import Requisition
from app.models.service import Service
from app.models.user import User


DEFAULT_UPLOAD_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "uploads")
)
UPLOAD_ROOT = os.path.abspath(settings.upload_dir) if settings.upload_dir else DEFAULT_UPLOAD_ROOT


@dataclass
class PdfGenerationResult:
    storage_path: str
    absolute_path: str


def _safe_ref(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "")
    normalized = normalized.strip("._-")
    return normalized or fallback


def _format_money(value: Decimal | float | int | None, currency: str = "USD") -> str:
    amount = Decimal(value or 0)
    formatted = f"{amount:,.2f}".replace(",", " ").replace(".", ",")
    return f"{formatted} {currency}"


def _tenant_dir(tenant_uuid: uuid.UUID | str, *parts: str) -> str:
    return os.path.join(UPLOAD_ROOT, "tenants", str(tenant_uuid), *parts)


def _wrap_text(pdf: canvas.Canvas, text: str, max_width: float, *, font: str, font_size: int) -> list[str]:
    text = " ".join((text or "").split())
    if not text:
        return [""]
    words = text.split(" ")
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if pdf.stringWidth(candidate, font, font_size) <= max_width:
            current = candidate
            continue
        lines.append(current)
        current = word
    lines.append(current)
    return lines


def _draw_wrapped_line(
    pdf: canvas.Canvas,
    text: str,
    *,
    x: float,
    y: float,
    max_width: float,
    font: str = "Helvetica",
    font_size: int = 10,
    leading: float = 14,
) -> float:
    pdf.setFont(font, font_size)
    current_y = y
    for line in _wrap_text(pdf, text, max_width, font=font, font_size=font_size):
        pdf.drawString(x, current_y, line)
        current_y -= leading
    return current_y


def _render_header(
    pdf: canvas.Canvas,
    *,
    title: str,
    organisation_name: str,
    subtitle: str | None,
    reference: str,
    created_at_label: str,
    print_settings: PrintSettings | None,
) -> float:
    top_y = A4[1] - 2 * cm
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(2 * cm, top_y, organisation_name or "Organisation")
    pdf.setFont("Helvetica", 10)
    subtitle_text = subtitle or ""
    if print_settings:
        contact_parts = [
            print_settings.address or "",
            print_settings.phone or "",
            print_settings.email or "",
        ]
        contact_text = " | ".join(part for part in contact_parts if part)
        if contact_text:
            pdf.drawString(2 * cm, top_y - 0.5 * cm, contact_text)
    if subtitle_text:
        pdf.drawString(2 * cm, top_y - 1.0 * cm, subtitle_text)

    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(2 * cm, top_y - 2.0 * cm, title)
    pdf.setFont("Helvetica", 10)
    pdf.drawString(2 * cm, top_y - 2.7 * cm, f"Reference : {reference}")
    pdf.drawString(11.5 * cm, top_y - 2.7 * cm, created_at_label)
    pdf.line(2 * cm, top_y - 3.0 * cm, A4[0] - 2 * cm, top_y - 3.0 * cm)
    return top_y - 3.7 * cm


def _finalize_pdf(pdf: canvas.Canvas, buffer: BytesIO) -> bytes:
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


async def _load_print_settings(db: AsyncSession, organisation_id: int) -> PrintSettings | None:
    res = await db.execute(
        select(PrintSettings).where(PrintSettings.organisation_id == organisation_id).limit(1)
    )
    return res.scalar_one_or_none()


async def _load_service_label(db: AsyncSession, service_id: int | None) -> str | None:
    if service_id is None:
        return None
    res = await db.execute(select(Service).where(Service.id == service_id).limit(1))
    service = res.scalar_one_or_none()
    if service is None:
        return None
    return f"{service.code} - {service.libelle}"


async def _load_user_name(db: AsyncSession, user_id: uuid.UUID | None) -> str | None:
    if user_id is None:
        return None
    res = await db.execute(select(User).where(User.id == user_id).limit(1))
    user = res.scalar_one_or_none()
    if user is None:
        return None
    full_name = " ".join(part for part in [user.prenom, user.nom] if part)
    return full_name or user.email


async def _load_org(db: AsyncSession, organisation_id: int) -> Organisation:
    res = await db.execute(select(Organisation).where(Organisation.id == organisation_id).limit(1))
    organisation = res.scalar_one_or_none()
    if organisation is None:
        raise RuntimeError(f"Organisation introuvable pour id={organisation_id}")
    return organisation


def _save_pdf_bytes(*, file_path: str, payload: bytes) -> None:
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "wb") as handle:
        handle.write(payload)


async def generate_requisition_official_pdf(
    db: AsyncSession,
    req: Requisition,
) -> PdfGenerationResult:
    from app.services.requisition_service import apply_snapshot_if_needed

    organisation = await _load_org(db, req.organisation_id)
    await apply_snapshot_if_needed(req, db, req.organisation_id)
    print_settings = await _load_print_settings(db, req.organisation_id)
    lignes_res = await db.execute(
        select(LigneRequisition)
        .where(LigneRequisition.requisition_id == req.id)
        .order_by(LigneRequisition.id.asc())
    )
    lignes = lignes_res.scalars().all()
    service_label = await _load_service_label(db, req.service_id)
    demandeur_name = await _load_user_name(db, req.created_by)

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    title = (
        req.req_titre_officiel_hist
        or (print_settings.req_titre_officiel if print_settings else "")
        or "Bon de requisition"
    )
    y = _render_header(
        pdf,
        title=title,
        organisation_name=(print_settings.organization_name if print_settings else "") or organisation.nom,
        subtitle=print_settings.organization_subtitle if print_settings else organisation.nom,
        reference=req.reference_numero or req.numero_requisition,
        created_at_label=f"Date : {(req.created_at or organisation.created_at).strftime('%d/%m/%Y')}",
        print_settings=print_settings,
    )

    left_x = 2 * cm
    right_x = 11 * cm
    pdf.setFont("Helvetica", 10)
    pdf.drawString(left_x, y, f"Numero : {req.numero_requisition}")
    pdf.drawString(right_x, y, f"Statut : {req.status}")
    y -= 0.6 * cm
    pdf.drawString(left_x, y, f"Mode de paiement : {req.mode_paiement}")
    if service_label:
        pdf.drawString(right_x, y, f"Service : {service_label}")
    y -= 0.6 * cm
    if demandeur_name:
        pdf.drawString(left_x, y, f"Demandeur : {demandeur_name}")
        y -= 0.6 * cm
    y = _draw_wrapped_line(
        pdf,
        f"Objet : {req.objet}",
        x=left_x,
        y=y,
        max_width=A4[0] - 4 * cm,
        font="Helvetica-Bold",
        font_size=10,
        leading=14,
    )
    y -= 0.2 * cm

    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(left_x, y, "Lignes")
    y -= 0.5 * cm
    pdf.setFont("Helvetica", 9)
    if not lignes:
        pdf.drawString(left_x, y, "Aucune ligne de requisition enregistree.")
        y -= 0.5 * cm
    else:
        for idx, ligne in enumerate(lignes, start=1):
            rubrique = ligne.rubrique or ligne.budget_poste_code_snapshot or "-"
            description = ligne.description or "-"
            amount = _format_money(ligne.montant_total, ligne.devise or "USD")
            pdf.drawString(left_x, y, f"{idx}. {rubrique}")
            pdf.drawRightString(A4[0] - 2 * cm, y, amount)
            y -= 0.45 * cm
            y = _draw_wrapped_line(
                pdf,
                description,
                x=left_x + 0.4 * cm,
                y=y,
                max_width=A4[0] - 4.4 * cm,
                font="Helvetica",
                font_size=9,
                leading=12,
            )
            y -= 0.15 * cm
            if y < 5 * cm:
                pdf.showPage()
                y = A4[1] - 2 * cm

    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawRightString(A4[0] - 2 * cm, max(y - 0.4 * cm, 3.6 * cm), f"Total : {_format_money(req.montant_total)}")

    footer_y = 2.8 * cm
    pdf.setFont("Helvetica", 9)
    left_label = req.signataire_g_label or req.req_label_gauche_hist or "Signature gauche"
    left_name = req.signataire_g_nom or req.req_nom_gauche_hist or ""
    right_label = req.signataire_d_label or req.req_label_droite_hist or "Signature droite"
    right_name = req.signataire_d_nom or req.req_nom_droite_hist or ""
    pdf.drawString(2 * cm, footer_y, left_label)
    pdf.drawString(2 * cm, footer_y - 0.5 * cm, left_name)
    pdf.drawString(11 * cm, footer_y, right_label)
    pdf.drawString(11 * cm, footer_y - 0.5 * cm, right_name)

    pdf_bytes = _finalize_pdf(pdf, buffer)
    safe_ref = _safe_ref(req.reference_numero or req.numero_requisition or str(req.id), "REQ")
    timestamp = req.created_at or organisation.created_at
    relative_path = (
        f"/uploads/tenants/{organisation.uuid}/requisitions/"
        f"{timestamp.year:04d}/{timestamp.month:02d}/{safe_ref}-bon.pdf"
    )
    absolute_path = os.path.join(UPLOAD_ROOT, relative_path.replace("/uploads/", "", 1))
    _save_pdf_bytes(file_path=absolute_path, payload=pdf_bytes)
    req.pdf_path = relative_path
    return PdfGenerationResult(storage_path=relative_path, absolute_path=absolute_path)


async def ensure_requisition_official_pdf(
    db: AsyncSession,
    req: Requisition,
    *,
    regenerate: bool = False,
) -> PdfGenerationResult:
    current_path = req.pdf_path
    if current_path and not regenerate:
        fs_path = os.path.join(UPLOAD_ROOT, current_path.replace("/uploads/", "", 1))
        if os.path.exists(fs_path):
            return PdfGenerationResult(storage_path=current_path, absolute_path=fs_path)
    return await generate_requisition_official_pdf(db, req)


async def generate_remboursement_official_pdf(
    db: AsyncSession,
    remboursement: RemboursementTransport,
) -> PdfGenerationResult:
    organisation = await _load_org(db, remboursement.organisation_id)
    print_settings = await _load_print_settings(db, remboursement.organisation_id)
    participants_res = await db.execute(
        select(ParticipantTransport)
        .where(ParticipantTransport.remboursement_id == remboursement.id)
        .order_by(ParticipantTransport.id.asc())
    )
    participants = participants_res.scalars().all()
    created_by_name = await _load_user_name(db, remboursement.created_by)

    if not remboursement.trans_titre_officiel_hist and print_settings:
        remboursement.trans_titre_officiel_hist = print_settings.trans_titre_officiel or None
        remboursement.trans_label_gauche_hist = print_settings.trans_label_gauche or None
        remboursement.trans_nom_gauche_hist = print_settings.trans_nom_gauche or None
        remboursement.trans_label_droite_hist = print_settings.trans_label_droite or None
        remboursement.trans_nom_droite_hist = print_settings.trans_nom_droite or None
        remboursement.signataire_g_label = print_settings.trans_label_gauche or None
        remboursement.signataire_g_nom = print_settings.trans_nom_gauche or None
        remboursement.signataire_d_label = print_settings.trans_label_droite or None
        remboursement.signataire_d_nom = print_settings.trans_nom_droite or None

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    title = (
        remboursement.trans_titre_officiel_hist
        or (print_settings.trans_titre_officiel if print_settings else "")
        or "Remboursement transport"
    )
    y = _render_header(
        pdf,
        title=title,
        organisation_name=(print_settings.organization_name if print_settings else "") or organisation.nom,
        subtitle=print_settings.organization_subtitle if print_settings else organisation.nom,
        reference=remboursement.reference_numero or remboursement.numero_remboursement,
        created_at_label=f"Date : {(remboursement.created_at or organisation.created_at).strftime('%d/%m/%Y')}",
        print_settings=print_settings,
    )
    left_x = 2 * cm
    right_x = 11 * cm
    pdf.setFont("Helvetica", 10)
    pdf.drawString(left_x, y, f"Numero : {remboursement.numero_remboursement}")
    pdf.drawString(right_x, y, f"Instance : {remboursement.instance}")
    y -= 0.6 * cm
    pdf.drawString(left_x, y, f"Type reunion : {remboursement.type_reunion}")
    pdf.drawString(right_x, y, f"Lieu : {remboursement.lieu}")
    y -= 0.6 * cm
    pdf.drawString(left_x, y, f"Nature : {remboursement.nature_reunion}")
    y -= 0.6 * cm
    if created_by_name:
        pdf.drawString(left_x, y, f"Demandeur : {created_by_name}")
        y -= 0.6 * cm
    y = _draw_wrapped_line(
        pdf,
        f"Travaux : {', '.join(remboursement.nature_travail or []) or '-'}",
        x=left_x,
        y=y,
        max_width=A4[0] - 4 * cm,
        font="Helvetica",
        font_size=10,
        leading=14,
    )
    y -= 0.2 * cm

    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(left_x, y, "Participants")
    y -= 0.5 * cm
    pdf.setFont("Helvetica", 9)
    if not participants:
        pdf.drawString(left_x, y, "Aucun participant enregistre.")
        y -= 0.5 * cm
    else:
        for idx, participant in enumerate(participants, start=1):
            amount = _format_money(participant.montant)
            pdf.drawString(left_x, y, f"{idx}. {participant.nom} - {participant.titre_fonction}")
            pdf.drawRightString(A4[0] - 2 * cm, y, amount)
            y -= 0.45 * cm
            if y < 5 * cm:
                pdf.showPage()
                y = A4[1] - 2 * cm

    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawRightString(
        A4[0] - 2 * cm,
        max(y - 0.4 * cm, 3.6 * cm),
        f"Total : {_format_money(remboursement.montant_total)}",
    )

    footer_y = 2.8 * cm
    pdf.setFont("Helvetica", 9)
    left_label = remboursement.signataire_g_label or remboursement.trans_label_gauche_hist or "Signature gauche"
    left_name = remboursement.signataire_g_nom or remboursement.trans_nom_gauche_hist or ""
    right_label = remboursement.signataire_d_label or remboursement.trans_label_droite_hist or "Signature droite"
    right_name = remboursement.signataire_d_nom or remboursement.trans_nom_droite_hist or ""
    pdf.drawString(2 * cm, footer_y, left_label)
    pdf.drawString(2 * cm, footer_y - 0.5 * cm, left_name)
    pdf.drawString(11 * cm, footer_y, right_label)
    pdf.drawString(11 * cm, footer_y - 0.5 * cm, right_name)

    pdf_bytes = _finalize_pdf(pdf, buffer)
    safe_ref = _safe_ref(remboursement.reference_numero or remboursement.numero_remboursement or str(remboursement.id), "REM")
    timestamp = remboursement.created_at or organisation.created_at
    relative_path = (
        f"/uploads/tenants/{organisation.uuid}/remboursements-transport/"
        f"{timestamp.year:04d}/{timestamp.month:02d}/{safe_ref}.pdf"
    )
    absolute_path = os.path.join(UPLOAD_ROOT, relative_path.replace("/uploads/", "", 1))
    _save_pdf_bytes(file_path=absolute_path, payload=pdf_bytes)
    remboursement.pdf_path = relative_path
    return PdfGenerationResult(storage_path=relative_path, absolute_path=absolute_path)


async def ensure_remboursement_official_pdf(
    db: AsyncSession,
    remboursement: RemboursementTransport,
    *,
    regenerate: bool = False,
) -> PdfGenerationResult:
    current_path = remboursement.pdf_path
    if current_path and not regenerate:
        fs_path = os.path.join(UPLOAD_ROOT, current_path.replace("/uploads/", "", 1))
        if os.path.exists(fs_path):
            return PdfGenerationResult(storage_path=current_path, absolute_path=fs_path)
    return await generate_remboursement_official_pdf(db, remboursement)
