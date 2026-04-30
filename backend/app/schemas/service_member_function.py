from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ServiceMemberFunctionBase(BaseModel):
    label: str = Field(..., min_length=1, max_length=150)
    sort_order: int | None = None
    is_default: bool | None = None
    is_active: bool | None = None


class ServiceMemberFunctionCreate(ServiceMemberFunctionBase):
    pass


class ServiceMemberFunctionUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=150)
    sort_order: int | None = None
    is_active: bool | None = None


class ServiceMemberFunctionOut(BaseModel):
    id: int
    service_id: int
    label: str
    sort_order: int
    is_default: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime
