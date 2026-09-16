"""Assistant du module Tableau.

Le module s'appuie sur le service IA partagé (`app.core.ai`), jamais sur l'agent
du Secrétariat : il doit répondre même dans une organisation où le Secrétariat
n'est pas activé.

Tous les outils sont en lecture. Importer, corriger un dossier, enregistrer une
décision ou générer un PV restent des actes humains, gardés par leur propre
droit : un assistant qui les déclencherait contournerait ces gardes, et une
délibération ne se délègue pas à une machine.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai.base import AIUnavailableError
from app.core.ai.service import get_ai_service_for_org
from app.models.user import User

from .models import TableauDossier
from .repository import dernier_exercice, get_analyse_for_import, get_stats, list_anomalies
from .service import get_base_tableau, get_reglages

logger = logging.getLogger(__name__)

MAX_TOURS = 6
MAX_HISTORIQUE = 10


SYSTEM_PROMPT = """Tu es l'assistant du module Tableau de l'Ordre des experts-comptables.

Le Tableau est la liste officielle des membres pour un exercice. Chaque membre y
a une situation (cotisation, heures de formation, assurance, chiffre d'affaires)
d'où découle une conclusion : INSCRIT, NON INSCRIT, À DÉLIBÉRER ou NON APPLICABLE.

Ce que tu dois savoir pour répondre juste :
- La base consolidée retient, pour chaque membre, sa situation la plus récente au
  sens de la date de situation — jamais le dernier fichier téléversé.
- Une analyse porte sur un périmètre : « import » (un fichier) ou « base » (la
  situation qui fait foi pour tout l'exercice). Une analyse marquée « stale » est
  obsolète : ses chiffres datent d'avant le dernier changement, dis-le clairement
  et invite à la relancer.
- Une décision de commission prime sur le verdict calculé.

Règles de conduite :
- Appuie chaque affirmation chiffrée sur un outil ; n'invente aucun nombre, aucun
  nom, aucun numéro d'ordre.
- Si les données manquent ou si aucune analyse n'est à jour, dis-le au lieu de
  supposer.
- Tu ne peux rien modifier. Si on te demande de corriger, d'importer, de décider
  ou de générer un document, explique où le faire dans le module.
- Réponds en français, brièvement, en citant l'exercice concerné."""


TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "etat_du_tableau",
            "description": "Chiffres d'ensemble du module pour l'exercice le plus récent : membres, analysés, incomplets, anomalies, décisions, état de l'analyse de base.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consulter_base",
            "description": "Situation consolidée de l'exercice : totaux et premiers membres, avec filtres facultatifs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "exercice": {"type": "string", "description": "Exercice visé ; par défaut le plus récent."},
                    "recherche": {"type": "string", "description": "N° d'ordre, nom, e-mail, NIF ou cabinet."},
                    "categorie": {"type": "string", "description": "Catégorie exacte, ex. « EC Cabinet »."},
                    "anomalie_only": {"type": "boolean", "description": "Ne garder que les membres en anomalie."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "situation_membre",
            "description": "Situation détaillée d'un membre et sa conclusion, recherché par n° d'ordre ou par nom.",
            "parameters": {
                "type": "object",
                "properties": {
                    "recherche": {"type": "string", "description": "N° d'ordre ou nom du membre."},
                    "exercice": {"type": "string"},
                },
                "required": ["recherche"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lister_anomalies",
            "description": "Anomalies de la dernière analyse d'un périmètre, éventuellement filtrées par gravité (high, medium, low).",
            "parameters": {
                "type": "object",
                "properties": {
                    "import_id": {"type": "integer"},
                    "scope": {"type": "string", "enum": ["import", "base"]},
                    "gravite": {"type": "string", "enum": ["high", "medium", "low"]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "regles_de_deliberation",
            "description": "Règles en vigueur pour l'exercice : heures minimales, seuil d'âge et son effet, ancienneté « nouveau membre », exemptions.",
            "parameters": {
                "type": "object",
                "properties": {"import_id": {"type": "integer"}},
            },
        },
    },
]


def _dossier_resume(dossier: TableauDossier) -> dict[str, Any]:
    return {
        "numero_ordre": dossier.numero_ordre,
        "nom": dossier.nom,
        "prenom": dossier.prenom,
        "categorie": dossier.categorie,
        "exercice": dossier.exercice,
        "cotisation_payee": dossier.cotisation_payee,
        "heures_forco": float(dossier.heures_forco) if dossier.heures_forco is not None else None,
        "assurance": dossier.assurance,
        "chiffre_affaires": dossier.chiffre_affaires,
        "anciennete_annees": dossier.anciennete_annees,
        "conclusion": dossier.conclusion,
        "conclusion_motif": dossier.conclusion_motif,
        "anomalie_detectee": dossier.anomalie_detectee,
    }


async def _dernier_import_id(db: AsyncSession, organisation_id: int, exercice: str | None) -> int | None:
    from .models import TableauImport

    q = select(TableauImport.id).where(TableauImport.organisation_id == organisation_id)
    if exercice:
        q = q.where(TableauImport.exercice == exercice)
    q = q.order_by(TableauImport.date_situation.desc(), TableauImport.created_at.desc()).limit(1)
    return (await db.execute(q)).scalar_one_or_none()


async def _executer_outil(
    nom: str,
    arguments: dict[str, Any],
    db: AsyncSession,
    organisation_id: int,
) -> dict[str, Any]:
    if nom == "etat_du_tableau":
        return await get_stats(db, organisation_id)

    if nom == "consulter_base":
        base = await get_base_tableau(
            db,
            [organisation_id],
            exercice=arguments.get("exercice"),
            anomalie_only=bool(arguments.get("anomalie_only")),
            recherche=arguments.get("recherche"),
            categorie=arguments.get("categorie"),
            limit=15,
        )
        return {
            "exercice": base["exercice"],
            "total_membres": base["total_membres"],
            "membres_sans_numero": base["membres_sans_numero"],
            "imports_couverts": base["imports_couverts"],
            "extrait": [_dossier_resume(d) for d in base["dossiers"]],
        }

    if nom == "situation_membre":
        base = await get_base_tableau(
            db,
            [organisation_id],
            exercice=arguments.get("exercice"),
            recherche=arguments.get("recherche"),
            limit=5,
        )
        dossiers = base["dossiers"]
        if not dossiers:
            return {"trouve": False, "message": "Aucun membre ne correspond à cette recherche."}
        return {"trouve": True, "exercice": base["exercice"], "membres": [_dossier_resume(d) for d in dossiers]}

    if nom == "lister_anomalies":
        scope = arguments.get("scope") or "base"
        import_id = arguments.get("import_id") or await _dernier_import_id(db, organisation_id, None)
        if import_id is None:
            return {"anomalies": [], "message": "Aucun import : il n'y a rien à analyser."}
        analyse = await get_analyse_for_import(db, organisation_id, int(import_id), scope=scope)
        if analyse is None:
            return {"anomalies": [], "message": f"Aucune analyse « {scope} » n'a encore été lancée."}
        anomalies = await list_anomalies(
            db,
            organisation_id,
            gravite=arguments.get("gravite"),
            analyse_id=analyse.id,
        )
        return {
            "scope": scope,
            "analyse_status": analyse.status,
            "total": len(anomalies),
            "anomalies": [
                {
                    "dossier_id": a.dossier_id,
                    "type": a.type_anomalie,
                    "gravite": a.gravite,
                    "description": a.description,
                }
                for a in anomalies[:25]
            ],
        }

    if nom == "regles_de_deliberation":
        import_id = arguments.get("import_id") or await _dernier_import_id(db, organisation_id, None)
        if import_id is None:
            return {"message": "Aucun import : les règles s'appliquent à un exercice."}
        return {"import_id": import_id, "reglages": await get_reglages(db, organisation_id, int(import_id))}

    return {"erreur": f"Outil inconnu : {nom}"}


def _historique_propre(historique: list[dict] | None) -> list[dict]:
    """Ne garde que des tours complets rôle/contenu, et pas plus que nécessaire."""
    if not historique:
        return []
    propre = [
        {"role": message["role"], "content": str(message.get("content") or "")}
        for message in historique
        if isinstance(message, dict) and message.get("role") in {"user", "assistant"}
    ]
    return propre[-MAX_HISTORIQUE:]


async def run_tableau_assistant(
    message: str,
    db: AsyncSession,
    user: User,
    organisation_id: int,
    conversation_history: list[dict] | None = None,
) -> dict[str, Any]:
    """Répond à une question sur le Tableau, en s'appuyant sur ses propres données."""
    try:
        ai_service = await get_ai_service_for_org(db, organisation_id)
    except AIUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    exercice = await dernier_exercice(db, [organisation_id])
    contexte = f"Exercice le plus récent connu : {exercice}." if exercice else "Aucun import n'a encore été chargé."

    messages: list[dict] = [{"role": "system", "content": f"{SYSTEM_PROMPT}\n\n{contexte}"}]
    messages.extend(_historique_propre(conversation_history))
    messages.append({"role": "user", "content": message})

    actions: list[str] = []
    resultats: list[dict] = []

    for _tour in range(MAX_TOURS):
        try:
            completion = await ai_service.chat_completion(messages, tools=TOOLS, temperature=0.2, max_tokens=1500)
        except AIUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Le service IA est temporairement indisponible. Réessayez dans un instant.",
            ) from exc

        reponse: dict = {"role": "assistant", "content": completion.content}
        if completion.tool_calls:
            reponse["tool_calls"] = completion.tool_calls
        messages.append(reponse)

        if completion.finish_reason == "stop" or not completion.tool_calls:
            return {
                "response": completion.content or "",
                "actions_taken": actions,
                "tool_results": resultats,
            }

        for appel in completion.tool_calls:
            nom = appel["function"]["name"]
            try:
                bruts = appel["function"].get("arguments", "{}")
                arguments = json.loads(bruts) if bruts else {}
            except json.JSONDecodeError:
                arguments = {}

            actions.append(nom)
            try:
                resultat = await _executer_outil(nom, arguments, db, organisation_id)
            except HTTPException as exc:
                resultat = {"erreur": exc.detail}
            except Exception as exc:  # noqa: BLE001 — l'assistant doit survivre à un outil en panne
                logger.exception("Assistant Tableau : outil %s en échec", nom)
                resultat = {"erreur": str(exc)}

            resultats.append({"outil": nom, "resultat": resultat})
            messages.append({
                "role": "tool",
                "tool_call_id": appel["id"],
                "content": json.dumps(resultat, ensure_ascii=False, default=str),
            })

    return {
        "response": "Je n'ai pas pu aboutir dans le nombre d'étapes imparti. Reformulez en une question plus précise.",
        "actions_taken": actions,
        "tool_results": resultats,
    }
