"""Facturation émise aux tenants — identité de l'éditeur, numérotation, PDF.

Deux chemins mènent à une facture SaaS, et ce module les fait converger :

* **paiement en ligne** — le tenant règle, la facture naît déjà acquittée
  (`saas_billing_notifications.create_and_send_saas_invoice`) ;
* **facturation émise** — l'éditeur établit la facture, le tenant la règle
  ensuite, en ligne ou par un moyen hors plateforme (virement, mobile money,
  espèces) constaté ici par un super-admin.

Le second chemin impose trois choses que le premier n'avait pas besoin de
connaître : une identité d'émetteur, une numérotation séquentielle sans trou, et
un PDF qui vaut demande de paiement — donc qui porte les coordonnées de
règlement tant que la facture n'est pas soldée.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import anyio
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.organisation import Organisation
from app.models.platform_settings import PlatformSettings
from app.models.saas_invoice import SaaSInvoice

# ── Identité de l'éditeur ────────────────────────────────────────────────────
# Seul le nom commercial est connu du code. Tout ce qui est légal ou bancaire
# (RCCM, NIF, IBAN…) reste vide par défaut : ces mentions engagent l'entreprise
# et figureront sur des pièces envoyées à de vrais clients. Elles se saisissent
# depuis la console, jamais depuis une valeur codée en dur.
ISSUER_DEFAULTS: dict[str, object] = {
    "name": "Eclectic IT Services",
    "tagline": "Édition et hébergement de solutions de gestion",
    "address": "",
    "city": "",
    "country": "",
    "email": "",
    "phone": "",
    "website": "",
    "rccm": "",
    "id_nat": "",
    "tax_id": "",
    "bank_name": "",
    "bank_account": "",
    "bank_swift": "",
    "mobile_money": "",
    "payment_terms_days": 15,
    # Quelles voies de reglement la facture annonce. Un client sous contrat
    # cadre reglant toujours par virement n'a pas a lire une invitation au
    # paiement en ligne, et inversement : l'affichage se choisit, il ne
    # s'impose pas.
    "online_payment_enabled": True,
    "manual_payment_enabled": True,
    "invoice_prefix": "EIS",
    "footer_note": "",
}

ISSUER_TEXT_FIELDS = tuple(k for k, v in ISSUER_DEFAULTS.items() if isinstance(v, str))

INVOICE_STATUSES = ("DRAFT", "ISSUED", "PAID", "CANCELLED")
OPEN_STATUSES = ("DRAFT", "ISSUED")

PAYMENT_METHODS = {
    "BANK_TRANSFER": "Virement bancaire",
    "MOBILE_MONEY": "Mobile money",
    "CASH": "Espèces",
    "CHECK": "Chèque",
    "ONLINE": "Paiement en ligne",
    "OTHER": "Autre",
}

# Palette alignée sur les exports Excel budget, pour que les documents sortant
# de la plateforme aient une même famille visuelle.
_INK = colors.HexColor("#0F172A")
_MUTED = colors.HexColor("#64748B")
_ACCENT = colors.HexColor("#0F766E")
_LINE = colors.HexColor("#E2E8F0")
_BAND = colors.HexColor("#F1F5F9")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _upload_root() -> str:
    default_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "uploads"))
    return os.path.abspath(settings.upload_dir) if settings.upload_dir else default_root


def _fmt_date(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone(timezone.utc).strftime("%d/%m/%Y")


def _fmt_money(amount: Decimal | float | int, currency: str) -> str:
    return f"{float(amount):,.2f} {currency}".replace(",", " ")


def to_decimal(value: object, field: str) -> Decimal:
    """Convertit en Decimal en refusant les entrées inexploitables.

    Les montants transitent en JSON, donc en float ou en chaîne. Passer par
    `str()` avant `Decimal` évite d'hériter du bruit binaire d'un float.
    """
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Montant invalide pour {field} : {value!r}") from exc
    if result.is_nan() or result.is_infinite():
        raise ValueError(f"Montant invalide pour {field} : {value!r}")
    return result.quantize(Decimal("0.01"))


# ── Identité éditeur : lecture / écriture ────────────────────────────────────


async def _platform_settings(db: AsyncSession) -> PlatformSettings:
    res = await db.execute(select(PlatformSettings).where(PlatformSettings.id == 1))
    row = res.scalar_one_or_none()
    if row is None:
        row = PlatformSettings(id=1, billing_config={})
        db.add(row)
        await db.flush()
    return row


def merge_issuer(raw: object) -> dict:
    """Complète une configuration partielle avec les valeurs par défaut."""
    stored = raw if isinstance(raw, dict) else {}
    issuer = dict(ISSUER_DEFAULTS)
    for key in ISSUER_DEFAULTS:
        value = stored.get(key)
        if value is None:
            continue
        if key == "payment_terms_days":
            try:
                issuer[key] = max(0, int(value))
            except (TypeError, ValueError):
                continue
        elif isinstance(ISSUER_DEFAULTS[key], bool):
            issuer[key] = bool(value)
        else:
            issuer[key] = str(value).strip()
    if not str(issuer.get("name") or "").strip():
        issuer["name"] = str(ISSUER_DEFAULTS["name"])
    if not str(issuer.get("invoice_prefix") or "").strip():
        issuer["invoice_prefix"] = str(ISSUER_DEFAULTS["invoice_prefix"])
    return issuer


async def get_issuer(db: AsyncSession) -> dict:
    row = await _platform_settings(db)
    config = row.billing_config if isinstance(row.billing_config, dict) else {}
    return merge_issuer(config.get("issuer"))


async def save_issuer(db: AsyncSession, payload: dict) -> dict:
    row = await _platform_settings(db)
    config = dict(row.billing_config) if isinstance(row.billing_config, dict) else {}
    issuer = merge_issuer({**(config.get("issuer") or {}), **payload})
    config["issuer"] = issuer
    # Réaffectation complète : SQLAlchemy ne détecte pas la mutation d'un JSONB
    # modifié en place.
    row.billing_config = config
    row.updated_at = _utcnow()
    return issuer


# ── Numérotation ─────────────────────────────────────────────────────────────


async def next_invoice_number(db: AsyncSession, *, prefix: str, issued_at: datetime) -> str:
    """Numéro séquentiel `PREFIX-AAAA-0001`, continu sur l'année civile.

    Une numérotation à trous se défend mal devant un contrôle : on repart donc
    du plus grand rang déjà attribué pour l'année, et non d'un compte de lignes
    (qui reculerait si une facture était supprimée).
    """
    year = issued_at.astimezone(timezone.utc).year
    stem = f"{prefix}-{year}-"
    res = await db.execute(
        select(func.max(SaaSInvoice.invoice_number)).where(SaaSInvoice.invoice_number.like(f"{stem}%"))
    )
    highest = res.scalar_one_or_none()
    rank = 0
    if highest:
        tail = str(highest)[len(stem):]
        if tail.isdigit():
            rank = int(tail)
    return f"{stem}{rank + 1:04d}"


# ── Lignes de facture ────────────────────────────────────────────────────────


def normalize_line_items(raw: object) -> tuple[list[dict], Decimal]:
    """Valide les lignes saisies et renvoie (lignes normalisées, total)."""
    if not isinstance(raw, list) or not raw:
        raise ValueError("Au moins une ligne de facturation est requise.")

    lines: list[dict] = []
    total = Decimal("0.00")
    for index, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"Ligne {index} : format invalide.")
        designation = str(entry.get("designation") or "").strip()
        if not designation:
            raise ValueError(f"Ligne {index} : la désignation est obligatoire.")
        quantity = to_decimal(entry.get("quantite", 1) or 0, f"quantité (ligne {index})")
        unit_price = to_decimal(entry.get("prix_unitaire", 0) or 0, f"prix unitaire (ligne {index})")
        if quantity <= 0:
            raise ValueError(f"Ligne {index} : la quantité doit être strictement positive.")
        if unit_price < 0:
            raise ValueError(f"Ligne {index} : le prix unitaire ne peut pas être négatif.")
        amount = (quantity * unit_price).quantize(Decimal("0.01"))
        lines.append(
            {
                "designation": designation,
                "quantite": float(quantity),
                "prix_unitaire": float(unit_price),
                "montant": float(amount),
            }
        )
        total += amount

    if total <= 0:
        raise ValueError("Le total de la facture doit être strictement positif.")
    return lines, total.quantize(Decimal("0.01"))


def default_due_date(issued_at: datetime, issuer: dict) -> datetime:
    try:
        days = int(issuer.get("payment_terms_days") or 0)
    except (TypeError, ValueError):
        days = 0
    return issued_at + timedelta(days=max(0, days))


# ── PDF ──────────────────────────────────────────────────────────────────────


def _issuer_lines(issuer: dict) -> list[str]:
    rows = [issuer.get("address"), issuer.get("city"), issuer.get("country")]
    contact = " · ".join(x for x in (issuer.get("phone"), issuer.get("email")) if x)
    rows.append(contact)
    rows.append(issuer.get("website"))
    legal = " · ".join(
        f"{label} {issuer.get(key)}"
        for key, label in (("rccm", "RCCM"), ("id_nat", "Id. Nat."), ("tax_id", "NIF"))
        if issuer.get(key)
    )
    rows.append(legal)
    return [str(row).strip() for row in rows if str(row or "").strip()]


def _payment_lines(issuer: dict) -> list[str]:
    rows: list[str] = []
    if issuer.get("bank_name") or issuer.get("bank_account"):
        bank = " — ".join(x for x in (issuer.get("bank_name"), issuer.get("bank_account")) if x)
        rows.append(f"Virement : {bank}")
        if issuer.get("bank_swift"):
            rows.append(f"SWIFT/BIC : {issuer['bank_swift']}")
    if issuer.get("mobile_money"):
        rows.append(f"Mobile money : {issuer['mobile_money']}")
    return rows


def _fit(c: canvas.Canvas, text: str, max_width: float, font: str, size: float) -> str:
    """Tronque une chaine pour qu'elle tienne dans la largeur donnee.

    Les coordonnees bancaires sont saisies librement : sans garde-fou, un IBAN
    verbeux depasse la marge droite et se fait rogner par le lecteur PDF.
    """
    if c.stringWidth(text, font, size) <= max_width:
        return text
    trimmed = text
    while trimmed and c.stringWidth(trimmed + "..", font, size) > max_width:
        trimmed = trimmed[:-1]
    return (trimmed + "..") if trimmed else ""


def _draw_header(c: canvas.Canvas, width: float, height: float, issuer: dict, invoice: SaaSInvoice) -> float:
    c.setFillColor(_ACCENT)
    c.rect(0, height - 0.5 * cm, width, 0.5 * cm, stroke=0, fill=1)

    y = height - 2.2 * cm
    c.setFillColor(_INK)
    c.setFont("Helvetica-Bold", 17)
    c.drawString(2 * cm, y, str(issuer.get("name") or ISSUER_DEFAULTS["name"]))

    if issuer.get("tagline"):
        c.setFont("Helvetica-Oblique", 9)
        c.setFillColor(_MUTED)
        c.drawString(2 * cm, y - 0.5 * cm, str(issuer["tagline"]))

    c.setFillColor(_MUTED)
    c.setFont("Helvetica", 8.5)
    line_y = y - 1.05 * cm
    for row in _issuer_lines(issuer):
        c.drawString(2 * cm, line_y, row)
        line_y -= 0.36 * cm

    c.setFillColor(_INK)
    c.setFont("Helvetica-Bold", 20)
    c.drawRightString(width - 2 * cm, y, "FACTURE")
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(_ACCENT)
    c.drawRightString(width - 2 * cm, y - 0.65 * cm, invoice.invoice_number)

    status_label = {
        "DRAFT": "BROUILLON",
        "ISSUED": "EN ATTENTE DE PAIEMENT",
        "PAID": "PAYÉE",
        "CANCELLED": "ANNULÉE",
    }.get(invoice.status, invoice.status)
    c.setFillColor(_MUTED if invoice.status != "PAID" else _ACCENT)
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(width - 2 * cm, y - 1.15 * cm, status_label)

    return min(line_y, y - 1.8 * cm) - 0.5 * cm


def _draw_parties(c: canvas.Canvas, width: float, y: float, org: Organisation, invoice: SaaSInvoice) -> float:
    c.setFillColor(_BAND)
    c.rect(2 * cm, y - 2.5 * cm, width - 4 * cm, 2.5 * cm, stroke=0, fill=1)

    c.setFillColor(_MUTED)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(2.4 * cm, y - 0.6 * cm, "FACTURÉ À")
    c.drawString(width / 2, y - 0.6 * cm, "DÉTAILS")

    c.setFillColor(_INK)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(2.4 * cm, y - 1.15 * cm, org.nom)
    c.setFont("Helvetica", 9)
    c.setFillColor(_MUTED)
    c.drawString(2.4 * cm, y - 1.6 * cm, f"Tenant : {org.slug}")
    if org.email_contact:
        c.drawString(2.4 * cm, y - 2.0 * cm, str(org.email_contact))

    c.setFillColor(_INK)
    c.setFont("Helvetica", 9)
    meta = [
        ("Date d'émission", _fmt_date(invoice.issue_date)),
        ("Échéance", _fmt_date(invoice.due_date)),
        (
            "Période",
            # « → » n'appartient pas a WinAnsiEncoding, la police Helvetica de
            # reportlab le rendrait en « ® ». On reste sur des caracteres surs.
            f"{_fmt_date(invoice.period_start)} au {_fmt_date(invoice.period_end)}"
            if invoice.period_start or invoice.period_end
            else "—",
        ),
    ]
    meta_y = y - 1.15 * cm
    for label, value in meta:
        c.setFillColor(_MUTED)
        c.drawString(width / 2, meta_y, f"{label} :")
        c.setFillColor(_INK)
        c.drawRightString(width - 2.4 * cm, meta_y, value)
        meta_y -= 0.45 * cm

    return y - 3.2 * cm


def _draw_items(c: canvas.Canvas, width: float, y: float, invoice: SaaSInvoice, fallback: str) -> float:
    c.setFillColor(_INK)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(2 * cm, y, "DÉSIGNATION")
    c.drawRightString(width - 8.2 * cm, y, "QTÉ")
    c.drawRightString(width - 5.2 * cm, y, "P.U.")
    c.drawRightString(width - 2 * cm, y, "MONTANT")
    y -= 0.25 * cm
    c.setStrokeColor(_ACCENT)
    c.setLineWidth(1.1)
    c.line(2 * cm, y, width - 2 * cm, y)
    y -= 0.65 * cm

    currency = invoice.currency
    rows = invoice.line_items if isinstance(invoice.line_items, list) and invoice.line_items else None
    if rows is None:
        # Factures nées d'un paiement en ligne : pas de détail saisi, on restitue
        # le libellé d'abonnement plutôt qu'un tableau vide.
        rows = [
            {
                "designation": fallback,
                "quantite": 1,
                "prix_unitaire": float(invoice.amount),
                "montant": float(invoice.amount),
            }
        ]

    c.setFont("Helvetica", 9.5)
    for row in rows:
        designation = str(row.get("designation") or "")
        # Le tableau ne gère pas le retour à la ligne : on tronque plutôt que de
        # laisser le texte chevaucher la colonne des quantités.
        if len(designation) > 58:
            designation = designation[:57] + ".."
        c.setFillColor(_INK)
        c.drawString(2 * cm, y, designation)
        c.setFillColor(_MUTED)
        c.drawRightString(width - 8.2 * cm, y, f"{float(row.get('quantite') or 0):g}")
        c.drawRightString(width - 5.2 * cm, y, _fmt_money(row.get("prix_unitaire") or 0, currency))
        c.setFillColor(_INK)
        c.drawRightString(width - 2 * cm, y, _fmt_money(row.get("montant") or 0, currency))
        y -= 0.55 * cm
        c.setStrokeColor(_LINE)
        c.setLineWidth(0.4)
        c.line(2 * cm, y + 0.18 * cm, width - 2 * cm, y + 0.18 * cm)

    y -= 0.4 * cm
    c.setFillColor(_BAND)
    c.rect(width - 8.6 * cm, y - 0.9 * cm, 6.6 * cm, 0.9 * cm, stroke=0, fill=1)
    c.setFillColor(_INK)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(width - 8.3 * cm, y - 0.6 * cm, "TOTAL")
    c.drawRightString(width - 2.2 * cm, y - 0.6 * cm, _fmt_money(invoice.amount, currency))
    return y - 1.8 * cm


def _draw_settlement(c: canvas.Canvas, width: float, y: float, invoice: SaaSInvoice, issuer: dict) -> float:
    if invoice.status == "PAID":
        c.setFillColor(_ACCENT)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(2 * cm, y, "Facture acquittée")
        c.setFillColor(_MUTED)
        c.setFont("Helvetica", 9)
        details = [f"Réglée le {_fmt_date(invoice.paid_at)}"]
        if invoice.payment_method:
            details.append(PAYMENT_METHODS.get(invoice.payment_method, invoice.payment_method))
        if invoice.payment_reference:
            details.append(f"Réf. {invoice.payment_reference}")
        c.drawString(2 * cm, y - 0.45 * cm, " · ".join(details))
        return y - 1.3 * cm

    if invoice.status == "CANCELLED":
        c.setFillColor(_MUTED)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(2 * cm, y, "Facture annulée")
        if invoice.cancel_reason:
            c.setFont("Helvetica", 9)
            c.drawString(2 * cm, y - 0.45 * cm, str(invoice.cancel_reason)[:110])
        return y - 1.3 * cm

    online = bool(issuer.get("online_payment_enabled", True))
    manual = bool(issuer.get("manual_payment_enabled", True))
    if not online and not manual:
        # Aucune voie annoncee : la facture reste muette sur le reglement, ce
        # qui se defend quand les modalites vivent dans un contrat signe.
        return y

    c.setFillColor(_INK)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(2 * cm, y, "Modalités de règlement")

    online_rows = [
        "Espace Facturation du compte,",
        "rubrique « Régler ma facture ».",
        "Règlement constaté immédiatement.",
    ]
    manual_rows = (_payment_lines(issuer) or [
        "Coordonnées de règlement communiquées",
        "par l'éditeur sur simple demande.",
    ]) + [
        "Transmettez la preuve de paiement :",
        "la facture est soldée après contrôle.",
    ]

    columns: list[tuple[str, list[str]]] = []
    if online:
        columns.append(("En ligne", online_rows))
    if manual:
        columns.append(("Paiement manuel", manual_rows))

    head_y = y - 0.5 * cm
    if len(columns) == 2:
        # Les deux voies coexistent : on les numerote pour dire au client qu'il
        # choisit, plutot que de laisser croire a une sequence obligatoire.
        c.setFont("Helvetica-Oblique", 8.5)
        c.setFillColor(_MUTED)
        c.drawString(2 * cm, head_y, "Deux options, au choix du client.")
        head_y -= 0.55 * cm
        positions = [2 * cm, width / 2 + 0.4 * cm]
        titles = ["1. En ligne", "2. Paiement manuel"]
    else:
        positions = [2 * cm]
        titles = [columns[0][0]]

    lowest = head_y
    for index, (position, title) in enumerate(zip(positions, titles)):
        c.setFillColor(_ACCENT)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(position, head_y, title)

        available = (width - 2 * cm) - position
        c.setFillColor(_MUTED)
        c.setFont("Helvetica", 8.5)
        line_y = head_y - 0.42 * cm
        for row in columns[index][1][:5]:
            c.drawString(position, line_y, _fit(c, row, available, "Helvetica", 8.5))
            line_y -= 0.36 * cm
        lowest = min(lowest, line_y)

    return lowest - 0.6 * cm


def render_invoice_pdf(
    *,
    invoice: SaaSInvoice,
    org: Organisation,
    issuer: dict,
    fallback_designation: str,
) -> str:
    """Trace le PDF sur disque et renvoie son chemin. Synchrone : à confier à un thread."""
    target_dir = os.path.join(_upload_root(), "saas-invoices", str(org.id))
    os.makedirs(target_dir, exist_ok=True)
    path = os.path.join(target_dir, f"{invoice.invoice_number}.pdf")

    c = canvas.Canvas(path, pagesize=A4)
    width, height = A4

    y = _draw_header(c, width, height, issuer, invoice)
    y = _draw_parties(c, width, y, org, invoice)
    y = _draw_items(c, width, y, invoice, fallback_designation)
    y = _draw_settlement(c, width, y, invoice, issuer)

    if invoice.notes:
        c.setFillColor(_INK)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(2 * cm, y, "Note")
        c.setFillColor(_MUTED)
        c.setFont("Helvetica", 9)
        c.drawString(2 * cm, y - 0.42 * cm, str(invoice.notes)[:120])

    c.setStrokeColor(_LINE)
    c.setLineWidth(0.5)
    c.line(2 * cm, 1.9 * cm, width - 2 * cm, 1.9 * cm)
    c.setFillColor(_MUTED)
    c.setFont("Helvetica", 7.5)
    footer = str(issuer.get("footer_note") or "").strip()
    c.drawString(2 * cm, 1.45 * cm, footer or f"{issuer.get('name')} — facture émise par la plateforme.")
    c.drawRightString(width - 2 * cm, 1.45 * cm, f"{invoice.invoice_number} · page 1/1")

    c.showPage()
    c.save()
    return path


async def refresh_invoice_pdf(
    db: AsyncSession,
    invoice: SaaSInvoice,
    *,
    org: Organisation | None = None,
    fallback_designation: str = "Abonnement SaaS",
) -> str:
    """(Re)génère le PDF d'une facture après un changement d'état."""
    if org is None:
        res = await db.execute(select(Organisation).where(Organisation.id == invoice.organisation_id))
        org = res.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation introuvable pour cette facture.")

    issuer = merge_issuer(invoice.issuer_snapshot) if invoice.issuer_snapshot else await get_issuer(db)
    path = await anyio.to_thread.run_sync(
        lambda: render_invoice_pdf(
            invoice=invoice,
            org=org,
            issuer=issuer,
            fallback_designation=fallback_designation,
        )
    )
    invoice.pdf_path = path
    invoice.updated_at = _utcnow()
    return path


# ── Création ─────────────────────────────────────────────────────────────────


async def create_issued_invoice(
    db: AsyncSession,
    *,
    org: Organisation,
    line_items: list[dict],
    total: Decimal,
    currency: str,
    period_start: datetime | None,
    period_end: datetime | None,
    due_date: datetime | None,
    notes: str | None,
    status: str,
    subscription_id: uuid.UUID | None = None,
) -> SaaSInvoice:
    if status not in ("DRAFT", "ISSUED"):
        raise ValueError("Une facture se crée en brouillon ou émise.")

    issuer = await get_issuer(db)
    now = _utcnow()
    prefix = str(issuer.get("invoice_prefix") or ISSUER_DEFAULTS["invoice_prefix"])

    invoice = SaaSInvoice(
        invoice_number=await next_invoice_number(db, prefix=prefix, issued_at=now),
        organisation_id=org.id,
        subscription_id=subscription_id,
        status=status,
        amount=total,
        currency=currency,
        issue_date=now,
        due_date=due_date or default_due_date(now, issuer),
        period_start=period_start,
        period_end=period_end,
        line_items=line_items,
        issuer_snapshot=issuer,
        notes=notes,
        metadata_json={"origin": "console", "created_at": now.isoformat()},
    )
    db.add(invoice)
    await db.flush()

    await refresh_invoice_pdf(db, invoice, org=org)
    return invoice


async def mark_invoice_paid(
    db: AsyncSession,
    invoice: SaaSInvoice,
    *,
    method: str,
    reference: str | None,
    paid_at: datetime | None,
    recorded_by: uuid.UUID | None,
    org: Organisation | None = None,
) -> SaaSInvoice:
    if invoice.status == "PAID":
        raise ValueError("Cette facture est déjà réglée.")
    if invoice.status == "CANCELLED":
        raise ValueError("Une facture annulée ne peut pas être réglée.")
    if method not in PAYMENT_METHODS:
        raise ValueError(f"Moyen de paiement inconnu : {method}")

    invoice.status = "PAID"
    invoice.payment_method = method
    invoice.payment_reference = (reference or "").strip() or None
    invoice.paid_at = paid_at or _utcnow()
    invoice.paid_by_user_id = recorded_by
    invoice.updated_at = _utcnow()

    await refresh_invoice_pdf(db, invoice, org=org)
    return invoice


async def cancel_invoice(db: AsyncSession, invoice: SaaSInvoice, *, reason: str | None) -> SaaSInvoice:
    if invoice.status == "PAID":
        raise ValueError("Une facture réglée ne s'annule pas : émettez un avoir.")
    if invoice.status == "CANCELLED":
        raise ValueError("Cette facture est déjà annulée.")

    invoice.status = "CANCELLED"
    invoice.cancelled_at = _utcnow()
    invoice.cancel_reason = (reason or "").strip() or None
    invoice.updated_at = _utcnow()

    await refresh_invoice_pdf(db, invoice)
    return invoice


async def find_open_invoice(db: AsyncSession, *, organisation_id: int) -> SaaSInvoice | None:
    """Facture ouverte la plus ancienne d'un tenant — celle qu'un paiement solde."""
    res = await db.execute(
        select(SaaSInvoice)
        .where(
            SaaSInvoice.organisation_id == organisation_id,
            SaaSInvoice.status.in_(OPEN_STATUSES),
        )
        .order_by(SaaSInvoice.issue_date.asc())
        .limit(1)
    )
    return res.scalars().first()
