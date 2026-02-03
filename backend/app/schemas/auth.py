from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    must_change_password: bool = False
    role: str


class ChangePasswordRequest(BaseModel):
    # If must_change_password is true, current_password may be omitted.
    current_password: str | None = None
    new_password: str = Field(min_length=6)


class BootstrapAdminRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    nom: str
    prenom: str
    bootstrap_password: str


class MeResponse(BaseModel):
    id: str
    email: EmailStr
    nom: str | None = None
    prenom: str | None = None
    role: str
    active: bool
    must_change_password: bool
    created_at: str | None = None
