from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(slots=True)
class ScoreResult:
    risk_score: int
    confidence_score: int
    level: str
    explanation: str
    reasons: list[str]
    sample_size: int
    mean_amount: float | None
    std_amount: float | None
    z_score: float | None
    duplicate_candidates: int


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _safe_std(values: list[float], mean: float) -> float:
    if not values:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def compute_requisition_score(
    amount: float,
    history_amounts: list[float],
    duplicate_candidates: int,
    min_history: int,
) -> ScoreResult:
    sample_size = len(history_amounts)
    if sample_size < min_history:
        explanation = "Historique insuffisant pour un score précis."
        reasons = [
            f"Seulement {sample_size} réquisitions comparables disponibles.",
            "Le score est basé sur des heuristiques conservatrices.",
        ]
        base_risk = 35
        if duplicate_candidates > 0:
            base_risk = 70
            reasons.append(f"{duplicate_candidates} montant(s) très proche(s) détecté(s).")
        return ScoreResult(
            risk_score=base_risk,
            confidence_score=40,
            level="MOYEN" if base_risk >= 60 else "FAIBLE",
            explanation=explanation,
            reasons=reasons,
            sample_size=sample_size,
            mean_amount=None,
            std_amount=None,
            z_score=None,
            duplicate_candidates=duplicate_candidates,
        )

    mean_amount = _mean(history_amounts)
    std_amount = _safe_std(history_amounts, mean_amount)
    z_score = 0.0
    if std_amount > 0:
        z_score = (amount - mean_amount) / std_amount

    # Risk formula: magnitude of deviation + duplicate signal.
    z_component = _clamp(abs(z_score) * 18.0, 0.0, 85.0)
    dup_component = _clamp(duplicate_candidates * 15.0, 0.0, 40.0)
    risk_score = int(_clamp(z_component + dup_component, 0.0, 100.0))

    # Confidence grows with history size and stable variance.
    confidence_score = int(_clamp(40.0 + (sample_size / 3.0), 0.0, 95.0))
    if std_amount == 0:
        confidence_score = int(_clamp(confidence_score - 15.0, 0.0, 95.0))

    if risk_score >= 75:
        level = "ELEVE"
    elif risk_score >= 45:
        level = "MOYEN"
    else:
        level = "FAIBLE"

    reasons: list[str] = []
    explanation = "Montant cohérent avec l'historique."
    if std_amount > 0 and abs(z_score) >= 2.5:
        explanation = "Montant significativement supérieur aux habitudes."
        reasons.append(f"Écart de {abs(z_score):.1f} écarts-types par rapport à la moyenne.")
    elif std_amount > 0 and abs(z_score) >= 1.5:
        explanation = "Montant plus élevé que la tendance habituelle."
        reasons.append(f"Écart de {abs(z_score):.1f} écarts-types par rapport à la moyenne.")
    elif std_amount == 0 and amount > mean_amount:
        explanation = "Montant supérieur à un historique très stable."
        reasons.append("Historique de montants quasi identiques.")

    if duplicate_candidates > 0:
        reasons.append(f"{duplicate_candidates} montant(s) très proche(s) détecté(s) récemment.")

    if not reasons:
        reasons.append("Aucun signal d'anomalie détecté.")

    return ScoreResult(
        risk_score=risk_score,
        confidence_score=confidence_score,
        level=level,
        explanation=explanation,
        reasons=reasons,
        sample_size=sample_size,
        mean_amount=mean_amount,
        std_amount=std_amount,
        z_score=z_score if std_amount > 0 else None,
        duplicate_candidates=duplicate_candidates,
    )
