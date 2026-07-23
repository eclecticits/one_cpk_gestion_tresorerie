"""
Manager Agent — Secrétariat
============================
Orchestrateur central inspiré du pattern Agentor (Manager/Triage Agent).
Un seul agent LLM qui pilote les agents spécialisés (Agenda, Réunions,
Documents, Approbations) via OpenAI function calling.

Architecture :
  User message
      ↓
  Manager Agent (OpenAI Chat Completions + tools)
      ↓ appels outils selon besoin
  agent_agenda  /  agent_reunion  /  agent_documents  /  agent_approbations
      ↓
  Réponse consolidée → utilisateur

Le Manager ne remplace PAS les routes existantes ; il s'y greffe comme
couche conversationnelle.
"""
from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import has_permission
from app.core.ai.base import AIUnavailableError
from app.core.ai.service import get_ai_service_for_org
from app.models.user import User
from app.modules.secretariat.services.agent_manager import (
    get_recommended_actions,
    get_secretariat_overview,
    get_pending_approvals,
)
from app.modules.secretariat.services.agenda_agent import (
    create_agenda_item,
    list_agenda_items,
    get_agenda_overview,
)
from app.modules.secretariat.services.documents_agent import (
    list_documents,
    generate_synthesis,
)
from app.modules.secretariat.services.reunion_agent import (
    create_meeting,
    list_meetings,
    generate_minutes_draft,
    generate_agenda,
)

logger = logging.getLogger(__name__)

# ── Prompt système ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Tu es l'Agent Manager du Secrétariat de l'organisation.
Tu coordonnes des agents spécialisés via des outils :

• Agent Agenda     — échéances, rappels, suivi du planning
• Agent Réunions   — planification, ordre du jour, procès-verbaux, décisions
• Agent Documents  — gestion documentaire, résumés, fiches de synthèse
• Agent Approbations — suivi des validations et approbations en attente

Règles :
1. Analyse la demande de l'utilisateur et identifie les outils appropriés.
2. Chaîne les appels si plusieurs agents sont nécessaires.
3. Réponds TOUJOURS en français, de façon concise et professionnelle.
4. Si une action a été réalisée, confirme-la explicitement.
5. Si tu ne peux pas accomplir une demande avec tes outils, dis-le clairement.
6. Ne génère pas de données fictives — travaille uniquement avec les données réelles retournées par tes outils.
"""


TOOL_REQUIRED_PERMISSIONS: dict[str, str] = {
    "creer_echeance_agenda": "secretariat.manage_agenda",
    "creer_reunion": "secretariat.manage_meetings",
    "generer_ordre_du_jour": "secretariat.generate_meeting_documents",
    "generer_pv_reunion": "secretariat.generate_meeting_documents",
}


async def _assert_tool_permission(name: str, user: User, db: AsyncSession) -> None:
    permission = TOOL_REQUIRED_PERMISSIONS.get(name)
    if permission is None:
        return
    checker = has_permission(permission)
    await checker(user=user, db=db)

# ── Définitions des outils (OpenAI function calling) ─────────────────────────

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_tableau_de_bord",
            "description": (
                "Retourne une vue d'ensemble du secrétariat : statistiques des tâches, "
                "brouillons de courrier, approbations, agenda, réunions et actions recommandées."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_actions_recommandees",
            "description": "Liste les actions prioritaires recommandées par le système selon l'état actuel du secrétariat.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lister_echeances_agenda",
            "description": "Liste les échéances et tâches de l'agenda du secrétariat.",
            "parameters": {
                "type": "object",
                "properties": {
                    "statut": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed", "cancelled", "overdue"],
                        "description": "Filtrer par statut (optionnel)",
                    },
                    "priorite": {
                        "type": "string",
                        "enum": ["low", "normal", "high", "urgent"],
                        "description": "Filtrer par priorité (optionnel)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "creer_echeance_agenda",
            "description": "Crée une nouvelle échéance ou tâche dans l'agenda du secrétariat.",
            "parameters": {
                "type": "object",
                "properties": {
                    "titre": {"type": "string", "description": "Titre de l'échéance (obligatoire)"},
                    "description": {"type": "string", "description": "Description détaillée (optionnel)"},
                    "priorite": {
                        "type": "string",
                        "enum": ["low", "normal", "high", "urgent"],
                        "description": "Priorité (défaut: normal)",
                    },
                    "type_echeance": {
                        "type": "string",
                        "enum": ["meeting", "deadline", "followup", "approval", "mail", "document", "task", "other"],
                        "description": "Type d'échéance (défaut: other)",
                    },
                    "date_echeance": {
                        "type": "string",
                        "description": "Date limite au format ISO 8601 (ex: 2026-06-20T10:00:00Z)",
                    },
                },
                "required": ["titre"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lister_reunions",
            "description": "Liste les réunions (passées et à venir) du secrétariat.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "creer_reunion",
            "description": "Planifie une nouvelle réunion.",
            "parameters": {
                "type": "object",
                "properties": {
                    "titre": {"type": "string", "description": "Intitulé de la réunion (obligatoire)"},
                    "type_reunion": {
                        "type": "string",
                        "description": "Type : conseil, comité, ordinaire, extraordinaire, technique, administrative (défaut: administrative)",
                    },
                    "date": {"type": "string", "description": "Date au format YYYY-MM-DD"},
                    "lieu": {"type": "string", "description": "Lieu de la réunion"},
                },
                "required": ["titre"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generer_ordre_du_jour",
            "description": "Génère un ordre du jour automatique pour une réunion existante.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reunion_id": {"type": "integer", "description": "Identifiant numérique de la réunion"},
                    "instructions": {"type": "string", "description": "Instructions spécifiques pour l'ordre du jour"},
                },
                "required": ["reunion_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generer_pv_reunion",
            "description": "Génère un projet de procès-verbal (PV) pour une réunion existante.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reunion_id": {"type": "integer", "description": "Identifiant numérique de la réunion"},
                    "instructions": {"type": "string", "description": "Instructions spécifiques pour le PV"},
                },
                "required": ["reunion_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lister_documents",
            "description": "Liste les documents du secrétariat.",
            "parameters": {
                "type": "object",
                "properties": {
                    "statut": {
                        "type": "string",
                        "enum": ["draft", "active", "archived", "pending_approval"],
                        "description": "Filtrer par statut (optionnel)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generer_synthese_document",
            "description": "Génère une fiche de synthèse IA pour un document existant.",
            "parameters": {
                "type": "object",
                "properties": {
                    "document_id": {"type": "integer", "description": "Identifiant numérique du document"},
                },
                "required": ["document_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lister_approbations_en_attente",
            "description": "Liste toutes les approbations en attente de décision.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

# ── Exécution des outils ──────────────────────────────────────────────────────

async def _execute_tool(
    name: str,
    args: dict,
    db: AsyncSession,
    user: User,
    organisation_id: int,
) -> Any:
    """Dispatch d'un appel d'outil vers le service approprié."""
    await _assert_tool_permission(name, user, db)

    if name == "get_tableau_de_bord":
        return await get_secretariat_overview(db, user, organisation_id)

    if name == "get_actions_recommandees":
        return await get_recommended_actions(db, user, organisation_id)

    if name == "lister_echeances_agenda":
        items = await list_agenda_items(
            db,
            organisation_id,
            statut=args.get("statut"),
            priorite=args.get("priorite"),
        )
        return [
            {
                "id": i.id,
                "titre": i.title,
                "type": i.item_type,
                "priorite": i.priority,
                "statut": i.status,
                "echeance": i.due_at.isoformat() if i.due_at else None,
            }
            for i in items
        ]

    if name == "creer_echeance_agenda":
        from datetime import datetime, timezone

        due_at = None
        raw_date = args.get("date_echeance")
        if raw_date:
            try:
                due_at = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            except ValueError:
                due_at = None

        payload = SimpleNamespace(
            title=args["titre"],
            description=args.get("description"),
            item_type=args.get("type_echeance", "other"),
            priority=args.get("priorite", "normal"),
            status="pending",
            due_at=due_at,
            start_at=None,
            assigned_to_user_id=None,
            target_type=None,
            target_id=None,
            metadata_json={"source": "manager_agent"},
        )
        item = await create_agenda_item(db, user, organisation_id, payload)
        return {"id": item.id, "titre": item.title, "statut": item.status, "echeance": item.due_at.isoformat() if item.due_at else None}

    if name == "lister_reunions":
        meetings = await list_meetings(db, organisation_id)
        return [
            {
                "id": m.id,
                "titre": m.title,
                "type": m.meeting_type,
                "date": m.meeting_date.isoformat() if m.meeting_date else None,
                "lieu": m.location,
                "statut": m.status,
            }
            for m in meetings
        ]

    if name == "creer_reunion":
        from datetime import date as date_type

        raw = args.get("date")
        meeting_date = None
        if raw:
            try:
                meeting_date = date_type.fromisoformat(raw)
            except ValueError:
                meeting_date = None

        payload = SimpleNamespace(
            title=args["titre"],
            meeting_type=args.get("type_reunion", "administrative"),
            meeting_date=meeting_date,
            location=args.get("lieu"),
            start_time=None,
            end_time=None,
        )
        meeting = await create_meeting(db, user, organisation_id, payload)
        return {"id": meeting.id, "titre": meeting.title, "type": meeting.meeting_type, "date": meeting.meeting_date.isoformat() if meeting.meeting_date else None}

    if name == "generer_ordre_du_jour":
        payload = SimpleNamespace(
            instructions=args.get("instructions", ""),
            tone="formel",
        )
        agenda_text = await generate_agenda(db, user, organisation_id, args["reunion_id"], payload)
        return {"reunion_id": args["reunion_id"], "ordre_du_jour": agenda_text}

    if name == "generer_pv_reunion":
        payload = SimpleNamespace(
            instructions=args.get("instructions", ""),
            tone="formel",
        )
        pv_text = await generate_minutes_draft(db, user, organisation_id, args["reunion_id"], payload)
        return {"reunion_id": args["reunion_id"], "pv_brouillon": pv_text}

    if name == "lister_documents":
        docs = await list_documents(
            db,
            organisation_id,
            statut=args.get("statut"),
            type_document=None,
            q=None,
        )
        return [
            {
                "id": d.id,
                "titre": d.title,
                "type": d.document_type,
                "statut": d.status,
                "cree_le": d.created_at.isoformat() if d.created_at else None,
            }
            for d in docs
        ]

    if name == "generer_synthese_document":
        doc = await generate_synthesis(db, user, organisation_id, args["document_id"])
        return {
            "document_id": doc.id,
            "synthese": doc.synthesis_json or {},
            "statut": doc.status,
        }

    if name == "lister_approbations_en_attente":
        return await get_pending_approvals(db, user, organisation_id)

    raise ValueError(f"Outil inconnu : {name}")


# ── Boucle principale de l'agent ──────────────────────────────────────────────

async def run_manager_agent(
    message: str,
    db: AsyncSession,
    user: User,
    organisation_id: int,
    conversation_history: list[dict] | None = None,
) -> dict:
    """
    Point d'entrée du Manager Agent.

    Paramètres :
        message              — message de l'utilisateur
        db                   — session base de données (contexte tenant)
        user                 — utilisateur courant
        organisation_id      — ID du tenant
        conversation_history — messages précédents [{"role": ..., "content": ...}]

    Retourne :
        {
          "response": str,           # réponse finale de l'agent
          "actions_taken": list[str] # résumé des outils appelés
          "tool_results": list[dict] # résultats bruts des outils (debug)
        }
    """
    try:
        ai_service = await get_ai_service_for_org(db, organisation_id)
    except AIUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": message})

    actions_taken: list[str] = []
    tool_results: list[dict] = []

    for _iteration in range(6):  # max 5 tours d'outil + 1 réponse finale
        try:
            completion = await ai_service.chat_completion(
                messages,
                tools=TOOLS,
                temperature=0.2,
                max_tokens=2048,
            )
        except AIUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Le service IA est temporairement indisponible. Veuillez réessayer.",
            ) from exc

        finish_reason = completion.finish_reason
        assistant_msg: dict = {"role": "assistant", "content": completion.content}
        if completion.tool_calls:
            assistant_msg["tool_calls"] = completion.tool_calls

        messages.append(assistant_msg)

        # Fin normale — retourner la réponse
        if finish_reason == "stop" or not completion.tool_calls:
            return {
                "response": completion.content or "",
                "actions_taken": actions_taken,
                "tool_results": tool_results,
            }

        # Appels d'outils à exécuter
        for tc in completion.tool_calls:
            tool_name = tc["function"]["name"]
            try:
                raw_args = tc["function"].get("arguments", "{}")
                tool_args = json.loads(raw_args) if raw_args else {}
            except json.JSONDecodeError:
                tool_args = {}

            logger.info("[Manager Agent] outil=%s args=%s", tool_name, tool_args)
            actions_taken.append(tool_name)

            try:
                result = await _execute_tool(tool_name, tool_args, db, user, organisation_id)
            except HTTPException as exc:
                result = {"erreur": exc.detail}
            except Exception as exc:
                logger.exception("Erreur outil %s", tool_name)
                result = {"erreur": str(exc)}

            tool_results.append({"outil": tool_name, "resultat": result})

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps(result, ensure_ascii=False, default=str),
            })

    return {
        "response": "Désolé, je n'ai pas pu compléter cette demande dans le temps imparti.",
        "actions_taken": actions_taken,
        "tool_results": tool_results,
    }
