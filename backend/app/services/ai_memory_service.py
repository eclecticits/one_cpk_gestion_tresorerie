from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from rapidfuzz import process as fuzz_process
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.standard_classification import StandardClassification


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AIMemoryService:
    @classmethod
    async def load_cache(cls, org_id: int, db: AsyncSession) -> dict[str, StandardClassification]:
        res = await db.execute(
            select(StandardClassification).where(StandardClassification.organisation_id == org_id)
        )
        return {row.raw_label: row for row in res.scalars().all()}

    @classmethod
    def _build_payload(
        cls,
        account: str | None,
        explanation: str,
        confidence: float,
        source: str,
    ) -> dict[str, Any]:
        return {
            "compte": account,
            "explication": explanation,
            "taux_confiance": confidence,
            "source": source,
        }

    @classmethod
    def _touch(cls, entry: StandardClassification) -> None:
        entry.occurrence_count = int(entry.occurrence_count or 0) + 1
        entry.last_used = _utcnow()

    @classmethod
    async def get_known_classification(
        cls,
        label: str,
        org_id: int,
        db: AsyncSession,
        cache: dict[str, StandardClassification] | None = None,
        fuzzy_threshold: int = 90,
    ) -> dict[str, Any] | None:
        if not label:
            return None

        if cache is None:
            cache = await cls.load_cache(org_id, db)

        exact = cache.get(label)
        if exact:
            cls._touch(exact)
            return cls._build_payload(
                exact.assigned_account,
                "Récupéré de la mémoire locale (validé précédemment).",
                1.0,
                "memory",
            )

        labels = list(cache.keys())
        if not labels:
            return None

        match = fuzz_process.extractOne(label, labels, score_cutoff=fuzzy_threshold)
        if not match:
            return None

        best_label, score, _ = match
        entry = cache.get(best_label)
        if not entry:
            return None

        cls._touch(entry)
        return cls._build_payload(
            entry.assigned_account,
            f"Ressemble à '{best_label}' (score: {score}%).",
            float(score) / 100.0,
            "memory",
        )

    @classmethod
    async def upsert_classification(
        cls,
        label: str,
        account: str,
        org_id: int,
        db: AsyncSession,
        confidence: float = 1.0,
    ) -> StandardClassification:
        res = await db.execute(
            select(StandardClassification).where(
                StandardClassification.organisation_id == org_id,
                StandardClassification.raw_label == label,
            )
        )
        existing = res.scalar_one_or_none()
        if existing:
            existing.assigned_account = account
            existing.confidence_score = confidence
            cls._touch(existing)
            await db.commit()
            return existing

        entry = StandardClassification(
            organisation_id=org_id,
            raw_label=label,
            assigned_account=account,
            confidence_score=confidence,
            occurrence_count=1,
            last_used=_utcnow(),
        )
        db.add(entry)
        await db.commit()
        return entry
