"""Schémas de la facturation émise aux tenants (console super-admin)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class IssuerOut(BaseModel):
    """Identité de l'éditeur telle qu'elle s'imprime sur les factures."""

    name: str
    tagline: str = ""
    address: str = ""
    city: str = ""
    country: str = ""
    email: str = ""
    phone: str = ""
    website: str = ""
    rccm: str = ""
    id_nat: str = ""
    tax_id: str = ""
    bank_name: str = ""
    bank_account: str = ""
    bank_swift: str = ""
    mobile_money: str = ""
    payment_terms_days: int = 15
    # Voies de règlement annoncées sur le PDF. Les deux par défaut ; décocher
    # l'une retire simplement sa colonne, décocher les deux rend la facture
    # muette sur le règlement.
    online_payment_enabled: bool = True
    manual_payment_enabled: bool = True
    invoice_prefix: str = "EIS"
    footer_note: str = ""


class PlanOut(BaseModel):
    """Un plan de la grille tarifaire."""

    code: str
    name: str
    description: str = ""
    # Le prix voyage en texte : un flottant JSON perdrait des centimes sur les
    # montants qui ne tombent pas juste en binaire.
    price: str = "0.00"
    currency: str = "USD"
    interval: str = "monthly"
    active: bool = True


class PlanIn(BaseModel):
    code: str = Field(max_length=50)
    name: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=500)
    price: str | float | int = "0.00"
    currency: str = "USD"
    interval: str = "monthly"
    active: bool = True


class PlanCatalogueUpdate(BaseModel):
    """Le catalogue est remplacé en bloc : c'est un tableau qu'on édite puis
    qu'on enregistre, pas une collection à muter ligne à ligne."""

    plans: list[PlanIn] = Field(default_factory=list, max_length=50)


class LogoOut(BaseModel):
    """Descripteur du logo de l'éditeur. `present` à faux quand aucun fichier
    n'est enregistré — le front n'a alors rien à afficher."""

    present: bool = False
    filename: str = ""
    content_type: str = ""
    size: int = 0
    uploaded_at: str = ""
    # Couleur de marque effectivement imprimée sur les factures, et celle que
    # le logo porte : les distinguer permet de proposer un retour en arrière
    # après un réglage à la main. Vides pour un logo sans couleur (gris, noir).
    accent: str = ""
    accent_detecte: str = ""


class AccentUpdate(BaseModel):
    """Une valeur vide rétablit la couleur lue dans le logo."""

    accent: str = Field(default="", max_length=7)


class IssuerUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    tagline: str | None = Field(default=None, max_length=160)
    address: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=80)
    email: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=80)
    website: str | None = Field(default=None, max_length=160)
    rccm: str | None = Field(default=None, max_length=80)
    id_nat: str | None = Field(default=None, max_length=80)
    tax_id: str | None = Field(default=None, max_length=80)
    bank_name: str | None = Field(default=None, max_length=120)
    bank_account: str | None = Field(default=None, max_length=120)
    bank_swift: str | None = Field(default=None, max_length=40)
    mobile_money: str | None = Field(default=None, max_length=120)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    online_payment_enabled: bool | None = None
    manual_payment_enabled: bool | None = None
    invoice_prefix: str | None = Field(default=None, min_length=1, max_length=10)
    footer_note: str | None = Field(default=None, max_length=200)


class InvoiceLineIn(BaseModel):
    designation: str = Field(min_length=1, max_length=200)
    quantite: float = Field(gt=0)
    prix_unitaire: float = Field(ge=0)


class InvoiceLineOut(BaseModel):
    designation: str
    quantite: float
    prix_unitaire: float
    montant: float


class InvoiceCreate(BaseModel):
    organisation_id: int
    # Liste vide autorisée : le serveur pré-remplit alors une ligne d'abonnement
    # à partir du plan de l'organisation, pris dans la grille tarifaire.
    lines: list[InvoiceLineIn] = Field(default_factory=list)
    currency: str = Field(default="USD", min_length=2, max_length=8)
    period_start: datetime | None = None
    period_end: datetime | None = None
    due_date: datetime | None = None
    notes: str | None = Field(default=None, max_length=400)
    # Un brouillon reste modifiable et n'est pas envoyé ; une facture émise part
    # au client et entre dans la numérotation utile.
    issue: bool = True
    send_email: bool = False


class InvoiceMarkPaid(BaseModel):
    method: str = Field(description="BANK_TRANSFER | MOBILE_MONEY | CASH | CHECK | ONLINE | OTHER")
    reference: str | None = Field(default=None, max_length=160)
    paid_at: datetime | None = None


class InvoiceCancel(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class InvoiceOut(BaseModel):
    id: str
    invoice_number: str
    organisation_id: int
    organisation_name: str | None = None
    organisation_slug: str | None = None
    status: str
    amount: float
    currency: str
    issue_date: datetime | None = None
    due_date: datetime | None = None
    paid_at: datetime | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    payment_method: str | None = None
    payment_method_label: str | None = None
    payment_reference: str | None = None
    lines: list[InvoiceLineOut] = Field(default_factory=list)
    notes: str | None = None
    cancel_reason: str | None = None
    sent_at: datetime | None = None
    recipient_email: str | None = None
    has_pdf: bool = False
    is_overdue: bool = False


class InvoiceListOut(BaseModel):
    items: list[InvoiceOut]
    total: int
    totals_by_status: dict[str, float] = Field(default_factory=dict)


class InvoiceSendResult(BaseModel):
    ok: bool
    sent_to: list[str] = Field(default_factory=list)
    detail: str | None = None
