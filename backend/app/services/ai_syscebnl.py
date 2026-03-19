from __future__ import annotations

import json
import os
from typing import Any

import httpx

SYSCEBNL_PROMPT = """
Tu es un expert comptable certifié en RDC, spécialisé dans le SYSCEBNL (OHADA).
Ta mission est de classer les libellés de dépenses des Conseils Provinciaux.

RÈGLES DE CLASSIFICATION :
1. CLASSE 6 (Charges) :
   - 60 : Achats (Fournitures de bureau, carburant, petit matériel).
   - 61 : Services extérieurs (Loyer, entretien, primes d'assurance).
   - 62 : Transports (Frais de mission, voyages officiels).
   - 63 : Services extérieurs B (Honoraires, télécoms, réception).
   - 64 : Impôts et taxes.
   - 66 : Charges de personnel (Salaires, gratifications).
2. CLASSE 2 (Investissements) :
   - 24 : Matériel roulant (Achat de véhicules de fonction).
   - 21 : Immobilisations incorporelles (Logiciels, licences).
   - 23 : Bâtiments et installations.

INSTRUCTIONS :
- Réponds UNIQUEMENT au format JSON.
- Analyse le libellé fourni et déduis le compte approprié.
- Si le libellé est "Achat 5 ordinateurs", utilise le compte 21 ou 24 selon la nature.

FORMAT DE SORTIE :
{
  "compte": "60xxx",
  "categorie": "Achats de fournitures",
  "explication": "Brève raison du choix",
  "taux_confiance": 0.95
}
""".strip()


async def classify_expense_with_gemma(description: str) -> dict[str, Any]:
    ollama_url = (os.getenv("OLLAMA_URL") or "http://localhost:11434/api/generate").strip()
    model = (os.getenv("OLLAMA_MODEL") or "gemma2:2b").strip()
    if not ollama_url:
        return {"error": "OLLAMA_URL manquant"}

    prompt_complet = f"{SYSCEBNL_PROMPT}\n\nLibellé à classer : '{description}'"
    payload = {
        "model": model,
        "prompt": prompt_complet,
        "stream": False,
        "format": "json",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(ollama_url, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        return {"error": f"IA locale indisponible: {exc}"}

    content = data.get("response", "")
    try:
        return json.loads(content) if content else {"error": "Réponse vide de l'IA"}
    except json.JSONDecodeError:
        return {"error": "Réponse JSON invalide", "raw": content}
