from __future__ import annotations

import uuid

from typing import Literal

from pydantic import BaseModel, Field


class RequisitionScoreRequest(BaseModel):
    requisition_id: uuid.UUID
    lookback_days: int = Field(default=365, ge=7, le=3650)
    min_history: int = Field(default=8, ge=3, le=200)


class RequisitionScoreBatchRequest(BaseModel):
    requisition_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
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
    # Rôle contraint : l'historique vient du client, un rôle libre permettrait
    # d'injecter un faux tour de parole « système » dans le prompt.
    role: Literal["user", "assistant"]
    content: str = Field(max_length=2000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    # Bornes de coût : sans elles, un historique long fait grossir le prompt
    # sans limite, alors que ai_max_context_chars ne borne que les données.
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)


class ChatResponse(BaseModel):
    answer: str
    widget: dict | None = None
    suggestions: list[str] | None = None


class ExpenseClassifyRequest(BaseModel):
    description: str = Field(min_length=2, max_length=500)


class ExpenseClassifyResponse(BaseModel):
    compte: str | None = None
    categorie: str | None = None
    explication: str | None = None
    taux_confiance: float | None = None
    error: str | None = None
    raw: str | None = None


class ExpenseBatchTransaction(BaseModel):
    label: str = Field(min_length=1, max_length=255)
    amount: float = Field(default=0)


class ExpenseBatchClassifyRequest(BaseModel):
    transactions: list[ExpenseBatchTransaction] = Field(default_factory=list, max_length=200)


class ExpenseBatchClassifyResult(BaseModel):
    label: str
    amount: float
    ai_classification: dict
