"""Report des créances impayées d'un exercice clôturé vers ses arriérés.

Une note « Cotisation 2026 » restée impayée au 31 décembre ne tombe pas. À la
clôture de 2026, son reste dû passe sur le poste d'arriérés de 2027 — celui que
désigne `BudgetPoste.code_poste_arrieres` — et les versements qui suivent s'y
imputent. L'exercice 2026, lui, ne bouge plus : ce qu'il a encaissé reste
réalisé chez lui, ce qu'il n'a pas encaissé n'y entrera jamais.

Trois règles tiennent l'ensemble :

  - la clôture reporte tout ou rien. Un poste qui porte des impayés sans poste
    d'arriérés dans l'exercice suivant bloque la clôture : laisser passer
    reviendrait à laisser la dette sur un exercice figé ;
  - un exercice clôturé ne reçoit plus d'imputation, ni ne s'en voit retirer
    une (`verifier_postes_ouverts`) ;
  - rouvrir un exercice annule ses reports, sauf si un versement a déjà été
    imputé sur un poste d'arriérés : il faudrait alors le défaire d'abord.

Les montants reportés servent de poids : un versement sur une note reportée se
répartit entre les postes d'arriérés dans leur proportion, comme un versement
ordinaire entre les articles (`encaissement_repartition.repartir`).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.encaissement import Encaissement, EncaissementArticle
from app.models.mouvement_budget_imputation import MouvementBudgetImputation
from app.models.payment_history import PaymentHistory
from app.models.report_creance import REPORT_ACTIVE, REPORT_ANNULE, REPORT_REMPLACE, ReportCreance
from app.services.encaissement_repartition import repartir

#: En deçà, le reste dû est un arrondi, pas une créance.
SEUIL_RESTE = Decimal("0.01")


def _money(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# Verrou : un exercice clôturé ne bouge plus
# ---------------------------------------------------------------------------


async def verifier_postes_ouverts(
    db: AsyncSession,
    *,
    organisation_id: int,
    poste_ids: set[int] | list[int],
    message: str,
) -> None:
    """Refuse l'opération si l'un des postes appartient à un exercice clôturé.

    `message` reçoit `{annee}` et `{poste}` : chaque chemin dit ce qui est
    refusé et quoi faire, un paiement et une annulation n'appelant pas la même
    réponse.
    """
    ids = {int(pid) for pid in poste_ids if pid is not None}
    if not ids:
        return
    row = (
        await db.execute(
            select(BudgetExercice.annee, BudgetPoste.code)
            .join(BudgetExercice, BudgetExercice.id == BudgetPoste.exercice_id)
            .where(
                BudgetPoste.organisation_id == organisation_id,
                BudgetPoste.id.in_(ids),
                BudgetExercice.statut == StatutBudget.CLOTURE,
            )
            .order_by(BudgetExercice.annee)
            .limit(1)
        )
    ).first()
    if row is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message.format(annee=row.annee, poste=row.code),
        )


# ---------------------------------------------------------------------------
# Où s'impute le prochain versement d'une note
# ---------------------------------------------------------------------------


async def reports_actifs(
    db: AsyncSession, *, organisation_id: int, encaissement_id: uuid.UUID
) -> list[ReportCreance]:
    return list(
        (
            await db.execute(
                select(ReportCreance).where(
                    ReportCreance.organisation_id == organisation_id,
                    ReportCreance.encaissement_id == encaissement_id,
                    ReportCreance.statut == REPORT_ACTIVE,
                )
            )
        ).scalars().all()
    )


async def lignes_de_recouvrement(
    db: AsyncSession, *, organisation_id: int, encaissement: Encaissement
) -> tuple[list[tuple[int | None, Decimal]], int | None]:
    """Les postes sur lesquels le prochain versement se répartit, et leurs poids.

    Une note reportée se recouvre sur ses postes d'arriérés, au prorata des
    montants reportés. Sinon, sur ses articles, avec le poste de l'en-tête pour
    les lignes muettes — la règle d'avant les reports.
    """
    reports = await reports_actifs(db, organisation_id=organisation_id, encaissement_id=encaissement.id)
    if reports:
        return [(r.poste_cible_id, _money(r.montant)) for r in reports], None
    articles = (
        await db.execute(
            select(EncaissementArticle.budget_poste_id, EncaissementArticle.montant).where(
                EncaissementArticle.encaissement_id == encaissement.id,
                EncaissementArticle.organisation_id == organisation_id,
            )
        )
    ).all()
    return (
        [(ligne.budget_poste_id, Decimal(str(ligne.montant or 0))) for ligne in articles],
        encaissement.budget_poste_id,
    )


# ---------------------------------------------------------------------------
# Clôture : reporter
# ---------------------------------------------------------------------------


async def _exercice_suivant(db: AsyncSession, *, organisation_id: int, annee: int) -> BudgetExercice | None:
    return (
        await db.execute(
            select(BudgetExercice).where(
                BudgetExercice.organisation_id == organisation_id,
                BudgetExercice.annee == annee + 1,
            )
        )
    ).scalar_one_or_none()


async def _creances_a_reporter(
    db: AsyncSession, *, organisation_id: int, poste_ids: set[int]
) -> list[Encaissement]:
    """Les notes avec un reste dû qui se recouvrent encore sur ces postes.

    Verrouillées : un versement concurrent changerait le reste pendant qu'on le
    reporte. Même ordre que le paiement — l'encaissement d'abord.
    """
    article_sur_poste = exists().where(
        EncaissementArticle.encaissement_id == Encaissement.id,
        EncaissementArticle.budget_poste_id.in_(poste_ids),
    )
    report_vers_poste = exists().where(
        ReportCreance.encaissement_id == Encaissement.id,
        ReportCreance.statut == REPORT_ACTIVE,
        ReportCreance.poste_cible_id.in_(poste_ids),
    )
    return list(
        (
            await db.execute(
                select(Encaissement)
                .where(
                    Encaissement.organisation_id == organisation_id,
                    Encaissement.est_proforma.is_(False),
                    Encaissement.is_deleted.is_(False),
                    Encaissement.statut_operation == "ACTIVE",
                    Encaissement.impact_budgetaire.is_(True),
                    Encaissement.montant_total - Encaissement.montant_paye >= SEUIL_RESTE,
                    or_(Encaissement.budget_poste_id.in_(poste_ids), article_sur_poste, report_vers_poste),
                )
                .order_by(Encaissement.id)
                .with_for_update()
            )
        ).scalars().all()
    )


async def reporter_creances_exercice(
    db: AsyncSession,
    *,
    organisation_id: int,
    exercice: BudgetExercice,
    user_id: uuid.UUID | None,
) -> dict[str, Any]:
    """Reporte le reste dû des notes de `exercice` vers les arriérés de N+1.

    Idempotent : une part déjà reportée ne l'est pas deux fois. Refuse tout,
    sans rien écrire, si un poste concerné n'a pas de poste d'arriérés.
    """
    postes_source = {
        poste.id: poste
        for poste in (
            await db.execute(
                select(BudgetPoste).where(
                    BudgetPoste.organisation_id == organisation_id,
                    BudgetPoste.exercice_id == exercice.id,
                )
            )
        ).scalars().all()
    }
    creances = await _creances_a_reporter(db, organisation_id=organisation_id, poste_ids=set(postes_source))

    # Parts à reporter : (encaissement, poste d'origine, montant), plus les
    # reports vivants que ce report remplace.
    parts: list[tuple[Encaissement, int, Decimal]] = []
    remplaces: list[ReportCreance] = []
    for enc in creances:
        reste = _money(enc.montant_total) - _money(enc.montant_paye)
        lignes, defaut = await lignes_de_recouvrement(db, organisation_id=organisation_id, encaissement=enc)
        deja = {
            row[0]
            for row in (
                await db.execute(
                    select(ReportCreance.poste_source_id).where(
                        ReportCreance.encaissement_id == enc.id,
                        ReportCreance.exercice_source_id == exercice.id,
                        ReportCreance.statut != REPORT_ANNULE,
                    )
                )
            ).all()
        }
        for poste_id, montant in repartir(lignes, reste, poste_par_defaut=defaut):
            if poste_id in postes_source and poste_id not in deja:
                parts.append((enc, poste_id, montant))
        remplaces.extend(
            r
            for r in await reports_actifs(db, organisation_id=organisation_id, encaissement_id=enc.id)
            if r.poste_cible_id in postes_source
        )

    if not parts:
        return {"notes_reportees": 0, "montant_reporte": "0.00", "postes": []}

    cible_exercice = await _exercice_suivant(db, organisation_id=organisation_id, annee=exercice.annee)
    if cible_exercice is None or cible_exercice.statut == StatutBudget.CLOTURE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "EXERCICE_SUIVANT_ABSENT",
                "message": (
                    f"Des notes de {exercice.annee} restent impayées et doivent passer en arriérés "
                    f"sur {exercice.annee + 1}, qui "
                    + ("est déjà clôturé." if cible_exercice is not None else "n'existe pas encore : préparez-le d'abord.")
                ),
                "postes": [],
            },
        )

    postes_cible_par_code = {
        poste.code: poste
        for poste in (
            await db.execute(
                select(BudgetPoste).where(
                    BudgetPoste.organisation_id == organisation_id,
                    BudgetPoste.exercice_id == cible_exercice.id,
                    BudgetPoste.is_deleted.is_(False),
                )
            )
        ).scalars().all()
    }

    correspondance: dict[int, BudgetPoste] = {}
    manques: dict[int, dict[str, Any]] = {}
    reste_par_poste: dict[int, Decimal] = defaultdict(Decimal)
    for _enc, poste_id, montant in parts:
        reste_par_poste[poste_id] += montant
    for poste_id, montant in reste_par_poste.items():
        source = postes_source[poste_id]
        code = (source.code_poste_arrieres or "").strip()
        cible = postes_cible_par_code.get(code) if code else None
        if cible is None or (cible.type or "").upper() != "RECETTE":
            manques[poste_id] = {
                "poste_id": source.id,
                "code": source.code,
                "libelle": source.libelle,
                "code_poste_arrieres": code or None,
                "reste_du": str(montant),
                "raison": (
                    "aucun poste d'arriérés désigné"
                    if not code
                    else f"le poste {code} n'existe pas en recette sur {cible_exercice.annee}"
                ),
            }
        else:
            correspondance[poste_id] = cible
    if manques:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "POSTE_ARRIERES_MANQUANT",
                "message": (
                    f"Des notes de {exercice.annee} restent impayées sur des postes sans poste d'arriérés "
                    f"en {cible_exercice.annee}. Désignez-le pour chacun avant de clôturer."
                ),
                "postes": sorted(manques.values(), key=lambda m: m["code"]),
            },
        )

    for report in remplaces:
        report.statut = REPORT_REMPLACE
    await db.flush()

    notes: set[uuid.UUID] = set()
    total = Decimal("0")
    par_cible: dict[int, Decimal] = defaultdict(Decimal)
    for enc, poste_id, montant in parts:
        cible = correspondance[poste_id]
        db.add(
            ReportCreance(
                organisation_id=organisation_id,
                encaissement_id=enc.id,
                exercice_source_id=exercice.id,
                exercice_cible_id=cible_exercice.id,
                poste_source_id=poste_id,
                poste_cible_id=cible.id,
                montant=montant,
                statut=REPORT_ACTIVE,
                created_by=user_id,
            )
        )
        notes.add(enc.id)
        total += montant
        par_cible[cible.id] += montant
    await db.flush()

    postes_cible = {p.id: p for p in correspondance.values()}
    return {
        "notes_reportees": len(notes),
        "montant_reporte": str(total),
        "exercice_cible": cible_exercice.annee,
        "postes": [
            {"poste_id": pid, "code": postes_cible[pid].code, "libelle": postes_cible[pid].libelle, "montant": str(m)}
            for pid, m in sorted(par_cible.items(), key=lambda item: postes_cible[item[0]].code)
        ],
    }


# ---------------------------------------------------------------------------
# Réouverture : défaire le report
# ---------------------------------------------------------------------------


async def annuler_reports_exercice(
    db: AsyncSession,
    *,
    organisation_id: int,
    exercice: BudgetExercice,
    user_id: uuid.UUID | None,
) -> int:
    """Annule les reports de `exercice`, pour qu'il se rouvre sur ses créances.

    Refuse si l'exercice suivant les a déjà reportés à son tour, ou si un
    versement s'est déjà imputé sur un poste d'arriérés : la dette serait alors
    rendue à 2026 alors qu'une partie en a été encaissée sur 2027.
    """
    reports = list(
        (
            await db.execute(
                select(ReportCreance)
                .where(
                    ReportCreance.organisation_id == organisation_id,
                    ReportCreance.exercice_source_id == exercice.id,
                    ReportCreance.statut != REPORT_ANNULE,
                )
                .with_for_update()
            )
        ).scalars().all()
    )
    if not reports:
        return 0
    if any(r.statut == REPORT_REMPLACE for r in reports):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"L'exercice {exercice.annee + 1} a déjà reporté ces créances à son tour : "
                f"rouvrez-le avant {exercice.annee}."
            ),
        )

    for report in reports:
        versement = (
            await db.execute(
                select(Encaissement.numero_recu)
                .join(PaymentHistory, PaymentHistory.encaissement_id == Encaissement.id)
                .join(MouvementBudgetImputation, MouvementBudgetImputation.payment_history_id == PaymentHistory.id)
                .where(
                    PaymentHistory.encaissement_id == report.encaissement_id,
                    MouvementBudgetImputation.budget_poste_id == report.poste_cible_id,
                    MouvementBudgetImputation.statut == "ACTIVE",
                    MouvementBudgetImputation.created_at >= report.created_at,
                )
                .limit(1)
            )
        ).first()
        if versement is not None:
            note = f"La note {versement.numero_recu}" if versement.numero_recu else "Une note"
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"{note} a déjà reçu un versement sur ses arriérés : l'exercice {exercice.annee} "
                    "ne peut plus être rouvert tant que ce versement n'est pas annulé."
                ),
            )

    now = datetime.now(timezone.utc)
    for report in reports:
        report.statut = REPORT_ANNULE
        report.annule_le = now
        report.annule_par_id = user_id
        # Le report que celui-ci avait remplacé — arriérés 2025 repris en 2026 —
        # redevient celui qui dit où la note se recouvre.
        precedent = (
            await db.execute(
                select(ReportCreance).where(
                    ReportCreance.encaissement_id == report.encaissement_id,
                    ReportCreance.exercice_cible_id == exercice.id,
                    ReportCreance.poste_cible_id == report.poste_source_id,
                    ReportCreance.statut == REPORT_REMPLACE,
                )
            )
        ).scalars().all()
        for ancien in precedent:
            ancien.statut = REPORT_ACTIVE
    await db.flush()
    return len(reports)


async def annuler_reports_encaissement(
    db: AsyncSession,
    *,
    organisation_id: int,
    encaissement_id: uuid.UUID,
    user_id: uuid.UUID | None,
) -> None:
    """Une note annulée ne doit plus rien : ses reports vivants s'éteignent."""
    now = datetime.now(timezone.utc)
    for report in await reports_actifs(db, organisation_id=organisation_id, encaissement_id=encaissement_id):
        report.statut = REPORT_ANNULE
        report.annule_le = now
        report.annule_par_id = user_id
    await db.flush()


async def arrieres_des_notes(
    db: AsyncSession, *, organisation_id: int, encaissement_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[dict[str, Any]]]:
    """Pour chaque note reportée, les postes d'arriérés sur lesquels elle se recouvre.

    Une requête pour toute la page : la liste des notes impayées l'affiche en
    regard de chaque note (« reportée en Arriérés de cotisation 2027 »).
    """
    if not encaissement_ids:
        return {}
    rows = (
        await db.execute(
            select(
                ReportCreance.encaissement_id,
                BudgetPoste.code,
                BudgetPoste.libelle,
                BudgetExercice.annee,
                ReportCreance.montant,
            )
            .join(BudgetPoste, BudgetPoste.id == ReportCreance.poste_cible_id)
            .join(BudgetExercice, BudgetExercice.id == ReportCreance.exercice_cible_id)
            .where(
                ReportCreance.organisation_id == organisation_id,
                ReportCreance.encaissement_id.in_(encaissement_ids),
                ReportCreance.statut == REPORT_ACTIVE,
            )
            .order_by(BudgetPoste.code)
        )
    ).all()
    resultat: dict[uuid.UUID, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        resultat[row.encaissement_id].append(
            {"code": row.code, "libelle": row.libelle, "annee": row.annee, "montant": str(_money(row.montant))}
        )
    return dict(resultat)


async def synthese_reports(
    db: AsyncSession, *, organisation_id: int, exercice: BudgetExercice
) -> dict[str, Any]:
    """Ce que `exercice` a reporté, et ce qu'il a reçu de l'exercice précédent."""

    async def _par_poste(colonne_exercice, colonne_poste) -> list[dict[str, Any]]:
        rows = (
            await db.execute(
                select(BudgetPoste.id, BudgetPoste.code, BudgetPoste.libelle, ReportCreance.montant, ReportCreance.encaissement_id)
                .join(BudgetPoste, BudgetPoste.id == colonne_poste)
                .where(
                    ReportCreance.organisation_id == organisation_id,
                    colonne_exercice == exercice.id,
                    ReportCreance.statut != REPORT_ANNULE,
                )
            )
        ).all()
        cumul: dict[int, dict[str, Any]] = {}
        for row in rows:
            ligne = cumul.setdefault(
                row.id, {"poste_id": row.id, "code": row.code, "libelle": row.libelle, "montant": Decimal("0"), "notes": set()}
            )
            ligne["montant"] += _money(row.montant)
            ligne["notes"].add(row.encaissement_id)
        return [
            {**ligne, "montant": str(ligne["montant"]), "notes": len(ligne["notes"])}
            for ligne in sorted(cumul.values(), key=lambda l: l["code"])
        ]

    return {
        "annee": exercice.annee,
        "reportes": await _par_poste(ReportCreance.exercice_source_id, ReportCreance.poste_source_id),
        "recus": await _par_poste(ReportCreance.exercice_cible_id, ReportCreance.poste_cible_id),
    }
