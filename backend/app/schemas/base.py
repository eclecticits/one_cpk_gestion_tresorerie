from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class DecimalBaseModel(BaseModel):
    model_config = ConfigDict(json_encoders={Decimal: str})
