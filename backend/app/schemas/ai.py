from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class RequisitionScoreRequest(BaseModel):
    requisition_id: uuid.UUID
    lookback_days: int = Field(default=365, ge=7, le=3650)
    min_history: int = Field(default=8, ge=3, le=200)


class RequisitionScoreBatchRequest(BaseModel):
    requisition_ids: list[uuid.UUID] = Field(default_factory=list)
    lookback_days: int = Field(default=365, ge=7, le=3650)
    min_history: int = Field(default=8, ge=3, le=200)


class RequisitionScoreResponse(BaseModel):
    requisition_id: uuid.UUID
    risk_score: int
    confidence_score: int
    level: str
    explanation: str
    reasons: list[str]
    segment: str
    sample_size: int
    mean_amount: float | None
    std_amount: float | None
    z_score: float | None
    duplicate_candidates: int


class CashForecastResponse(BaseModel):
    solde_actuel: float
    lookback_days: int
    horizon_days: int
    reserve_threshold: float
    encaissements_total: float
    sorties_total: float
    net_total: float
    baseline_projection: float
    stress_projection: float
    pending_total: float
    pressure_ratio: float
    autonomy_days: int | None
    risk_level: str
    risk_message: str


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = Field(default_factory=list)


class ChatResponse(BaseModel):
    answer: str
    widget: dict | None = None
    suggestions: list[str] | None = None
