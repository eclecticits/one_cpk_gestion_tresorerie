from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


# ----------------------
# Users
# ----------------------


class UserCreateRequest(BaseModel):
    email: EmailStr
    nom: str
    prenom: str
    role: str = Field(default="reception")


class UserUpdateRequest(BaseModel):
    email: EmailStr | None = None
    nom: str | None = None
    prenom: str | None = None
    role: str | None = None


class ToggleStatusRequest(BaseModel):
    user_id: str
    current_status: bool


class ResetPasswordRequest(BaseModel):
    user_id: str


class SetUserPasswordRequest(BaseModel):
    user_id: str
    password: str = Field(min_length=6)
    force_change: bool = False


class DeleteUserRequest(BaseModel):
    user_id: str


class UserOut(BaseModel):
    id: str
    email: EmailStr
    nom: str | None = None
    prenom: str | None = None
    role: str
    role_id: int | None = None
    active: bool
    must_change_password: bool
    is_first_login: bool
    is_email_verified: bool
    created_at: str | None = None


class UserListOut(BaseModel):
    items: list[UserOut]
    total: int
    page: int
    page_size: int


# ----------------------
# Rubriques
# ----------------------


class RubriqueCreateRequest(BaseModel):
    code: str
    libelle: str
    description: str | None = None
    active: bool = True


class RubriqueUpdateRequest(BaseModel):
    code: str | None = None
    libelle: str | None = None
    description: str | None = None
    active: bool | None = None


class RubriqueOut(BaseModel):
    id: str
    code: str
    libelle: str
    description: str | None = None
    active: bool


# ----------------------
# Print settings
# ----------------------


class PrintSettingsOut(BaseModel):
    id: str
    organization_name: str
    organization_subtitle: str
    header_text: str
    address: str
    phone: str
    email: str
    website: str
    bank_name: str
    bank_account: str
    mobile_money_name: str
    mobile_money_number: str
    pied_de_page_legal: str
    afficher_qr_code: bool
    show_header_logo: bool
    show_footer_signature: bool
    logo_url: str
    stamp_url: str
    recu_label_signature: str
    recu_nom_signataire: str
    sortie_label_signature: str
    sortie_nom_signataire: str
    sortie_sig_label_1: str
    sortie_sig_label_2: str
    sortie_sig_label_3: str
    sortie_sig_hint: str
    show_sortie_qr: bool
    sortie_qr_base_url: str
    show_sortie_watermark: bool
    sortie_watermark_text: str
    sortie_watermark_opacity: float
    paper_format: str
    compact_header: bool
    req_titre_officiel: str
    req_label_gauche: str
    req_nom_gauche: str
    req_label_droite: str
    req_nom_droite: str
    trans_titre_officiel: str
    trans_label_gauche: str
    trans_nom_gauche: str
    trans_label_droite: str
    trans_nom_droite: str
    default_currency: str
    secondary_currency: str
    exchange_rate: float
    fiscal_year: int
    budget_alert_threshold: int
    budget_block_overrun: bool
    budget_force_roles: str


class PrintSettingsUpdateRequest(BaseModel):
    organization_name: str | None = None
    organization_subtitle: str | None = None
    header_text: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    bank_name: str | None = None
    bank_account: str | None = None
    mobile_money_name: str | None = None
    mobile_money_number: str | None = None
    pied_de_page_legal: str | None = None
    afficher_qr_code: bool | None = None
    show_header_logo: bool | None = None
    show_footer_signature: bool | None = None
    logo_url: str | None = None
    stamp_url: str | None = None
    recu_label_signature: str | None = None
    recu_nom_signataire: str | None = None
    sortie_label_signature: str | None = None
    sortie_nom_signataire: str | None = None
    sortie_sig_label_1: str | None = None
    sortie_sig_label_2: str | None = None
    sortie_sig_label_3: str | None = None
    sortie_sig_hint: str | None = None
    show_sortie_qr: bool | None = None
    sortie_qr_base_url: str | None = None
    show_sortie_watermark: bool | None = None
    sortie_watermark_text: str | None = None
    sortie_watermark_opacity: float | None = None
    paper_format: str | None = None
    compact_header: bool | None = None
    req_titre_officiel: str | None = None
    req_label_gauche: str | None = None
    req_nom_gauche: str | None = None
    req_label_droite: str | None = None
    req_nom_droite: str | None = None
    trans_titre_officiel: str | None = None
    trans_label_gauche: str | None = None
    trans_nom_gauche: str | None = None
    trans_label_droite: str | None = None
    trans_nom_droite: str | None = None
    default_currency: str | None = None
    secondary_currency: str | None = None
    exchange_rate: float | None = None
    fiscal_year: int | None = None
    budget_alert_threshold: int | None = None
    budget_block_overrun: bool | None = None
    budget_force_roles: str | None = None


class PrintSettingsResponse(BaseModel):
    data: PrintSettingsOut | None


# ----------------------
# Notification settings
# ----------------------


class NotificationSettingsOut(BaseModel):
    id: str
    email_expediteur: str
    email_president: str
    emails_bureau_cc: str
    email_tresorier: str
    emails_bureau_sortie_cc: str
    email_validation_1: str
    email_validation_final: str
    max_caisse_amount: int
    smtp_password: str
    smtp_host: str
    smtp_port: int
    updated_by: str | None = None
    updated_at: str | None = None


class NotificationSettingsUpdateRequest(BaseModel):
    email_expediteur: str | None = None
    email_president: str | None = None
    emails_bureau_cc: str | None = None
    email_tresorier: str | None = None
    emails_bureau_sortie_cc: str | None = None
    email_validation_1: str | None = None
    email_validation_final: str | None = None
    max_caisse_amount: int | None = None
    smtp_password: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None


class NotificationSettingsResponse(BaseModel):
    data: NotificationSettingsOut | None


# ----------------------
# Menu permissions
# ----------------------


class MenuPermissionsOut(BaseModel):
    menus: list[str]


class SetMenuPermissionsRequest(BaseModel):
    menus: list[str] = Field(default_factory=list)


# ----------------------
# System roles (user_roles)
# ----------------------


class UserRoleAssignmentCreateRequest(BaseModel):
    user_id: str
    role: str


class UserRoleAssignmentOut(BaseModel):
    id: str
    user_id: str
    role: str
    created_at: str
    created_by: str | None = None


# ----------------------
# Requisition approvers
# ----------------------


class SimpleUserInfo(BaseModel):
    nom: str | None = None
    prenom: str | None = None
    email: EmailStr


class RequisitionApproverCreateRequest(BaseModel):
    user_id: str
    active: bool = True
    notes: str | None = None


class RequisitionApproverUpdateRequest(BaseModel):
    active: bool | None = None
    notes: str | None = None


class RequisitionApproverOut(BaseModel):
    id: str
    user_id: str
    active: bool
    added_at: str
    notes: str | None = None
    user: SimpleUserInfo | None = None
