from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.budget import BudgetExercice, BudgetLigne, StatutBudget
from app.models.budget_audit_log import BudgetAuditLog
from app.models.encaissement import Encaissement
from app.models.ligne_requisition import LigneRequisition
from app.models.sortie_fonds import SortieFonds
from app.models.print_settings import PrintSettings
from app.models.user import User
from app.schemas.budget import (
    BudgetAuditLogOut,
    BudgetExerciseSummary,
    BudgetExercisesResponse,
    BudgetLineCreate,
    BudgetLineSummary,
    BudgetLineUpdate,
    BudgetLinesResponse,
)

router = APIRouter()


async def _log_budget_change(
    db: AsyncSession,
    *,
    exercice_id: int | None,
    budget_ligne_id: int | None,
    action: str,
    field_name: str,
    old_value: Decimal | None,
    new_value: Decimal | None,
    user: User,
) -> None:
    db.add(
        BudgetAuditLog(
            exercice_id=exercice_id,
            budget_ligne_id=budget_ligne_id,
            action=action,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            user_id=user.id,
        )
    )

async def _is_locked_exercise(exercice_id: int, db: AsyncSession) -> bool:
    max_res = await db.execute(select(func.max(BudgetExercice.annee)))
    max_annee = max_res.scalar_one_or_none()
    if max_annee is None:
        return False
    ex_res = await db.execute(select(BudgetExercice).where(BudgetExercice.id == exercice_id))
    exercice = ex_res.scalar_one_or_none()
    if exercice is None:
        return False
    return exercice.annee < max_annee


@router.post("/exercices/{annee}/cloture")
async def close_budget_exercise(
    annee: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(BudgetExercice).where(BudgetExercice.annee == annee))
    exercice = result.scalar_one_or_none()
    if exercice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exercice introuvable")
    if await _is_locked_exercise(exercice.id, db):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Exercice verrouillé (année antérieure)")
    if exercice.statut == StatutBudget.CLOTURE:
        return {"ok": True, "statut": exercice.statut.value}
    exercice.statut = StatutBudget.CLOTURE
    await db.commit()
    return {"ok": True, "statut": exercice.statut.value}


@router.post("/exercices/{annee}/ouvrir")
async def reopen_budget_exercise(
    annee: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(BudgetExercice).where(BudgetExercice.annee == annee))
    exercice = result.scalar_one_or_none()
    if exercice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exercice introuvable")
    if exercice.statut != StatutBudget.CLOTURE:
        return {"ok": True, "statut": exercice.statut.value if exercice.statut else None}
    exercice.statut = StatutBudget.VOTE
    await db.commit()
    return {"ok": True, "statut": exercice.statut.value}


@router.post("/exercices/{annee}/initialiser")
async def initialize_next_exercise(
    annee: int,
    annee_cible: int | None = None,
    coefficient: float = 0.0,
    overwrite: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    cible = annee_cible or (annee + 1)
    if cible == annee:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="annee_cible invalide")

    src_res = await db.execute(select(BudgetExercice).where(BudgetExercice.annee == annee))
    src = src_res.scalar_one_or_none()
    if src is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exercice source introuvable")

    tgt_res = await db.execute(select(BudgetExercice).where(BudgetExercice.annee == cible))
    tgt = tgt_res.scalar_one_or_none()
    if tgt is not None and not overwrite:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Exercice cible déjà existant")

    if tgt is None:
        tgt = BudgetExercice(annee=cible, statut=StatutBudget.BROUILLON)
        db.add(tgt)
        await db.flush()
    else:
        await db.execute(select(BudgetLigne).where(BudgetLigne.exercice_id == tgt.id))
        await db.execute(
            BudgetLigne.__table__.delete().where(BudgetLigne.exercice_id == tgt.id)
        )
        await db.flush()

    coeff = Decimal(str(coefficient))
    lines_res = await db.execute(select(BudgetLigne).where(BudgetLigne.exercice_id == src.id))
    lines = lines_res.scalars().all()
    for line in lines:
        montant_prevu = Decimal(line.montant_prevu or 0)
        nouveau = montant_prevu + (montant_prevu * coeff)
        db.add(
            BudgetLigne(
                exercice_id=tgt.id,
                code=line.code,
                libelle=line.libelle,
                type=line.type,
                montant_prevu=nouveau,
                montant_engage=0,
                montant_paye=0,
            )
        )

    await db.commit()
    return {"ok": True, "annee_source": annee, "annee_cible": cible}


@router.get("/exercices", response_model=BudgetExercisesResponse)
async def list_budget_exercices(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BudgetExercisesResponse:
    result = await db.execute(select(BudgetExercice).order_by(BudgetExercice.annee.desc()))
    exercices = [
        BudgetExerciseSummary(annee=ex.annee, statut=ex.statut.value if ex.statut else None)
        for ex in result.scalars().all()
    ]
    return BudgetExercisesResponse(exercices=exercices)


@router.get("/summary")
async def budget_summary(
    annee: int | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    async def _latest_exercice_with_lines() -> BudgetExercice | None:
        result = await db.execute(
            select(BudgetExercice)
            .join(BudgetLigne, BudgetLigne.exercice_id == BudgetExercice.id)
            .order_by(BudgetExercice.annee.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _latest_voted_exercice_with_lines() -> BudgetExercice | None:
        result = await db.execute(
            select(BudgetExercice)
            .join(BudgetLigne, BudgetLigne.exercice_id == BudgetExercice.id)
            .where(BudgetExercice.statut == StatutBudget.VOTE)
            .order_by(BudgetExercice.annee.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    if annee is None:
        settings_res = await db.execute(select(PrintSettings).limit(1))
        settings = settings_res.scalar_one_or_none()
        if settings and settings.fiscal_year:
            annee = settings.fiscal_year
    if annee is None:
        active_res = await db.execute(
            select(BudgetExercice)
            .where(BudgetExercice.statut != StatutBudget.CLOTURE)
            .order_by(BudgetExercice.annee.desc())
            .limit(1)
        )
        active = active_res.scalar_one_or_none()
        if active:
            annee = active.annee
    if annee is None:
        max_res = await db.execute(select(func.max(BudgetExercice.annee)))
        annee = max_res.scalar_one_or_none()
    if annee is None:
        return {
            "annee": None,
            "recettes": {"prevu": 0, "reel": 0},
            "depenses": {"prevu": 0, "reel": 0, "engage": 0, "paye": 0},
        }

    ex_res = await db.execute(select(BudgetExercice).where(BudgetExercice.annee == annee))
    exercice = ex_res.scalar_one_or_none()
    if exercice is None:
        exercice = await _latest_voted_exercice_with_lines()
        if exercice is None:
            exercice = await _latest_exercice_with_lines()
        if exercice is None:
            return {
                "annee": annee,
                "recettes": {"prevu": 0, "reel": 0},
                "depenses": {"prevu": 0, "reel": 0, "engage": 0, "paye": 0},
            }
        annee = exercice.annee
    else:
        count_res = await db.execute(
            select(func.count()).select_from(BudgetLigne).where(BudgetLigne.exercice_id == exercice.id)
        )
        if count_res.scalar_one() == 0:
            fallback = await _latest_voted_exercice_with_lines()
            if fallback is None:
                fallback = await _latest_exercice_with_lines()
            if fallback:
                exercice = fallback
                annee = exercice.annee

    recettes_res = await db.execute(
        select(
            func.coalesce(func.sum(BudgetLigne.montant_prevu), 0).label("prevu"),
            func.coalesce(func.sum(BudgetLigne.montant_paye), 0).label("reel"),
        ).where(BudgetLigne.exercice_id == exercice.id, BudgetLigne.type == "RECETTE")
    )
    depenses_res = await db.execute(
        select(
            func.coalesce(func.sum(BudgetLigne.montant_prevu), 0).label("prevu"),
            func.coalesce(func.sum(BudgetLigne.montant_engage), 0).label("engage"),
            func.coalesce(func.sum(BudgetLigne.montant_paye), 0).label("paye"),
        ).where(BudgetLigne.exercice_id == exercice.id, BudgetLigne.type == "DEPENSE")
    )
    recettes = recettes_res.first()
    depenses = depenses_res.first()
    return {
        "annee": annee,
        "recettes": {"prevu": float(recettes.prevu or 0), "reel": float(recettes.reel or 0)},
        "depenses": {
            "prevu": float(depenses.prevu or 0),
            "reel": float(depenses.paye or 0),
            "engage": float(depenses.engage or 0),
            "paye": float(depenses.paye or 0),
        },
    }


@router.get("/audit-logs", response_model=list[BudgetAuditLogOut])
async def list_budget_audit_logs(
    annee: int | None = None,
    limit: int = 200,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[BudgetAuditLogOut]:
    query = select(BudgetAuditLog)
    if annee is not None:
        ex_res = await db.execute(select(BudgetExercice).where(BudgetExercice.annee == annee))
        exercice = ex_res.scalar_one_or_none()
        if exercice is None:
            return []
        query = query.where(BudgetAuditLog.exercice_id == exercice.id)
    query = query.order_by(BudgetAuditLog.created_at.desc()).limit(limit)
    res = await db.execute(query)
    logs = res.scalars().all()
    user_ids = {log.user_id for log in logs if log.user_id}
    user_map: dict[str, User] = {}
    if user_ids:
        users_res = await db.execute(select(User).where(User.id.in_(user_ids)))
        for u in users_res.scalars().all():
            user_map[str(u.id)] = u
    return [
        BudgetAuditLogOut(
            id=log.id,
            exercice_id=log.exercice_id,
            budget_ligne_id=log.budget_ligne_id,
            action=log.action,
            field_name=log.field_name,
            old_value=log.old_value,
            new_value=log.new_value,
            user_id=str(log.user_id) if log.user_id else None,
            user_name=(
                f"{user_map.get(str(log.user_id)).prenom} {user_map.get(str(log.user_id)).nom}".strip()
                if log.user_id and user_map.get(str(log.user_id))
                else None
            ),
            user_role=(user_map.get(str(log.user_id)).role if log.user_id and user_map.get(str(log.user_id)) else None),
            created_at=log.created_at.isoformat(),
        )
        for log in logs
    ]


@router.get("/lines", response_model=BudgetLinesResponse)
async def list_budget_lines(
    annee: int | None = None,
    type: str | None = None,
    active: bool | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BudgetLinesResponse:
    if annee is None:
        result = await db.execute(select(func.max(BudgetExercice.annee)))
        annee = result.scalar_one_or_none()

    if annee is None:
        return BudgetLinesResponse(annee=None, statut=None, lignes=[])

    exercice_result = await db.execute(select(BudgetExercice).where(BudgetExercice.annee == annee))
    exercice = exercice_result.scalar_one_or_none()
    if exercice is None:
        return BudgetLinesResponse(annee=annee, statut=None, lignes=[])

    query = select(BudgetLigne).where(BudgetLigne.exercice_id == exercice.id)
    if type:
        query = query.where(BudgetLigne.type == type.upper())
    if active is not None:
        query = query.where(BudgetLigne.active == active)
    query = query.order_by(BudgetLigne.code)

    lines_result = await db.execute(query)
    lines = lines_result.scalars().all()

    summaries: list[BudgetLineSummary] = []
    for line in lines:
        montant_prevu = Decimal(line.montant_prevu or 0)
        montant_engage = Decimal(line.montant_engage or 0)
        montant_paye = Decimal(line.montant_paye or 0)
        is_depense = (line.type or "").upper() == "DEPENSE"
        base_consomme = montant_paye if is_depense else montant_engage
        disponible = montant_prevu - base_consomme
        if montant_prevu > 0:
            pourcentage = (base_consomme / montant_prevu) * Decimal("100")
        else:
            pourcentage = Decimal("0")

        summaries.append(
            BudgetLineSummary(
                id=line.id,
                code=line.code,
                libelle=line.libelle,
                parent_code=line.parent_code,
                type=line.type,
                active=line.active,
                montant_prevu=montant_prevu,
                montant_engage=montant_engage,
                montant_paye=montant_paye,
                montant_disponible=disponible,
                pourcentage_consomme=pourcentage,
            )
        )

    return BudgetLinesResponse(
        annee=annee,
        statut=exercice.statut.value if exercice.statut else None,
        lignes=summaries,
    )


@router.post("/lines", response_model=BudgetLineSummary, status_code=status.HTTP_201_CREATED)
async def create_budget_line(
    payload: BudgetLineCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BudgetLineSummary:
    exercice_result = await db.execute(select(BudgetExercice).where(BudgetExercice.annee == payload.annee))
    exercice = exercice_result.scalar_one_or_none()
    if exercice is None:
        exercice = BudgetExercice(annee=payload.annee, statut=StatutBudget.BROUILLON)
        db.add(exercice)
        await db.flush()
    if exercice.statut == StatutBudget.CLOTURE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Exercice clôturé")
    if await _is_locked_exercise(exercice.id, db):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Exercice verrouillé (année antérieure)")
    if payload.montant_prevu is not None and payload.montant_prevu < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le montant prévu doit être positif")

    line = BudgetLigne(
        exercice_id=exercice.id,
        code=payload.code.strip(),
        libelle=payload.libelle.strip(),
        parent_code=payload.parent_code.strip() if payload.parent_code else None,
        type=payload.type.strip().upper(),
        active=payload.active,
        montant_prevu=payload.montant_prevu,
    )
    db.add(line)
    await db.commit()
    await db.refresh(line)
    await _log_budget_change(
        db,
        exercice_id=exercice.id,
        budget_ligne_id=line.id,
        action="create",
        field_name="montant_prevu",
        old_value=None,
        new_value=Decimal(line.montant_prevu or 0),
        user=user,
    )
    await db.commit()

    montant_prevu = Decimal(line.montant_prevu or 0)
    montant_engage = Decimal(line.montant_engage or 0)
    montant_paye = Decimal(line.montant_paye or 0)
    is_depense = (line.type or "").upper() == "DEPENSE"
    base_consomme = montant_paye if is_depense else montant_engage
    disponible = montant_prevu - base_consomme
    pourcentage = (base_consomme / montant_prevu) * Decimal("100") if montant_prevu > 0 else Decimal("0")

    return BudgetLineSummary(
        id=line.id,
        code=line.code,
        libelle=line.libelle,
        parent_code=line.parent_code,
        type=line.type,
        active=line.active,
        montant_prevu=montant_prevu,
        montant_engage=montant_engage,
        montant_paye=montant_paye,
        montant_disponible=disponible,
        pourcentage_consomme=pourcentage,
    )


@router.put("/lines/{line_id}", response_model=BudgetLineSummary)
async def update_budget_line(
    line_id: int,
    payload: BudgetLineUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BudgetLineSummary:
    result = await db.execute(select(BudgetLigne).where(BudgetLigne.id == line_id))
    line = result.scalar_one_or_none()
    if line is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ligne budgétaire introuvable")
    ex_res = await db.execute(select(BudgetExercice).where(BudgetExercice.id == line.exercice_id))
    exercice = ex_res.scalar_one_or_none()
    if exercice and exercice.statut == StatutBudget.CLOTURE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Exercice clôturé")
    if exercice and await _is_locked_exercise(exercice.id, db):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Exercice verrouillé (année antérieure)")

    linked_requisitions = await db.execute(
        select(LigneRequisition.id).where(LigneRequisition.budget_ligne_id == line.id).limit(1)
    )
    if linked_requisitions.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action impossible : des réquisitions sont liées à cette rubrique",
        )
    linked_enc = await db.execute(
        select(Encaissement.id).where(Encaissement.budget_ligne_id == line.id).limit(1)
    )
    if linked_enc.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action impossible : des encaissements sont liés à cette rubrique",
        )
    linked_sorties = await db.execute(
        select(SortieFonds.id).where(SortieFonds.budget_ligne_id == line.id).limit(1)
    )
    if linked_sorties.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action impossible : des sorties de fonds sont liées à cette rubrique",
        )

    if payload.code is not None:
        line.code = payload.code.strip()
    if payload.libelle is not None:
        line.libelle = payload.libelle.strip()
    if payload.type is not None:
        line.type = payload.type.strip().upper()
    if payload.parent_code is not None:
        line.parent_code = payload.parent_code.strip() if payload.parent_code else None
    if payload.active is not None:
        line.active = payload.active
    if payload.montant_prevu is not None:
        old_prevu = Decimal(line.montant_prevu or 0)
        if payload.montant_prevu < 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le montant prévu doit être positif")
        line.montant_prevu = payload.montant_prevu
        new_prevu = Decimal(payload.montant_prevu or 0)
        if new_prevu != old_prevu:
            await _log_budget_change(
                db,
                exercice_id=line.exercice_id,
                budget_ligne_id=line.id,
                action="update",
                field_name="montant_prevu",
                old_value=old_prevu,
                new_value=new_prevu,
                user=user,
            )

    await db.commit()
    await db.refresh(line)

    montant_prevu = Decimal(line.montant_prevu or 0)
    montant_engage = Decimal(line.montant_engage or 0)
    montant_paye = Decimal(line.montant_paye or 0)
    is_depense = (line.type or "").upper() == "DEPENSE"
    base_consomme = montant_paye if is_depense else montant_engage
    disponible = montant_prevu - base_consomme
    pourcentage = (base_consomme / montant_prevu) * Decimal("100") if montant_prevu > 0 else Decimal("0")

    return BudgetLineSummary(
        id=line.id,
        code=line.code,
        libelle=line.libelle,
        parent_code=line.parent_code,
        type=line.type,
        active=line.active,
        montant_prevu=montant_prevu,
        montant_engage=montant_engage,
        montant_paye=montant_paye,
        montant_disponible=disponible,
        pourcentage_consomme=pourcentage,
    )


@router.delete("/lines/{line_id}")
async def delete_budget_line(
    line_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(BudgetLigne).where(BudgetLigne.id == line_id))
    line = result.scalar_one_or_none()
    if line is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ligne budgétaire introuvable")
    ex_res = await db.execute(select(BudgetExercice).where(BudgetExercice.id == line.exercice_id))
    exercice = ex_res.scalar_one_or_none()
    if exercice and exercice.statut == StatutBudget.CLOTURE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Exercice clôturé")
    if exercice and await _is_locked_exercise(exercice.id, db):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Exercice verrouillé (année antérieure)")
    await db.delete(line)
    await db.commit()
    await _log_budget_change(
        db,
        exercice_id=line.exercice_id,
        budget_ligne_id=line.id,
        action="delete",
        field_name="ligne",
        old_value=None,
        new_value=None,
        user=user,
    )
    await db.commit()
    return {"ok": True}
