from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.encaissement import Encaissement
from app.models.budget import BudgetExercice, BudgetLigne
from app.models.ligne_requisition import LigneRequisition
from app.models.requisition import Requisition
from app.models.sortie_fonds import SortieFonds
from app.services.anomaly_scoring import compute_requisition_score
from app.services.forecasting import compute_cash_forecast


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_float(value) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


async def _fetch_history_amounts(
    db: AsyncSession,
    rubrique: str,
    created_by,
    since: datetime,
) -> list[float]:
    stmt = (
        select(LigneRequisition.montant_total)
        .select_from(LigneRequisition)
        .join(Requisition, Requisition.id == LigneRequisition.requisition_id)
        .where(
            and_(
                Requisition.created_at >= since,
                LigneRequisition.rubrique == rubrique,
            )
        )
    )
    if created_by:
        stmt = stmt.where(Requisition.created_by == created_by)
    res = await db.execute(stmt)
    return [_to_float(row[0]) for row in res.all()]


async def _count_duplicate_candidates(
    db: AsyncSession,
    requisition_id,
    amount: float,
    tolerance_pct: float = 0.03,
) -> int:
    if amount <= 0:
        return 0
    tolerance = amount * tolerance_pct
    stmt = (
        select(LigneRequisition.id)
        .select_from(LigneRequisition)
        .join(Requisition, Requisition.id == LigneRequisition.requisition_id)
        .where(
            and_(
                Requisition.id != requisition_id,
                LigneRequisition.montant_total.between(amount - tolerance, amount + tolerance),
            )
        )
    )
    res = await db.execute(stmt)
    return len(res.all())


async def build_finance_snapshot(db: AsyncSession) -> dict[str, Any]:
    now = _utcnow()
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

    enc_month_stmt = select(func.coalesce(func.sum(func.coalesce(Encaissement.montant_percu, 0)), 0)).where(
        Encaissement.date_encaissement >= month_start
    )
    enc_month = _to_float((await db.execute(enc_month_stmt)).scalar_one() or 0)

    sorties_month_stmt = select(func.coalesce(func.sum(func.coalesce(SortieFonds.montant_paye, 0)), 0)).where(
        and_(
            (SortieFonds.statut.is_(None)) | (func.upper(SortieFonds.statut) == "VALIDE"),
            func.coalesce(SortieFonds.date_paiement, SortieFonds.created_at) >= month_start,
        )
    )
    sorties_month = _to_float((await db.execute(sorties_month_stmt)).scalar_one() or 0)

    forecast = await compute_cash_forecast(db=db, lookback_days=30, horizon_days=30, reserve_threshold=1000.0)

    req_recent_stmt = (
        select(Requisition)
        .order_by(Requisition.created_at.desc())
        .limit(10)
    )
    req_recent = (await db.execute(req_recent_stmt)).scalars().all()

    top_sorties_stmt = (
        select(SortieFonds)
        .where(
            (SortieFonds.statut.is_(None)) | (func.upper(SortieFonds.statut) == "VALIDE")
        )
        .order_by(SortieFonds.montant_paye.desc())
        .limit(10)
    )
    top_sorties = (await db.execute(top_sorties_stmt)).scalars().all()

    # Budget lines (top depenses)
    budget_lines: list[dict[str, Any]] = []
    pending_by_line: dict[int, float] = {}
    try:
        exercice_res = await db.execute(select(func.max(BudgetExercice.annee)))
        annee = exercice_res.scalar_one_or_none()
        if annee is not None:
            pending_stmt = (
                select(
                    LigneRequisition.budget_ligne_id,
                    func.coalesce(func.sum(func.coalesce(LigneRequisition.montant_total, 0)), 0),
                )
                .join(Requisition, Requisition.id == LigneRequisition.requisition_id)
                .where(
                    LigneRequisition.budget_ligne_id.is_not(None),
                    func.upper(Requisition.status).in_(
                        ["EN_ATTENTE", "AUTORISEE", "VALIDEE", "PENDING_VALIDATION_IMPORT"]
                    ),
                )
                .group_by(LigneRequisition.budget_ligne_id)
            )
            for row in (await db.execute(pending_stmt)).all():
                pending_by_line[int(row[0])] = _to_float(row[1])

            budget_lines_res = await db.execute(
                select(BudgetLigne)
                .join(BudgetExercice, BudgetExercice.id == BudgetLigne.exercice_id)
                .where(BudgetExercice.annee == annee, BudgetLigne.type == "DEPENSE")
                .order_by(BudgetLigne.montant_paye.desc())
                .limit(10)
            )
            for line in budget_lines_res.scalars().all():
                prevu = _to_float(line.montant_prevu)
                paye = _to_float(line.montant_paye)
                pending = pending_by_line.get(int(line.id), 0.0)
                consomme_pct = (paye / prevu * 100) if prevu > 0 else 0
                engage = paye + pending
                engage_pct = (engage / prevu * 100) if prevu > 0 else 0
                budget_lines.append(
                    {
                        "code": line.code,
                        "libelle": line.libelle,
                        "montant_prevu": prevu,
                        "montant_paye": paye,
                        "montant_en_attente": pending,
                        "pourcentage_consomme": round(consomme_pct, 1),
                        "pourcentage_engage": round(engage_pct, 1),
                    }
                )
    except Exception:
        budget_lines = []

    # Top beneficiaires (last 30 days)
    top_beneficiaires: list[dict[str, Any]] = []
    try:
        since_30 = now - timedelta(days=30)
        benef_stmt = (
            select(
                SortieFonds.beneficiaire,
                func.coalesce(func.sum(func.coalesce(SortieFonds.montant_paye, 0)), 0).label("total"),
            )
            .where(
                and_(
                    (SortieFonds.statut.is_(None)) | (func.upper(SortieFonds.statut) == "VALIDE"),
                    func.coalesce(SortieFonds.date_paiement, SortieFonds.created_at) >= since_30,
                )
            )
            .group_by(SortieFonds.beneficiaire)
            .order_by(func.coalesce(func.sum(func.coalesce(SortieFonds.montant_paye, 0)), 0).desc())
            .limit(5)
        )
        for row in (await db.execute(benef_stmt)).all():
            top_beneficiaires.append({"beneficiaire": row[0], "montant": _to_float(row[1])})
    except Exception:
        top_beneficiaires = []

    # Upcoming large payments: approved requisitions without sortie
    upcoming: list[dict[str, Any]] = []
    try:
        approved_stmt = (
            select(Requisition)
            .where(func.upper(Requisition.status).in_(["APPROUVEE", "AUTORISEE", "VALIDEE"]))
            .order_by(Requisition.montant_total.desc())
            .limit(10)
        )
        approved = (await db.execute(approved_stmt)).scalars().all()
        for req in approved:
            res = await db.execute(
                select(SortieFonds.id).where(SortieFonds.requisition_id == req.id).limit(1)
            )
            if res.scalar_one_or_none() is None:
                upcoming.append(
                    {
                        "numero": req.numero_requisition,
                        "objet": req.objet,
                        "montant": _to_float(req.montant_total),
                        "date": req.created_at.isoformat(),
                    }
                )
            if len(upcoming) >= 5:
                break
    except Exception:
        upcoming = []

    anomalies: list[dict[str, Any]] = []
    since_90 = now - timedelta(days=90)
    for req in req_recent:
        rubriques_res = await db.execute(
            select(LigneRequisition.rubrique).where(LigneRequisition.requisition_id == req.id)
        )
        rubriques = [row[0] for row in rubriques_res.all() if row[0]]
        rubrique = rubriques[0] if rubriques else "GENERAL"
        history_amounts = await _fetch_history_amounts(
            db=db,
            rubrique=rubrique,
            created_by=req.created_by,
            since=since_90,
        )
        duplicate_candidates = await _count_duplicate_candidates(
            db=db,
            requisition_id=req.id,
            amount=_to_float(req.montant_total),
        )
        score = compute_requisition_score(
            amount=_to_float(req.montant_total),
            history_amounts=history_amounts,
            duplicate_candidates=duplicate_candidates,
            min_history=8,
        )
        if score.risk_score >= 75:
            anomalies.append(
                {
                    "numero": req.numero_requisition,
                    "montant": _to_float(req.montant_total),
                    "score": score.risk_score,
                    "raison": score.explanation,
                }
            )
        if len(anomalies) >= 5:
            break

    tensions = []
    for line in budget_lines:
        ratio = line.get("pourcentage_engage", 0)
        if ratio >= 90:
            tensions.append(
                {
                    "libelle": line["libelle"],
                    "ratio": ratio,
                    "montant_prevu": line["montant_prevu"],
                    "montant_paye": line["montant_paye"],
                    "montant_en_attente": line["montant_en_attente"],
                }
            )
    tensions.sort(key=lambda x: x["ratio"], reverse=True)

    return {
        "solde_actuel": forecast.solde_actuel,
        "encaissements_mois": enc_month,
        "sorties_mois": sorties_month,
        "stress_test": {
            "baseline_projection": forecast.baseline_projection,
            "stress_projection": forecast.stress_projection,
            "pending_total": forecast.pending_total,
            "reserve_threshold": forecast.reserve_threshold,
        },
        "budget_lignes": budget_lines,
        "tensions": tensions[:5],
        "requisitions_recentes": [
            {
                "numero": r.numero_requisition,
                "objet": r.objet,
                "montant": _to_float(r.montant_total),
                "status": r.status,
                "created_at": r.created_at.isoformat(),
            }
            for r in req_recent
        ],
        "top_sorties": [
            {
                "motif": s.motif,
                "montant": _to_float(s.montant_paye),
                "date": (s.date_paiement or s.created_at).isoformat(),
            }
            for s in top_sorties
        ],
        "top_beneficiaires": top_beneficiaires,
        "echeances": upcoming,
        "anomalies": anomalies,
    }


def _detect_intent(text: str) -> str:
    lower = text.lower()
    if any(k in lower for k in ["cash", "trésorerie", "solde", "caisse", "argent"]):
        return "CASH"
    if any(k in lower for k in ["stress", "risque", "danger", "alerte", "tension"]):
        return "RISK"
    if any(k in lower for k in ["anomalie", "bizarre", "suspect", "doublon"]):
        return "ANOMALY"
    if any(k in lower for k in ["chauffe", "surchauffe", "où ça chauffe", "ou ca chauffe", "tensions"]):
        return "TENSION"
    if any(k in lower for k in ["fournisseur", "prestataire", "bénéficiaire", "beneficiaire"]):
        return "SUPPLIER"
    if any(k in lower for k in ["échéance", "echeance", "à payer", "a payer", "non payé", "non payee"]):
        return "DUE"
    if "social" in lower:
        return "SOCIAL"
    if any(k in lower for k in ["budget", "restant", "prévu", "paye", "consommé", "consomme"]):
        return "BUDGET"
    if any(k in lower for k in ["résumé", "resume", "semaine", "mois", "où en est-on", "ou en est on"]):
        return "SUMMARY"
    return "UNKNOWN"


def _fmt_amount(value: float) -> str:
    return f"{value:,.2f} $".replace(",", " ").replace(".", ",")


def _match_budget_line(lines: list[dict[str, Any]], text: str) -> dict[str, Any] | None:
    lower = text.lower()
    for line in lines:
        if not line.get("libelle"):
            continue
        if line["libelle"].lower() in lower or any(token in line["libelle"].lower() for token in lower.split()):
            return line
    return None


async def _local_answer(question: str, db: AsyncSession) -> dict[str, Any]:
    snapshot = await build_finance_snapshot(db)
    intent = _detect_intent(question)

    solde = _fmt_amount(snapshot["solde_actuel"])
    pending = _fmt_amount(snapshot["stress_test"]["pending_total"])
    stress_proj = _fmt_amount(snapshot["stress_test"]["stress_projection"])
    reserve = _fmt_amount(snapshot["stress_test"]["reserve_threshold"])

    if intent == "CASH":
        return {
            "answer": (
                f"Le solde actuel est de {solde}. "
                f"Avec {pending} de réquisitions en attente, le stress test projette {stress_proj}."
            ),
            "widget": {"label": "Solde actuel", "value": solde, "tone": "ok"},
        }
    if intent == "RISK":
        tone = "critical" if snapshot["stress_test"]["stress_projection"] <= snapshot["stress_test"]["reserve_threshold"] else "warn"
        return {
            "answer": (
                f"Le stress test projette {stress_proj} face à une réserve critique de {reserve}. "
                "Surveillance recommandée."
            ),
            "widget": {"label": "Stress Test", "value": stress_proj, "tone": tone},
        }
    if intent == "ANOMALY":
        anomalies = snapshot.get("anomalies", [])
        if not anomalies:
            return {"answer": "Aucune anomalie majeure détectée dans les dernières réquisitions."}
        top = anomalies[0]
        return {
            "answer": (
                f"Anomalie détectée : réquisition {top['numero']} ({_fmt_amount(top['montant'])}) "
                f"avec un score {top['score']}. {top['raison']}"
            ),
            "widget": {"label": "Score anomalie", "value": str(top["score"]), "tone": "critical"},
        }
    if intent == "TENSION":
        tensions = snapshot.get("tensions", [])
        if not tensions:
            return {"answer": "Aucune tension budgétaire majeure détectée avec les réquisitions en attente."}
        top = tensions[0]
        tone = "critical" if top["ratio"] >= 100 else "warn"
        return {
            "answer": (
                f"Attention, {top['libelle']} est sous tension : "
                f"{top['ratio']}% engagé (payé + en attente). "
                f"Payé {_fmt_amount(top['montant_paye'])}, en attente {_fmt_amount(top['montant_en_attente'])}."
            ),
            "widget": {"label": "Surchauffe", "value": f"{top['ratio']}%", "tone": tone},
        }
    if intent == "SUPPLIER":
        fournisseurs = snapshot.get("top_beneficiaires", [])
        if not fournisseurs:
            return {"answer": "Aucun fournisseur majeur détecté sur les 30 derniers jours."}
        top = fournisseurs[0]
        return {
            "answer": (
                f"Le fournisseur le plus payé est {top['beneficiaire']} avec {_fmt_amount(top['montant'])} "
                "sur les 30 derniers jours."
            ),
            "widget": {"label": "Top fournisseur", "value": top["beneficiaire"], "tone": "ok"},
        }
    if intent == "DUE":
        echeances = snapshot.get("echeances", [])
        if not echeances:
            return {"answer": "Aucune échéance importante en attente de paiement détectée."}
        top = echeances[0]
        return {
            "answer": (
                f"Échéance prioritaire : {top['numero']} ({_fmt_amount(top['montant'])}) "
                f"pour {top['objet']}."
            ),
            "widget": {"label": "Échéance", "value": _fmt_amount(top["montant"]), "tone": "warn"},
        }
    if intent == "SOCIAL":
        line = _match_budget_line(snapshot.get("budget_lignes", []), "social")
        if line:
            pending = _to_float(line.get("montant_en_attente", 0))
        return {
            "answer": (
                f"Le poste {line['libelle']} a consommé {line['pourcentage_consomme']}% "
                f"({ _fmt_amount(line['montant_paye']) } / { _fmt_amount(line['montant_prevu']) }). "
                f"Avec les réquisitions en attente ({_fmt_amount(pending)}), "
                f"le niveau engagé monte à {line['pourcentage_engage']}%."
            ),
                "widget": {
                    "type": "impact",
                    "label": "Budget Social",
                    "value": f"{line['pourcentage_engage']}%",
                    "tone": "warn" if line["pourcentage_engage"] >= 80 else "ok",
                    "solid": _to_float(line["montant_paye"]),
                    "ghost": _to_float(line.get("montant_en_attente", 0)),
                    "limit": _to_float(line["montant_prevu"]),
                    "details": {
                        "solid": _fmt_amount(_to_float(line["montant_paye"])),
                        "ghost": _fmt_amount(_to_float(line.get("montant_en_attente", 0))),
                        "limit": _fmt_amount(_to_float(line["montant_prevu"])),
                    },
                },
            }
        return {
            "answer": (
                "Je n'ai pas trouvé de ligne budgétaire 'Social'. "
                f"Encaissements du mois {_fmt_amount(snapshot['encaissements_mois'])}, "
                f"sorties {_fmt_amount(snapshot['sorties_mois'])}."
            )
        }
    if intent == "BUDGET":
        lines = snapshot.get("budget_lignes", [])
        line = _match_budget_line(lines, question)
        if line:
            remaining = _to_float(line["montant_prevu"]) - _to_float(line["montant_paye"])
            pending = _to_float(line.get("montant_en_attente", 0))
            engage_pct = line.get("pourcentage_engage", line["pourcentage_consomme"])
            return {
                "answer": (
                    f"{line['libelle']} a consommé {line['pourcentage_consomme']}% "
                    f"({ _fmt_amount(line['montant_paye']) } / { _fmt_amount(line['montant_prevu']) }). "
                    f"En attente: {_fmt_amount(pending)}. "
                    f"Engagé total: {engage_pct}%. Reste estimé: {_fmt_amount(remaining)}."
                ),
                "widget": {
                    "type": "impact",
                    "label": line["libelle"],
                    "value": f"{engage_pct}%",
                    "tone": "warn",
                    "solid": _to_float(line["montant_paye"]),
                    "ghost": _to_float(line.get("montant_en_attente", 0)),
                    "limit": _to_float(line["montant_prevu"]),
                    "details": {
                        "solid": _fmt_amount(_to_float(line["montant_paye"])),
                        "ghost": _fmt_amount(_to_float(line.get("montant_en_attente", 0))),
                        "limit": _fmt_amount(_to_float(line["montant_prevu"])),
                    },
                },
            }
        if lines:
            top = lines[0]
            return {
                "answer": (
                    f"Le poste le plus consommé est {top['libelle']} avec {top['pourcentage_consomme']}% "
                    f"({ _fmt_amount(top['montant_paye']) } / { _fmt_amount(top['montant_prevu']) })."
                ),
                "widget": {"label": "Top budget", "value": top["libelle"], "tone": "ok"},
            }
        return {"answer": "Aucune ligne budgétaire disponible pour le moment."}
    if intent == "SUMMARY":
        return {
            "answer": (
                f"Résumé: solde actuel {solde}, encaissements du mois {_fmt_amount(snapshot['encaissements_mois'])}, "
                f"sorties {_fmt_amount(snapshot['sorties_mois'])}. Stress test à {stress_proj}."
            ),
            "widget": {"label": "Stress Test", "value": stress_proj, "tone": "warn"},
        }

    return {
        "answer": (
            "Bonjour ! Je peux vous donner des chiffres clés immédiats. "
            "Essayez par exemple : « solde », « stress test », « budget social », "
            "« fournisseur », « échéance », ou « où ça chauffe ». "
            "L'analyse avancée est en maintenance."
        )
    }


async def ask_openai(
    *,
    question: str,
    history: list[dict[str, str]],
    db: AsyncSession,
) -> dict[str, Any]:
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return await _local_answer(question, db)

    snapshot = await build_finance_snapshot(db)

    system_prompt = (
        "Tu es l'intelligence financière de l'ONEC. Tu as accès uniquement aux chiffres fournis dans le contexte. "
        "Réponds de manière concise, factuelle et orientée décision. "
        "Si une analyse est demandée, utilise des pourcentages. "
        "Si un risque est détecté, souligne-le clairement. "
        "Réponds STRICTEMENT en JSON avec les clés: answer (string), widget (optional object avec label, value, tone), "
        "suggestions (optional array of strings). JSON uniquement."
    )

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history[-8:]:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role not in {"user", "assistant"}:
            role = "user"
        messages.append({"role": role, "content": content})
    messages.append(
        {
            "role": "user",
            "content": f"Question: {question}\n\nContexte financier:\n{json.dumps(snapshot, ensure_ascii=False)}",
        }
    )

    payload = {
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "messages": messages,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            res.raise_for_status()
            data = res.json()
    except httpx.HTTPStatusError as exc:
        # Fallback to local intelligence on rate limit or API errors
        if exc.response is not None and exc.response.status_code in {401, 402, 429, 500, 503}:
            return await _local_answer(question, db)
        raise
    except httpx.HTTPError:
        return await _local_answer(question, db)

    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    try:
        parsed = json.loads(content) if content else {}
    except json.JSONDecodeError:
        parsed = {"answer": content}

    if "answer" not in parsed:
        parsed["answer"] = content or "Réponse indisponible."
    return parsed
