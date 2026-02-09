from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr


class PrintSettingsBase(BaseModel):
    organization_name: str = ""
    organization_subtitle: str = ""
    header_text: str = ""
    address: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    bank_name: str = ""
    bank_account: str = ""
    mobile_money_name: str = ""
    mobile_money_number: str = ""
    pied_de_page_legal: str = ""
    afficher_qr_code: bool = True
    show_header_logo: bool = True
    show_footer_signature: bool = True
    logo_url: str = ""
    stamp_url: str = ""
    recu_label_signature: str = ""
    recu_nom_signataire: str = ""
    sortie_label_signature: str = ""
    sortie_nom_signataire: str = ""
    show_sortie_qr: bool = True
    sortie_qr_base_url: str = ""
    show_sortie_watermark: bool = True
    sortie_watermark_text: str = "PAYÉ"
    sortie_watermark_opacity: float = 0.15
    paper_format: str = "A5"
    compact_header: bool = False
    req_titre_officiel: str = ""
    req_label_gauche: str = ""
    req_nom_gauche: str = ""
    req_label_droite: str = ""
    req_nom_droite: str = ""
    trans_titre_officiel: str = ""
    trans_label_gauche: str = ""
    trans_nom_gauche: str = ""
    trans_label_droite: str = ""
    trans_nom_droite: str = ""
    default_currency: str = "USD"
    secondary_currency: str = "CDF"
    exchange_rate: float = 0
    fiscal_year: int = 2026
    budget_alert_threshold: int = 80
    budget_block_overrun: bool = True
    budget_force_roles: str = ""


class PrintSettingsUpdate(PrintSettingsBase):
    pass


class PrintSettingsResponse(PrintSettingsBase):
    id: str
    updated_by: str | None = None
    updated_at: datetime

    class Config:
        from_attributes = True
