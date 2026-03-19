from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx

from app.services.ai_memory_service import AIMemoryService
from app.services.ai_syscebnl import SYSCEBNL_PROMPT
from sqlalchemy.ext.asyncio import AsyncSession


class AIBatchProcessor:
    OLLAMA_URL = (os.getenv("OLLAMA_URL") or "http://localhost:11434/api/generate").strip()
    MODEL = (os.getenv("OLLAMA_MODEL") or "gemma2:2b").strip()

    @classmethod
    async def classify_single(cls, transaction: dict, client: httpx.AsyncClient) -> dict[str, Any]:
        prompt = (
            f"{SYSCEBNL_PROMPT}\n\n"
            f"Libellé : '{transaction.get('label', '')}' - Montant : {transaction.get('amount', '')} FC"
        )

        payload = {
            "model": cls.MODEL,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }

        try:
            response = await client.post(cls.OLLAMA_URL, json=payload, timeout=10.0)
            response.raise_for_status()
            ai_data = json.loads(response.json().get("response", "") or "{}")
            if isinstance(ai_data, dict):
                ai_data.setdefault("source", "ai")
            return {**transaction, "ai_classification": ai_data}
        except Exception:
            return {**transaction, "ai_classification": {"error": "Échec classification", "source": "ai"}}

    @classmethod
    async def process_batch(
        cls,
        transactions: list[dict[str, Any]],
        db: AsyncSession,
        org_id: int,
    ) -> list[dict[str, Any]]:
        if not transactions:
            return []

        cache = await AIMemoryService.load_cache(org_id, db)
        results: list[dict[str, Any]] = []
        pending: list[tuple[int, dict[str, Any]]] = []

        for idx, tx in enumerate(transactions):
            label = str(tx.get("label", "")).strip()
            memory_hit = await AIMemoryService.get_known_classification(
                label=label,
                org_id=org_id,
                db=db,
                cache=cache,
            )
            if memory_hit:
                results.append({**tx, "ai_classification": memory_hit})
            else:
                results.append({})
                pending.append((idx, tx))

        if cache:
            await db.commit()

        if not pending:
            return results

        async with httpx.AsyncClient() as client:
            tasks = [cls.classify_single(tx, client) for _, tx in pending]
            classified = await asyncio.gather(*tasks)

        for (idx, _), item in zip(pending, classified):
            results[idx] = item

        return results
