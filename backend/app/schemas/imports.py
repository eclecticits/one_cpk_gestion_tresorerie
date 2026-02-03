from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


ImportStatus = Literal["success", "error", "partial"]
ImportCategory = Literal["sec", "en_cabinet", "independant", "salarie"]


class ImportsHistoryResponse(BaseModel):
    id: str
    filename: str
    category: str
    imported_by: str | None = None
    rows_imported: int
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class ImportsHistoryList(BaseModel):
    items: list[ImportsHistoryResponse]
    total: int
