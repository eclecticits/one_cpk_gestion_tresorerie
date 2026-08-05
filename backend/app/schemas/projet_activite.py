from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProjetActiviteBase(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    libelle: str = Field(min_length=1, max_length=255)
    type: str = Field(default="PROJET", pattern="^(PROJET|ACTIVITE)$")
    description: str | None = None
    is_active: bool = True


class ProjetActiviteCreate(ProjetActiviteBase):
    pass


class ProjetActiviteUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50)
    libelle: str | None = Field(default=None, min_length=1, max_length=255)
    type: str | None = Field(default=None, pattern="^(PROJET|ACTIVITE)$")
    description: str | None = None
    is_active: bool | None = None


class ProjetActiviteResponse(ProjetActiviteBase):
    id: int
    organisation_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
