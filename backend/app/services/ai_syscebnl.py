from __future__ import annotations

import json
import logging
from typing import Any

from app.core.ai.base import AIProviderError
from app.core.ai.service import get_ai_service

logger = logging.getLogger("onec_cpk_ai.syscebnl")

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

_SYSCEBNL_SYSTEM = (
    "Tu es un expert comptable SYSCEBNL (OHADA). "
    "Réponds UNIQUEMENT en JSON valide selon le format demandé."
)


async def classify_expense_with_gemma(description: str) -> dict[str, Any]:
    """Classifie une dépense via AIService (provider configurable — Anthropic ou Ollama)."""
    prompt = f"{SYSCEBNL_PROMPT}\n\nLibellé à classer : '{description}'"
    try:
        service = get_ai_service()
        ai_response = await service.generate(prompt, system=_SYSCEBNL_SYSTEM, temperature=0.1)
        content = ai_response.content
    except AIProviderError as exc:
        logger.warning("syscebnl.provider_unavailable error=%s", exc)
        return {"error": f"IA indisponible: {exc}"}

    try:
        return json.loads(content) if content else {"error": "Réponse vide de l'IA"}
    except json.JSONDecodeError:
        return {"error": "Réponse JSON invalide", "raw": content[:200]}
