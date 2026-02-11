from __future__ import annotations

from pydantic import BaseModel


class PermissionOut(BaseModel):
    id: int
    code: str
    description: str | None = None


class RoleOut(BaseModel):
    id: int
    code: str
    label: str | None = None
    description: str | None = None
    permissions: list[str] = []


class RoleCreate(BaseModel):
    code: str
    label: str | None = None
    description: str | None = None


class RoleUpdate(BaseModel):
    label: str | None = None
    description: str | None = None


class RolePermissionsUpdate(BaseModel):
    role_id: int
    permission_codes: list[str]


class RolePermissionsPayload(BaseModel):
    roles: list[RolePermissionsUpdate]
