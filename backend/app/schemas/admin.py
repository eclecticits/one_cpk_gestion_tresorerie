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
    active: bool
    must_change_password: bool
    created_at: str | None = None


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
    footer_text: str
    show_header_logo: bool
    show_footer_signature: bool
    logo_url: str
    stamp_url: str
    signature_name: str
    signature_title: str
    paper_format: str
    compact_header: bool


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
    footer_text: str | None = None
    show_header_logo: bool | None = None
    show_footer_signature: bool | None = None
    logo_url: str | None = None
    stamp_url: str | None = None
    signature_name: str | None = None
    signature_title: str | None = None
    paper_format: str | None = None
    compact_header: bool | None = None


class PrintSettingsResponse(BaseModel):
    data: PrintSettingsOut | None


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
