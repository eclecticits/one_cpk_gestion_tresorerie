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
    footer_text: str = ""
    show_header_logo: bool = True
    show_footer_signature: bool = True
    logo_url: str = ""
    stamp_url: str = ""
    signature_name: str = ""
    signature_title: str = ""
    paper_format: str = "A5"
    compact_header: bool = False


class PrintSettingsUpdate(PrintSettingsBase):
    pass


class PrintSettingsResponse(PrintSettingsBase):
    id: str
    updated_by: str | None = None
    updated_at: datetime

    class Config:
        from_attributes = True
