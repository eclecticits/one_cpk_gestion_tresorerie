from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from uuid import UUID
from app.schemas.admin import UserOut


ImportStatus = Literal["success", "error", "partial"]
ImportCategory = Literal["sec", "en_cabinet", "independant", "salarie"]


class ImportsHistoryResponse(BaseModel):
    id: UUID
    filename: str
    category: str
    imported_by: UUID | None = None
    rows_imported: int
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class ImportsHistoryResponseWithUser(ImportsHistoryResponse):
    imported_by_user: UserOut | None = None


class ImportsHistoryList(BaseModel):
    items: list[ImportsHistoryResponse]
    total: int
