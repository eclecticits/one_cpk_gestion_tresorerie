from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.compte_bancaire import CompteBancaire
from app.models.generated_document import DocumentSignatorySnapshot, GeneratedDocument
from app.models.organisation import Organisation
from app.models.print_settings import PrintSettings
from app.models.requisition import Requisition
from app.models.user import User


FINAL_REQUISITION_STATUSES = {"AUTORISEE", "APPROUVEE", "PAYEE", "SIGNEE", "EN_DECAISSEMENT"}
EDITABLE_REQUISITION_STATUSES = {"BROUILLON", "EN_ATTENTE", "EN_ATTENTE_COMMISSION"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def model_snapshot(obj: Any, fields: list[str]) -> dict[str, Any]:
    if obj is None:
        return {}
    return {field: json_value(getattr(obj, field, None)) for field in fields}


def full_user_name(user: User | None) -> str | None:
    if user is None:
        return None
    name = " ".join(part for part in [user.prenom, user.nom] if part).strip()
    return name or user.email


def historical_status(req: Requisition) -> str:
    return (req.status or "").upper()


def is_requisition_finalized(req: Requisition) -> bool:
    return historical_status(req) in FINAL_REQUISITION_STATUSES


def ensure_requisition_editable(req: Requisition, *, attempted_fields: set[str] | None = None) -> None:
    if not is_requisition_finalized(req):
        return
    fields = ", ".join(sorted(attempted_fields or [])) or "champs sensibles"
    from fastapi import HTTPException, status

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            "Réquisition verrouillée historiquement après validation. "
            f"Modification refusée pour: {fields}."
        ),
    )


def exchange_rate_for_currency(settings: PrintSettings | None, currency: str | None) -> Decimal:
    code = (currency or "USD").upper()
    if code == "USD":
        return Decimal("1")
    attr = {
        "CDF": "exchange_rate_cdf",
        "EUR": "exchange_rate_eur",
        "XOF": "exchange_rate_xof",
    }.get(code)
    if not attr or settings is None:
        return Decimal("0")
    try:
        return Decimal(str(getattr(settings, attr) or 0))
    except Exception:
        return Decimal("0")


def converted_to_base_amount(amount: Decimal | None, currency: str | None, rate: Decimal) -> Decimal | None:
    total = Decimal(amount or 0)
    code = (currency or "USD").upper()
    if code == "USD":
        return total
    if rate <= 0:
        return None
    return (total / rate).quantize(Decimal("0.01"))


async def load_requisition_signatories(db: AsyncSession, req: Requisition) -> dict[str, Any]:
    user_ids = [
        ("demandeur", req.created_by, req.created_at),
        ("signataire_service", req.signed_by_id, req.signed_at),
        ("examen", getattr(req, "examen_par", None), getattr(req, "examen_le", None)),
        ("validation_1", req.validee_par, req.validee_le),
        ("validation_2", req.approuvee_par, req.approuvee_le),
        ("paiement", req.payee_par, req.payee_le),
    ]
    snapshots: list[dict[str, Any]] = []
    for order, (role, user_id, signed_at) in enumerate(user_ids, start=1):
        if user_id is None:
            continue
        res = await db.execute(select(User).where(User.id == user_id).limit(1))
        user = res.scalar_one_or_none()
        snapshots.append(
            {
                "display_order": order,
                "role": role,
                "user_id": str(user_id),
                "full_name": full_user_name(user),
                "title": getattr(user, "role", None) if user is not None else None,
                "signature": getattr(user, "signature_url", None) if user is not None else None,
                "signed_at": json_value(signed_at),
            }
        )
    return {"items": snapshots}


async def ensure_requisition_historical_snapshot(
    db: AsyncSession,
    req: Requisition,
    *,
    tenant_id: int,
    force: bool = False,
) -> None:
    if req.historical_snapshot_status == "complete" and not force:
        return

    org_res = await db.execute(select(Organisation).where(Organisation.id == tenant_id).limit(1))
    org = org_res.scalar_one_or_none()
    ps_res = await db.execute(select(PrintSettings).where(PrintSettings.organisation_id == tenant_id).limit(1))
    settings = ps_res.scalar_one_or_none()
    bank = None
    if req.compte_bancaire_id is not None:
        bank_res = await db.execute(
            select(CompteBancaire).where(
                CompteBancaire.id == req.compte_bancaire_id,
                CompteBancaire.organisation_id == tenant_id,
            ).limit(1)
        )
        bank = bank_res.scalar_one_or_none()

    print_fields = [
        "organization_name",
        "organization_subtitle",
        "header_text",
        "address",
        "phone",
        "email",
        "website",
        "bank_name",
        "bank_account",
        "mobile_money_name",
        "mobile_money_number",
        "pied_de_page_legal",
        "show_header_logo",
        "show_footer_signature",
        "logo_url",
        "stamp_url",
        "req_titre_officiel",
        "req_label_gauche",
        "req_nom_gauche",
        "req_label_droite",
        "req_nom_droite",
        "sortie_label_signature",
        "sortie_nom_signataire",
        "sortie_sig_label_1",
        "sortie_sig_label_2",
        "sortie_sig_label_3",
        "sortie_sig_hint",
        "default_currency",
        "secondary_currency",
        "exchange_rate",
        "exchange_rate_cdf",
        "exchange_rate_eur",
        "exchange_rate_xof",
        "fiscal_year",
    ]
    req.print_settings_snapshot = model_snapshot(settings, print_fields)
    req.organisation_snapshot = model_snapshot(
        org,
        ["id", "uuid", "nom", "slug", "email_contact", "telephone", "adresse", "devise_preferee", "taux_change_interne"],
    )
    req.bank_account_snapshot = model_snapshot(
        bank,
        ["id", "intitule", "numero_compte", "devise", "account_type"],
    )
    req.signatories_snapshot = await load_requisition_signatories(db, req)

    rate = exchange_rate_for_currency(settings, req.devise)
    req.exchange_rate_snapshot = rate
    req.exchange_rate_source = "print_settings"
    req.exchange_rate_date = utcnow()
    req.base_amount_snapshot = Decimal(req.montant_total or 0)
    req.converted_amount_snapshot = converted_to_base_amount(req.montant_total, req.devise, rate)

    if not req.req_titre_officiel_hist and settings:
        req.req_titre_officiel_hist = settings.req_titre_officiel or None
    if not req.req_label_gauche_hist and settings:
        req.req_label_gauche_hist = settings.req_label_gauche or None
    if not req.req_nom_gauche_hist and settings:
        req.req_nom_gauche_hist = settings.req_nom_gauche or None
    if not req.req_label_droite_hist and settings:
        req.req_label_droite_hist = settings.req_label_droite or None
    if not req.req_nom_droite_hist and settings:
        req.req_nom_droite_hist = settings.req_nom_droite or None
    req.signataire_g_label = req.signataire_g_label or req.req_label_gauche_hist
    req.signataire_g_nom = req.signataire_g_nom or req.req_nom_gauche_hist
    req.signataire_d_label = req.signataire_d_label or req.req_label_droite_hist
    req.signataire_d_nom = req.signataire_d_nom or req.req_nom_droite_hist

    req.historical_snapshot_status = "complete"
    req.snapshot_created_at = req.snapshot_created_at or utcnow()
    req.snapshot_version = req.snapshot_version or 1
    req.row_version = (req.row_version or 0) + 1


async def mark_legacy_snapshot_incomplete(db: AsyncSession, req: Requisition) -> None:
    if req.historical_snapshot_status == "complete":
        return
    req.historical_snapshot_status = "legacy_data_unverified"
    req.snapshot_created_at = req.snapshot_created_at or utcnow()
    await db.flush()


async def register_generated_document(
    db: AsyncSession,
    *,
    organisation_id: int,
    resource_type: str,
    resource_id: str,
    document_type: str,
    pdf_path: str | None,
    payload: bytes | None,
    source_snapshot: dict[str, Any] | None,
    signatories_snapshot: dict[str, Any] | None,
    exchange_rate_snapshot: dict[str, Any] | None,
    generated_by: uuid.UUID | None = None,
    legacy_data_status: str = "current_snapshot",
) -> GeneratedDocument:
    version_res = await db.execute(
        select(func.coalesce(func.max(GeneratedDocument.version), 0)).where(
            GeneratedDocument.organisation_id == organisation_id,
            GeneratedDocument.resource_type == resource_type,
            GeneratedDocument.resource_id == resource_id,
            GeneratedDocument.document_type == document_type,
        )
    )
    version = int(version_res.scalar_one() or 0) + 1
    rendered_hash = hashlib.sha256(payload).hexdigest() if payload else None
    doc = GeneratedDocument(
        organisation_id=organisation_id,
        resource_type=resource_type,
        resource_id=resource_id,
        document_type=document_type,
        version=version,
        generated_at=utcnow(),
        generated_by=generated_by,
        source_snapshot=source_snapshot,
        signatories_snapshot=signatories_snapshot,
        exchange_rate_snapshot=exchange_rate_snapshot,
        rendered_hash=rendered_hash,
        pdf_path=pdf_path,
        is_original=version == 1,
        legacy_data_status=legacy_data_status,
    )
    db.add(doc)
    await db.flush()
    for item in (signatories_snapshot or {}).get("items", []):
        db.add(
            DocumentSignatorySnapshot(
                document_id=doc.id,
                organisation_id=organisation_id,
                user_id=uuid.UUID(item["user_id"]) if item.get("user_id") else None,
                display_order=int(item.get("display_order") or 1),
                full_name_snapshot=item.get("full_name"),
                title_snapshot=item.get("title"),
                role_snapshot=item.get("role"),
                signature_snapshot=item.get("signature"),
                signed_at=datetime.fromisoformat(item["signed_at"]) if item.get("signed_at") else None,
            )
        )
    return doc
