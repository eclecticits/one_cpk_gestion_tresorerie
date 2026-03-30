from __future__ import annotations

import logging
import re

import httpx

logger = logging.getLogger("onec_cpk_api.whatsapp")


def normalize_whatsapp_numbers(raw: str | None) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"[,\n;]+", raw)
    seen: set[str] = set()
    numbers: list[str] = []
    for part in parts:
        item = part.strip()
        if not item:
            continue
        item = item.replace(" ", "")
        if item.startswith("+"):
            normalized = "+" + re.sub(r"\D", "", item)
        else:
            normalized = re.sub(r"\D", "", item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        numbers.append(normalized)
    return numbers


async def send_whatsapp_message(api_url: str, api_key: str, number: str, message: str) -> None:
    if not api_url or not number or not message:
        return
    headers = {}
    if api_key:
        headers["apikey"] = api_key
    payload = {"number": number, "text": message}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(api_url, json=payload, headers=headers)
            resp.raise_for_status()
    except httpx.HTTPError:
        logger.exception("WhatsApp send failed for %s", number)
