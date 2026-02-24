from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class CommissionRole(str, Enum):
    PRESIDENT = "PRESIDENT"
    DELEGUE = "DELEGUE"
    MEMBRE = "MEMBRE"
    ASSISTANT = "ASSISTANT"


class CommissionMemberUserOut(BaseModel):
    id: str
    nom: str | None = None
    prenom: str | None = None
    email: str | None = None


class CommissionMemberBase(BaseModel):
    user_id: str | None = None
    full_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    matricule: str | None = Field(default=None, max_length=50)
    role_type: CommissionRole = CommissionRole.MEMBRE
    custom_title: str | None = Field(default=None, max_length=150)
    is_signer: bool | None = None


class CommissionMemberCreate(CommissionMemberBase):
    pass


class CommissionMemberUpdate(BaseModel):
    user_id: str | None = None
    full_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    matricule: str | None = Field(default=None, max_length=50)
    role_type: CommissionRole | None = None
    custom_title: str | None = Field(default=None, max_length=150)
    is_signer: bool | None = None


class CommissionMemberOut(BaseModel):
    id: int
    service_id: int
    user_id: str | None = None
    full_name: str
    email: str | None = None
    matricule: str | None = None
    role_type: CommissionRole
    custom_title: str | None = None
    is_signer: bool
    created_at: datetime
    user: CommissionMemberUserOut | None = None


class CommissionMemberLookupOut(BaseModel):
    full_name: str
    email: str | None = None
    matricule: str | None = None


class CommissionMemberMultiAssign(BaseModel):
    service_ids: list[int]
    user_id: str | None = None
    full_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    matricule: str | None = Field(default=None, max_length=50)
    role_type: CommissionRole = CommissionRole.MEMBRE
    custom_title: str | None = Field(default=None, max_length=150)
    is_signer: bool | None = None
