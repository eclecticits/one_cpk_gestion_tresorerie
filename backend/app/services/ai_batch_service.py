from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai.base import AIProviderError
from app.core.ai.service import get_ai_service, get_ai_service_for_org
from app.services.ai_memory_service import AIMemoryService
from app.services.ai_syscebnl import SYSCEBNL_PROMPT

logger = logging.getLogger("onec_cpk_ai.batch")


async def _classify_single(transaction: dict[str, Any], service=None) -> dict[str, Any]:
    """Classifie une transaction via AIService.

    `service` est le provider résolu par organisation (résidence des données) ;
    à défaut, on retombe sur la factory basée sur l'environnement.
    """
    prompt = (
        f"{SYSCEBNL_PROMPT}\n\n"
        f"Libellé : '{transaction.get('label', '')}' - Montant : {transaction.get('amount', '')} FC"
    )
    try:
        svc = service or get_ai_service()
        ai_response = await svc.generate(prompt, temperature=0.1)
        ai_data = json.loads(ai_response.content or "{}")
        if isinstance(ai_data, dict):
            ai_data.setdefault("source", "ai")
        return {**transaction, "ai_classification": ai_data}
    except (AIProviderError, json.JSONDecodeError, Exception) as exc:
        logger.warning("batch.classify_single_failed label=%s error=%s", transaction.get("label"), exc)
        return {**transaction, "ai_classification": {"error": "Échec classification", "source": "ai"}}


class AIBatchProcessor:
    @classmethod
    async def classify_single(cls, transaction: dict[str, Any], *_args, **_kwargs) -> dict[str, Any]:
        """Compatibilité — délègue à _classify_single (le client httpx n'est plus utilisé)."""
        return await _classify_single(transaction)

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
        results: list[dict[str, Any]] = [{}] * len(transactions)
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
                results[idx] = {**tx, "ai_classification": memory_hit}
            else:
                pending.append((idx, tx))

        if cache:
            await db.commit()

        if pending:
            # Provider résolu par organisation (résidence des données), construit
            # une seule fois pour tout le lot ; repli env géré par _classify_single.
            try:
                service = await get_ai_service_for_org(db, org_id)
            except Exception:
                service = None
            tasks = [_classify_single(tx, service) for _, tx in pending]
            classified = await asyncio.gather(*tasks)
            for (idx, _), item in zip(pending, classified):
                results[idx] = item

        return results
