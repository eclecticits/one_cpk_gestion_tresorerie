from __future__ import annotations

import json
import enum
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import get_current_tenant_id, get_current_user
from app.db.session import get_db
from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.budget_audit_log import BudgetAuditLog
from app.models.encaissement import Encaissement
from app.models.service import Service
from app.models.service_rubrique import ServiceRubrique
from app.models.ligne_requisition import LigneRequisition
from app.models.requisition import Requisition
from app.models.sortie_fonds import SortieFonds
from app.models.print_settings import PrintSettings
from app.models.service_rubrique import ServiceRubrique
from app.models.user import User
from app.modules.comptabilite.models import ComptaMappingPosteBudgetaire
from app.services.forecasting import PENDING_REQUISITION_STATUSES
from app.services.service_access import can_view_all_services, get_user_service_ids
from app.schemas.budget import (
    BudgetAuditLogOut,
    BudgetExerciseCreate,
    BudgetExerciseSummary,
    BudgetExercisesResponse,
    BudgetPosteCreate,
    BudgetPosteSummary,
    BudgetPosteTree,
    BudgetPosteUpdate,
    BudgetPostesResponse,
    BudgetPostesTreeResponse,
    BudgetLinesResponse,
    BudgetLinesTreeResponse,
    BudgetLineSummary,
    BudgetLineCreate,
    BudgetLineUpdate,
    BudgetPosteImportRequest,
    BudgetPosteImportResponse,
)

router = APIRouter()

REPLACE_BUDGET_CONFIRMATION = "REMPLACER BUDGET"


@dataclass(slots=True)
class _BudgetTreeLine:
    id: int
    exercice_id: int
    code: str
    libelle: str
    parent_code: str | None
    parent_id: int | None
    type: str | None
    active: bool
    is_global: bool
    montant_prevu: Decimal
    montant_engage: Decimal
    montant_paye: Decimal


async def _get_or_create_budget_exercice(
    db: AsyncSession,
    *,
    organisation_id: int,
    annee: int,
    statut: StatutBudget = StatutBudget.BROUILLON,
) -> BudgetExercice:
    result = await db.execute(
        select(BudgetExercice).where(
            BudgetExercice.annee == annee,
            BudgetExercice.organisation_id == organisation_id,
        )
    )
    exercice = result.scalar_one_or_none()
    if exercice is not None:
        return exercice

    try:
        async with db.begin_nested():
            exercice = BudgetExercice(annee=annee, statut=statut, organisation_id=organisation_id)
            db.add(exercice)
            await db.flush()
            return exercice
    except IntegrityError:
        result = await db.execute(
            select(BudgetExercice).where(
                BudgetExercice.annee == annee,
                BudgetExercice.organisation_id == organisation_id,
            )
        )
        exercice = result.scalar_one_or_none()
        if exercice is None:
            raise
        return exercice


async def _log_budget_change(
    db: AsyncSession,
    *,
    exercice_id: int | None,
    budget_poste_id: int | None,
    action: str,
    field_name: str,
    old_value: Decimal | None,
    new_value: Decimal | None,
    user: User,
) -> None:
    db.add(
        BudgetAuditLog(
            organisation_id=user.organisation_id,
            exercice_id=exercice_id,
            budget_poste_id=budget_poste_id,
            action=action,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            user_id=user.id,
        )
    )


async def _is_locked_exercise(exercice_id: int, db: AsyncSession, organisation_id: int) -> bool:
    max_res = await db.execute(
        select(func.max(BudgetExercice.annee)).where(BudgetExercice.organisation_id == organisation_id)
    )
    max_annee = max_res.scalar_one_or_none()
    if max_annee is None:
        return False
    ex_res = await db.execute(
        select(BudgetExercice).where(
            BudgetExercice.id == exercice_id,
            BudgetExercice.organisation_id == organisation_id,
        )
    )
    exercice = ex_res.scalar_one_or_none()
    if exercice is None:
        return False
    return exercice.annee < max_annee


async def _resolve_parent_link(
    db: AsyncSession,
    *,
    exercice_id: int,
    parent_id: int | None,
    parent_code: str | None,
    organisation_id: int,
) -> tuple[int | None, str | None]:
    parent_code = _normalize_budget_code(parent_code) if parent_code else None
    if parent_id is None and not parent_code:
        return None, None

    parent_line: BudgetPoste | None = None
    if parent_id is not None:
        res = await db.execute(
            select(BudgetPoste).where(
                BudgetPoste.id == parent_id,
                BudgetPoste.is_deleted.is_(False),
                BudgetPoste.organisation_id == organisation_id,
            )
        )
        parent_line = res.scalar_one_or_none()
        if parent_line is None or parent_line.exercice_id != exercice_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rubrique parente invalide")
        if parent_code and parent_code != parent_line.code:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rubrique parente incohérente")
        return parent_line.id, parent_line.code

    if parent_code:
        res = await db.execute(
            select(BudgetPoste).where(
                BudgetPoste.exercice_id == exercice_id,
                BudgetPoste.code == parent_code,
                BudgetPoste.is_deleted.is_(False),
                BudgetPoste.organisation_id == organisation_id,
            )
        )
        parent_lines = res.scalars().all()
        if len(parent_lines) > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Plusieurs postes parents trouvés pour le code {parent_code}.",
            )
        if parent_lines:
            return parent_lines[0].id, parent_lines[0].code
        return None, parent_code

    return None, None


def _normalize_budget_code(value: str | None) -> str | None:
    if not value:
        return None
    code = value.strip()
    code = re.sub(r"\s+", "", code)
    code = re.sub(r"\.+", ".", code)
    code = code.strip(".")
    return code or None


def _split_budget_code(code: str) -> list[str]:
    normalized = _normalize_budget_code(code) or ""
    return [part for part in normalized.split(".") if part]


async def _ensure_budget_parent_chain(
    db: AsyncSession,
    *,
    exercice_id: int,
    organisation_id: int,
    type_value: str,
    parent_code: str,
    existing_by_code: dict[str, BudgetPoste],
) -> tuple[int | None, str | None]:
    parts = _split_budget_code(parent_code)
    if not parts:
        return None, None

    current_parent_id: int | None = None
    current_parent_code: str | None = None
    for depth, part in enumerate(parts, start=1):
        prefix = ".".join(parts[:depth])
        normalized_prefix = (_normalize_budget_code(prefix) or "").lower()
        if not normalized_prefix:
            continue
        existing = existing_by_code.get(normalized_prefix)
        if existing is None:
            parent_line = BudgetPoste(
                organisation_id=organisation_id,
                exercice_id=exercice_id,
                code=prefix,
                libelle=f"Groupe {prefix}",
                parent_id=current_parent_id,
                parent_code=current_parent_code,
                type=type_value,
                active=True,
                montant_prevu=0,
                montant_engage=0,
                montant_paye=0,
                is_deleted=False,
            )
            db.add(parent_line)
            await db.flush()
            existing_by_code[normalized_prefix] = parent_line
            current_parent_id = parent_line.id
            current_parent_code = parent_line.code
            continue

        if current_parent_id is not None and existing.parent_id != current_parent_id:
            existing.parent_id = current_parent_id
            existing.parent_code = current_parent_code
        if existing.is_deleted:
            existing.is_deleted = False
            existing.deleted_at = None
            existing.deleted_by = None
        if not existing.type:
            existing.type = type_value
        await db.flush()
        current_parent_id = existing.id
        current_parent_code = existing.code

    return current_parent_id, current_parent_code


async def _has_children(db: AsyncSession, line_id: int) -> bool:
    res = await db.execute(
        select(func.count())
        .select_from(BudgetPoste)
        .where(
            BudgetPoste.parent_id == line_id,
            BudgetPoste.id != line_id,
            BudgetPoste.is_deleted.is_(False),
        )
    )
    return res.scalar_one() > 0


def _json_safe(value):
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _model_payload(row) -> dict:
    return {column.name: _json_safe(getattr(row, column.name)) for column in row.__table__.columns}


async def _write_budget_replace_backup(
    db: AsyncSession,
    *,
    organisation_id: int,
    exercice: BudgetExercice,
) -> str:
    postes_res = await db.execute(
        select(BudgetPoste).where(
            BudgetPoste.organisation_id == organisation_id,
            BudgetPoste.exercice_id == exercice.id,
        )
    )
    postes = postes_res.scalars().all()
    poste_ids = [poste.id for poste in postes]

    service_rubriques = []
    mappings = []
    audit_logs = []
    if poste_ids:
        service_res = await db.execute(
            select(ServiceRubrique).where(ServiceRubrique.budget_poste_id.in_(poste_ids))
        )
        service_rubriques = service_res.scalars().all()
        mappings_res = await db.execute(
            select(ComptaMappingPosteBudgetaire).where(
                ComptaMappingPosteBudgetaire.organisation_id == organisation_id,
                ComptaMappingPosteBudgetaire.budget_poste_id.in_(poste_ids),
            )
        )
        mappings = mappings_res.scalars().all()
        audit_res = await db.execute(
            select(BudgetAuditLog).where(
                BudgetAuditLog.organisation_id == organisation_id,
                (
                    (BudgetAuditLog.exercice_id == exercice.id)
                    | (BudgetAuditLog.budget_poste_id.in_(poste_ids))
                ),
            )
        )
        audit_logs = audit_res.scalars().all()

    payload = {
        "operation": "budget_import_replace_exercise",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "organisation_id": organisation_id,
        "exercice": _model_payload(exercice),
        "budget_postes": [_model_payload(row) for row in postes],
        "service_rubriques": [_model_payload(row) for row in service_rubriques],
        "compta_mapping_poste_budgetaire": [_model_payload(row) for row in mappings],
        "budget_audit_logs": [_model_payload(row) for row in audit_logs],
    }

    backup_dir = Path("backups")
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"budget_import_replace_org{organisation_id}_{exercice.annee}_{stamp}.json"
    backup_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if not backup_path.exists() or backup_path.stat().st_size <= 0:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Sauvegarde budget vide ou absente")
    return str(backup_path)


async def _assert_budget_replace_has_no_operational_refs(
    db: AsyncSession,
    *,
    organisation_id: int,
    poste_ids: list[int],
) -> None:
    if not poste_ids:
        return
    checks = [
        ("encaissements", Encaissement, Encaissement.id, Encaissement.budget_poste_id),
        ("lignes_requisition", LigneRequisition, LigneRequisition.id, LigneRequisition.budget_poste_id),
        ("sorties_fonds", SortieFonds, SortieFonds.id, SortieFonds.budget_poste_id),
    ]
    blocking: list[dict] = []
    for table_name, model, id_column, budget_column in checks:
        res = await db.execute(
            select(id_column)
            .where(
                model.organisation_id == organisation_id,
                budget_column.in_(poste_ids),
            )
            .limit(10)
        )
        ids = [str(item) for item in res.scalars().all()]
        if ids:
            blocking.append({"table": table_name, "ids": ids})
    if blocking:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Remplacement impossible: des opérations référencent encore des postes budgétaires.",
                "references": blocking,
            },
        )


async def _delete_budget_exercise_poste_settings(
    db: AsyncSession,
    *,
    organisation_id: int,
    exercice_id: int,
    poste_ids: list[int],
) -> None:
    if not poste_ids:
        return
    await db.execute(delete(ServiceRubrique).where(ServiceRubrique.budget_poste_id.in_(poste_ids)))
    await db.execute(
        delete(ComptaMappingPosteBudgetaire).where(
            ComptaMappingPosteBudgetaire.organisation_id == organisation_id,
            ComptaMappingPosteBudgetaire.budget_poste_id.in_(poste_ids),
        )
    )
    await db.execute(
        delete(BudgetAuditLog).where(
            BudgetAuditLog.organisation_id == organisation_id,
            (
                (BudgetAuditLog.exercice_id == exercice_id)
                | (BudgetAuditLog.budget_poste_id.in_(poste_ids))
            ),
        )
    )
    await db.execute(
        update(BudgetPoste)
        .where(
            BudgetPoste.organisation_id == organisation_id,
            BudgetPoste.exercice_id == exercice_id,
        )
        .values(parent_id=None, parent_code=None)
    )
    await db.execute(
        delete(BudgetPoste).where(
            BudgetPoste.organisation_id == organisation_id,
            BudgetPoste.exercice_id == exercice_id,
        )
    )


async def _refresh_parent_totals(db: AsyncSession, parent_id: int | None) -> None:
    current_id = parent_id
    visited: set[int] = set()
    while current_id and current_id not in visited:
        visited.add(current_id)
        total_res = await db.execute(
            select(func.coalesce(func.sum(BudgetPoste.montant_prevu), 0)).where(
                BudgetPoste.parent_id == current_id,
                BudgetPoste.is_deleted.is_(False),
            )
        )
        total = Decimal(total_res.scalar_one() or 0)
        parent_res = await db.execute(select(BudgetPoste).where(BudgetPoste.id == current_id))
        parent = parent_res.scalar_one_or_none()
        if parent is None:
            break
        parent.montant_prevu = total
        await db.flush()
        current_id = parent.parent_id


def _build_tree_nodes(lines: list[BudgetPoste]) -> list[dict]:
    nodes: dict[int, dict] = {}
    by_code: dict[tuple[int, str], dict] = {}
    for line in lines:
        node = {"line": line, "children": []}
        nodes[line.id] = node
        if line.code:
            by_code[(line.exercice_id, line.code)] = node

    roots: list[dict] = []
    for line in lines:
        node = nodes[line.id]
        parent_node = None
        if line.parent_id:
            parent_node = nodes.get(line.parent_id)
        elif line.parent_code:
            parent_node = by_code.get((line.exercice_id, line.parent_code))
        if parent_node and parent_node is not node:
            parent_node["children"].append(node)
        else:
            roots.append(node)

    def _sort_children(item: dict) -> None:
        item["children"].sort(key=lambda child: (child["line"].code or ""))
        for child in item["children"]:
            _sort_children(child)

    roots.sort(key=lambda child: (child["line"].code or ""))
    for root in roots:
        _sort_children(root)

    return roots


def _compute_tree_totals(node: dict) -> dict:
    children = node["children"]
    if children:
        totals = {"montant_prevu": Decimal("0"), "montant_engage": Decimal("0"), "montant_paye": Decimal("0")}
        for child in children:
            child_totals = _compute_tree_totals(child)
            totals["montant_prevu"] += child_totals["montant_prevu"]
            totals["montant_engage"] += child_totals["montant_engage"]
            totals["montant_paye"] += child_totals["montant_paye"]
    else:
        line = node["line"]
        totals = {
            "montant_prevu": Decimal(line.montant_prevu or 0),
            "montant_engage": Decimal(line.montant_engage or 0),
            "montant_paye": Decimal(line.montant_paye or 0),
        }

    line = node["line"]
    is_depense = (line.type or "").upper() == "DEPENSE"
    base_consomme = totals["montant_paye"] if is_depense else totals["montant_engage"]
    disponible = totals["montant_prevu"] - base_consomme
    if totals["montant_prevu"] > 0:
        pourcentage = (base_consomme / totals["montant_prevu"]) * Decimal("100")
    else:
        pourcentage = Decimal("0")

    totals["montant_disponible"] = disponible
    totals["pourcentage_consomme"] = pourcentage
    node["totals"] = totals
    return totals


def _node_to_tree_schema(node: dict) -> BudgetPosteTree:
    line = node["line"]
    totals = node.get("totals") or _compute_tree_totals(node)
    return BudgetPosteTree(
        id=line.id,
        code=line.code,
        libelle=line.libelle,
        parent_code=line.parent_code,
        parent_id=line.parent_id,
        type=line.type,
        active=line.active,
        is_global=line.is_global,
        montant_prevu=totals["montant_prevu"],
        montant_engage=totals["montant_engage"],
        montant_paye=totals["montant_paye"],
        montant_disponible=totals["montant_disponible"],
        pourcentage_consomme=totals["pourcentage_consomme"],
        children=[_node_to_tree_schema(child) for child in node["children"]],
    )


@router.post("/exercices/{annee}/cloture")
async def close_budget_exercise(
    annee: int,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(BudgetExercice).where(
            BudgetExercice.annee == annee,
            BudgetExercice.organisation_id == tenant_id,
        )
    )
    exercice = result.scalar_one_or_none()
    if exercice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exercice introuvable")
    if await _is_locked_exercise(exercice.id, db, tenant_id):
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
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(BudgetExercice).where(
            BudgetExercice.annee == annee,
            BudgetExercice.organisation_id == tenant_id,
        )
    )
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
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    cible = annee_cible or (annee + 1)
    if cible == annee:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="annee_cible invalide")

    src_res = await db.execute(
        select(BudgetExercice).where(
            BudgetExercice.annee == annee,
            BudgetExercice.organisation_id == tenant_id,
        )
    )
    src = src_res.scalar_one_or_none()
    if src is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exercice source introuvable")

    tgt_res = await db.execute(
        select(BudgetExercice).where(
            BudgetExercice.annee == cible,
            BudgetExercice.organisation_id == tenant_id,
        )
    )
    tgt = tgt_res.scalar_one_or_none()
    if tgt is not None and not overwrite:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Exercice cible déjà existant")

    if tgt is None:
        tgt = BudgetExercice(annee=cible, statut=StatutBudget.BROUILLON, organisation_id=tenant_id)
        db.add(tgt)
        await db.flush()
    else:
        await db.execute(
            select(BudgetPoste).where(
                BudgetPoste.exercice_id == tgt.id,
                BudgetPoste.organisation_id == tenant_id,
                BudgetPoste.is_deleted.is_(False),
            )
        )
        await db.execute(
            BudgetPoste.__table__.update()
            .where(
                BudgetPoste.exercice_id == tgt.id,
                BudgetPoste.organisation_id == tenant_id,
            )
            .values(is_deleted=True)
        )
        await db.flush()

    coeff = Decimal(str(coefficient))
    parent_ids_subq = (
        select(BudgetPoste.parent_id)
        .where(
            BudgetPoste.exercice_id == src.id,
            BudgetPoste.organisation_id == tenant_id,
            BudgetPoste.is_deleted.is_(False),
            BudgetPoste.parent_id.is_not(None),
        )
        .distinct()
    )
    totals_res = await db.execute(
        select(
            func.coalesce(func.sum(BudgetPoste.montant_prevu), 0),
            func.coalesce(func.sum(BudgetPoste.montant_paye), 0),
        ).where(
            BudgetPoste.exercice_id == src.id,
            BudgetPoste.organisation_id == tenant_id,
            BudgetPoste.is_deleted.is_(False),
            BudgetPoste.type == "DEPENSE",
            BudgetPoste.id.not_in(parent_ids_subq),
        )
    )
    total_prevu, total_paye = totals_res.one()
    report_amount = Decimal(total_prevu or 0) - Decimal(total_paye or 0)
    lines_res = await db.execute(
        select(BudgetPoste).where(
            BudgetPoste.exercice_id == src.id,
            BudgetPoste.organisation_id == tenant_id,
            BudgetPoste.is_deleted.is_(False),
        )
    )
    lines = lines_res.scalars().all()
    for line in lines:
        montant_prevu = Decimal(line.montant_prevu or 0)
        nouveau = montant_prevu + (montant_prevu * coeff)
        db.add(
            BudgetPoste(
                organisation_id=tenant_id,
                exercice_id=tgt.id,
                code=line.code,
                libelle=line.libelle,
                parent_code=line.parent_code,
                type=line.type,
                montant_prevu=nouveau,
                montant_engage=0,
                montant_paye=0,
            )
        )

    await db.flush()

    tgt_lines_res = await db.execute(
        select(BudgetPoste).where(
            BudgetPoste.exercice_id == tgt.id,
            BudgetPoste.organisation_id == tenant_id,
        )
    )
    tgt_lines = tgt_lines_res.scalars().all()
    code_map = {item.code: item for item in tgt_lines}
    for item in tgt_lines:
        if item.parent_code:
            parent = code_map.get(item.parent_code)
            if parent and parent.id != item.id:
                item.parent_id = parent.id

    report_res = await db.execute(
        select(BudgetPoste).where(
            BudgetPoste.exercice_id == tgt.id,
            BudgetPoste.organisation_id == tenant_id,
            BudgetPoste.is_deleted.is_(False),
            BudgetPoste.code == "I",
            BudgetPoste.type == "RECETTE",
        )
    )
    report_line = report_res.scalar_one_or_none()
    if report_line:
        report_line.libelle = "Report N-1"
        report_line.parent_id = None
        report_line.parent_code = None
        report_line.montant_prevu = report_amount
        report_line.montant_engage = Decimal("0")
        report_line.montant_paye = Decimal("0")
        report_line.active = True
    else:
        db.add(
            BudgetPoste(
                organisation_id=tenant_id,
                exercice_id=tgt.id,
                code="I",
                libelle="Report N-1",
                parent_code=None,
                parent_id=None,
                type="RECETTE",
                active=True,
                montant_prevu=report_amount,
                montant_engage=Decimal("0"),
                montant_paye=Decimal("0"),
            )
        )

    await db.commit()
    return {"ok": True, "annee_source": annee, "annee_cible": cible}


@router.get("/exercices", response_model=BudgetExercisesResponse)
async def list_budget_exercices(
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> BudgetExercisesResponse:
    result = await db.execute(
        select(BudgetExercice)
        .where(BudgetExercice.organisation_id == tenant_id)
        .order_by(BudgetExercice.annee.desc())
    )
    exercices = [
        BudgetExerciseSummary(annee=ex.annee, statut=ex.statut.value if ex.statut else None)
        for ex in result.scalars().all()
    ]
    return BudgetExercisesResponse(exercices=exercices)


@router.post("/exercices", response_model=BudgetExerciseSummary, status_code=status.HTTP_201_CREATED)
async def create_budget_exercise(
    payload: BudgetExerciseCreate,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> BudgetExerciseSummary:
    exercice = await _get_or_create_budget_exercice(
        db,
        organisation_id=tenant_id,
        annee=payload.annee,
        statut=StatutBudget.BROUILLON,
    )
    await db.commit()
    await db.refresh(exercice)
    return BudgetExerciseSummary(annee=exercice.annee, statut=exercice.statut.value if exercice.statut else None)


@router.get("/summary")
async def budget_summary(
    annee: int | None = None,
    service_id: int | None = None,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    org_id = tenant_id

    async def _latest_exercice_with_lines() -> BudgetExercice | None:
        result = await db.execute(
            select(BudgetExercice)
            .join(BudgetPoste, BudgetPoste.exercice_id == BudgetExercice.id)
            .where(
                BudgetExercice.organisation_id == org_id,
                BudgetPoste.organisation_id == org_id,
                BudgetPoste.is_deleted.is_(False),
            )
            .order_by(BudgetExercice.annee.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _latest_voted_exercice_with_lines() -> BudgetExercice | None:
        result = await db.execute(
            select(BudgetExercice)
            .join(BudgetPoste, BudgetPoste.exercice_id == BudgetExercice.id)
            .where(
                BudgetExercice.organisation_id == org_id,
                BudgetPoste.organisation_id == org_id,
                BudgetExercice.statut == StatutBudget.VOTE,
                BudgetPoste.is_deleted.is_(False),
            )
            .order_by(BudgetExercice.annee.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    if annee is None:
        settings_res = await db.execute(
            select(PrintSettings).where(PrintSettings.organisation_id == org_id).limit(1)
        )
        settings = settings_res.scalar_one_or_none()
        if settings and settings.fiscal_year:
            annee = settings.fiscal_year
    if annee is None:
        active_res = await db.execute(
            select(BudgetExercice)
            .where(
                BudgetExercice.organisation_id == org_id,
                BudgetExercice.statut != StatutBudget.CLOTURE,
            )
            .order_by(BudgetExercice.annee.desc())
            .limit(1)
        )
        active = active_res.scalar_one_or_none()
        if active:
            annee = active.annee
    if annee is None:
        max_res = await db.execute(
            select(func.max(BudgetExercice.annee)).where(BudgetExercice.organisation_id == org_id)
        )
        annee = max_res.scalar_one_or_none()
    if annee is None:
        return {
            "annee": None,
            "recettes": {"prevu": 0, "reel": 0},
            "depenses": {"prevu": 0, "reel": 0, "engage": 0, "paye": 0},
            "service_id": service_id,
            "total_recettes": 0,
            "total_depenses": 0,
            "solde": 0,
        }

    ex_res = await db.execute(
        select(BudgetExercice).where(
            BudgetExercice.organisation_id == org_id,
            BudgetExercice.annee == annee,
        )
    )
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
                "service_id": service_id,
                "total_recettes": 0,
                "total_depenses": 0,
                "solde": 0,
            }
        annee = exercice.annee
    else:
        count_res = await db.execute(
            select(func.count())
            .select_from(BudgetPoste)
            .where(
                BudgetPoste.organisation_id == org_id,
                BudgetPoste.exercice_id == exercice.id,
                BudgetPoste.is_deleted.is_(False),
            )
        )
        if count_res.scalar_one() == 0:
            fallback = await _latest_voted_exercice_with_lines()
            if fallback is None:
                fallback = await _latest_exercice_with_lines()
            if fallback:
                exercice = fallback
                annee = exercice.annee

    if service_id is not None:
        service_res = await db.execute(
            select(Service).where(Service.id == service_id, Service.organisation_id == org_id)
        )
        if service_res.scalar_one_or_none() is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service non trouvé")

        recettes_res = await db.execute(
            select(func.coalesce(func.sum(func.coalesce(Encaissement.montant_paye, 0)), 0))
            .select_from(Encaissement)
            .join(BudgetPoste, BudgetPoste.id == Encaissement.budget_poste_id)
            .where(
                Encaissement.service_id == service_id,
                Encaissement.organisation_id == org_id,
                BudgetPoste.organisation_id == org_id,
                BudgetPoste.exercice_id == exercice.id,
                BudgetPoste.type == "RECETTE",
                Encaissement.est_proforma.is_(False),
            )
        )
        depenses_res = await db.execute(
            select(func.coalesce(func.sum(func.coalesce(SortieFonds.montant_paye, 0)), 0))
            .select_from(SortieFonds)
            .join(BudgetPoste, BudgetPoste.id == SortieFonds.budget_poste_id)
            .where(
                SortieFonds.service_id == service_id,
                SortieFonds.organisation_id == org_id,
                BudgetPoste.organisation_id == org_id,
                BudgetPoste.exercice_id == exercice.id,
                BudgetPoste.type == "DEPENSE",
                (SortieFonds.statut.is_(None)) | (func.upper(SortieFonds.statut) == "VALIDE"),
            )
        )
        total_recettes = float(recettes_res.scalar_one() or 0)
        total_depenses = float(depenses_res.scalar_one() or 0)
        return {
            "annee": annee,
            "recettes": {"prevu": 0, "reel": total_recettes},
            "depenses": {"prevu": 0, "reel": total_depenses, "engage": 0, "paye": total_depenses},
            "service_id": service_id,
            "total_recettes": total_recettes,
            "total_depenses": total_depenses,
            "solde": total_recettes - total_depenses,
        }

    child = aliased(BudgetPoste)
    leaf_condition = ~exists().where(
        child.parent_id == BudgetPoste.id,
        child.organisation_id == org_id,
        child.is_deleted.is_(False),
    )

    recettes_res = await db.execute(
        select(
            func.coalesce(func.sum(BudgetPoste.montant_prevu), 0).label("prevu"),
            func.coalesce(func.sum(BudgetPoste.montant_paye), 0).label("reel"),
        ).where(
            BudgetPoste.exercice_id == exercice.id,
            BudgetPoste.organisation_id == org_id,
            BudgetPoste.type == "RECETTE",
            BudgetPoste.is_deleted.is_(False),
            leaf_condition,
        )
    )
    depenses_res = await db.execute(
        select(
            func.coalesce(func.sum(BudgetPoste.montant_prevu), 0).label("prevu"),
            func.coalesce(func.sum(BudgetPoste.montant_engage), 0).label("engage"),
            func.coalesce(func.sum(BudgetPoste.montant_paye), 0).label("paye"),
        ).where(
            BudgetPoste.exercice_id == exercice.id,
            BudgetPoste.organisation_id == org_id,
            BudgetPoste.type == "DEPENSE",
            BudgetPoste.is_deleted.is_(False),
            leaf_condition,
        )
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
        "service_id": service_id,
        "total_recettes": float(recettes.reel or 0),
        "total_depenses": float(depenses.paye or 0),
        "solde": float(recettes.reel or 0) - float(depenses.paye or 0),
    }


@router.get("/summary/mine")
async def budget_summary_mine(
    service_id: int | None = None,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if user.role != "admin":
        service_ids = await get_user_service_ids(db, user)
        if not service_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Utilisateur sans service assigné.")
        if service_id is None:
            if len(service_ids) == 1:
                service_id = service_ids[0]
            else:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="service_id requis")
        if service_id not in service_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès interdit")
    elif service_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="service_id requis")

    async def _resolve_exercice() -> BudgetExercice | None:
        settings_res = await db.execute(
            select(PrintSettings).where(PrintSettings.organisation_id == tenant_id).limit(1)
        )
        settings = settings_res.scalar_one_or_none()
        if settings and settings.fiscal_year:
            ex_res = await db.execute(
                select(BudgetExercice).where(
                    BudgetExercice.annee == settings.fiscal_year,
                    BudgetExercice.organisation_id == tenant_id,
                )
            )
            ex = ex_res.scalar_one_or_none()
            if ex:
                return ex

        active_res = await db.execute(
            select(BudgetExercice)
            .where(
                BudgetExercice.organisation_id == tenant_id,
                BudgetExercice.statut != StatutBudget.CLOTURE,
            )
            .order_by(BudgetExercice.annee.desc())
            .limit(1)
        )
        active = active_res.scalar_one_or_none()
        if active:
            return active

        max_res = await db.execute(
            select(func.max(BudgetExercice.annee)).where(BudgetExercice.organisation_id == tenant_id)
        )
        max_annee = max_res.scalar_one_or_none()
        if max_annee is None:
            return None
        ex_res = await db.execute(
            select(BudgetExercice).where(
                BudgetExercice.annee == max_annee,
                BudgetExercice.organisation_id == tenant_id,
            )
        )
        return ex_res.scalar_one_or_none()

    exercice = await _resolve_exercice()
    if exercice is None:
        return {
            "annee": None,
            "total": 0,
            "total_depenses": 0,
            "total_recettes": 0,
            "consomme": 0,
            "en_attente": 0,
            "disponible": 0,
        }

    # Le montant d'un poste parent est un ROLLUP : il vaut déjà la somme de ses
    # sous-postes (cf. _refresh_parent_totals). Sommer parents ET enfants
    # compterait donc chaque montant deux fois. On ne retient que les feuilles,
    # exactement comme /budget/summary, l'export Excel et l'écran Budget.
    child = aliased(BudgetPoste)
    leaf_condition = ~exists().where(
        child.parent_id == BudgetPoste.id,
        child.organisation_id == tenant_id,
        child.is_deleted.is_(False),
    )

    total_depenses_res = await db.execute(
        select(func.coalesce(func.sum(func.coalesce(BudgetPoste.montant_prevu, 0)), 0))
        .select_from(BudgetPoste)
        .join(ServiceRubrique, ServiceRubrique.budget_poste_id == BudgetPoste.id)
        .where(
            BudgetPoste.exercice_id == exercice.id,
            BudgetPoste.organisation_id == tenant_id,
            BudgetPoste.is_deleted.is_(False),
            BudgetPoste.type == "DEPENSE",
            ServiceRubrique.service_id == service_id,
            leaf_condition,
        )
    )
    total_depenses = float(total_depenses_res.scalar_one() or 0)

    total_recettes_res = await db.execute(
        select(func.coalesce(func.sum(func.coalesce(BudgetPoste.montant_prevu, 0)), 0))
        .select_from(BudgetPoste)
        .join(ServiceRubrique, ServiceRubrique.budget_poste_id == BudgetPoste.id)
        .where(
            BudgetPoste.exercice_id == exercice.id,
            BudgetPoste.organisation_id == tenant_id,
            BudgetPoste.is_deleted.is_(False),
            BudgetPoste.type == "RECETTE",
            ServiceRubrique.service_id == service_id,
            leaf_condition,
        )
    )
    total_recettes = float(total_recettes_res.scalar_one() or 0)

    consomme_res = await db.execute(
        select(func.coalesce(func.sum(func.coalesce(SortieFonds.montant_paye, 0)), 0))
        .select_from(SortieFonds)
        .join(BudgetPoste, BudgetPoste.id == SortieFonds.budget_poste_id)
        .join(ServiceRubrique, ServiceRubrique.budget_poste_id == BudgetPoste.id)
        .where(
            SortieFonds.service_id == service_id,
            SortieFonds.organisation_id == tenant_id,
            ServiceRubrique.service_id == service_id,
            BudgetPoste.exercice_id == exercice.id,
            BudgetPoste.organisation_id == tenant_id,
            (SortieFonds.statut.is_(None)) | (func.upper(SortieFonds.statut) == "VALIDE"),
        )
    )
    consomme = float(consomme_res.scalar_one() or 0)

    en_attente_res = await db.execute(
        select(func.coalesce(func.sum(func.coalesce(Requisition.montant_total, 0)), 0))
        .select_from(Requisition)
        .where(
            Requisition.service_id == service_id,
            Requisition.organisation_id == tenant_id,
            func.upper(Requisition.status).in_(PENDING_REQUISITION_STATUSES),
        )
    )
    en_attente = float(en_attente_res.scalar_one() or 0)

    return {
        "annee": exercice.annee,
        "total": total_depenses,
        "total_depenses": total_depenses,
        "total_recettes": total_recettes,
        "consomme": consomme,
        "en_attente": en_attente,
        "disponible": total_depenses - (consomme + en_attente),
    }


@router.get("/audit-logs", response_model=list[BudgetAuditLogOut])
async def list_budget_audit_logs(
    annee: int | None = None,
    limit: int = 200,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[BudgetAuditLogOut]:
    query = select(BudgetAuditLog).where(BudgetAuditLog.organisation_id == tenant_id)
    if annee is not None:
        ex_res = await db.execute(
            select(BudgetExercice).where(
                BudgetExercice.annee == annee,
                BudgetExercice.organisation_id == tenant_id,
            )
        )
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
            budget_poste_id=log.budget_poste_id,
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


@router.get("/postes", response_model=BudgetPostesResponse)
async def list_budget_postes(
    annee: int | None = None,
    type: str | None = None,
    active: bool | None = None,
    service_id: int | None = None,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> BudgetPostesResponse:
    response = await list_budget_lines(
        annee=annee,
        type=type,
        active=active,
        service_id=service_id,
        user=user,
        tenant_id=tenant_id,
        db=db,
    )
    return BudgetPostesResponse(annee=response.annee, statut=response.statut, postes=response.lignes)


@router.get("/postes/tree", response_model=BudgetPostesTreeResponse)
async def list_budget_postes_tree(
    annee: int | None = None,
    type: str | None = None,
    active: bool | None = None,
    service_id: int | None = None,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> BudgetPostesTreeResponse:
    response = await list_budget_lines_tree(
        annee=annee,
        type=type,
        active=active,
        service_id=service_id,
        user=user,
        tenant_id=tenant_id,
        db=db,
    )
    return BudgetPostesTreeResponse(annee=response.annee, statut=response.statut, postes=response.lignes)


@router.get("/lines", response_model=BudgetLinesResponse)
async def list_budget_lines(
    annee: int | None = None,
    type: str | None = None,
    active: bool | None = None,
    service_id: int | None = None,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> BudgetLinesResponse:
    if annee is None:
        result = await db.execute(
            select(func.max(BudgetExercice.annee)).where(BudgetExercice.organisation_id == tenant_id)
        )
        annee = result.scalar_one_or_none()

    if annee is None:
        return BudgetLinesResponse(annee=None, statut=None, lignes=[])

    exercice_result = await db.execute(
        select(BudgetExercice).where(
            BudgetExercice.annee == annee,
            BudgetExercice.organisation_id == tenant_id,
        )
    )
    exercice = exercice_result.scalar_one_or_none()
    if exercice is None:
        return BudgetLinesResponse(annee=annee, statut=None, lignes=[])

    query = select(BudgetPoste).where(
        BudgetPoste.exercice_id == exercice.id,
        BudgetPoste.organisation_id == tenant_id,
        BudgetPoste.is_deleted.is_(False),
    )
    if type:
        query = query.where(BudgetPoste.type == type.upper())
    if active is not None:
        query = query.where(BudgetPoste.active == active)
    query = query.order_by(BudgetPoste.code)

    lines_result = await db.execute(query)
    lines = lines_result.scalars().all()

    service_sorties_map: dict[int, Decimal] = {}
    service_recettes_map: dict[int, Decimal] = {}
    if service_id is not None:
        service_res = await db.execute(
            select(Service).where(
                Service.id == service_id,
                Service.organisation_id == tenant_id,
            )
        )
        if service_res.scalar_one_or_none() is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service non trouvé")

        sorties_res = await db.execute(
            select(
                SortieFonds.budget_poste_id,
                func.coalesce(func.sum(func.coalesce(SortieFonds.montant_paye, 0)), 0),
            )
            .where(
                SortieFonds.service_id == service_id,
                SortieFonds.organisation_id == tenant_id,
                (SortieFonds.statut.is_(None)) | (func.upper(SortieFonds.statut) == "VALIDE"),
            )
            .group_by(SortieFonds.budget_poste_id)
        )
        service_sorties_map = {int(row[0]): Decimal(row[1] or 0) for row in sorties_res.all() if row[0]}

        recettes_res = await db.execute(
            select(
                Encaissement.budget_poste_id,
                func.coalesce(func.sum(func.coalesce(Encaissement.montant_paye, 0)), 0),
            )
            .where(
                Encaissement.service_id == service_id,
                Encaissement.organisation_id == tenant_id,
                Encaissement.est_proforma.is_(False),
            )
            .group_by(Encaissement.budget_poste_id)
        )
        service_recettes_map = {int(row[0]): Decimal(row[1] or 0) for row in recettes_res.all() if row[0]}

    summaries: list[BudgetLineSummary] = []
    for line in lines:
        montant_prevu = Decimal(line.montant_prevu or 0)
        montant_engage = Decimal(line.montant_engage or 0)
        montant_paye = Decimal(line.montant_paye or 0)
        if service_id is not None:
            if (line.type or "").upper() == "DEPENSE":
                montant_paye = service_sorties_map.get(line.id, Decimal("0"))
                montant_engage = Decimal("0")
            else:
                montant_engage = service_recettes_map.get(line.id, Decimal("0"))
                montant_paye = montant_engage
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
                parent_id=line.parent_id,
                type=line.type,
                active=line.active,
                is_global=line.is_global,
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


@router.get("/lines/autorisees", response_model=BudgetLinesResponse)
async def list_allowed_budget_lines(
    annee: int | None = None,
    type: str | None = None,
    active: bool | None = None,
    service_id: int | None = None,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> BudgetLinesResponse:
    # Même périmètre que la création de réquisition : qui peut porter une
    # réquisition sur un service doit pouvoir en lister les postes autorisés.
    unrestricted = (user.role or "").lower() in {"admin", "super_admin"} or await can_view_all_services(db, user)
    if not unrestricted:
        service_ids = await get_user_service_ids(db, user)
        if not service_ids:
            return BudgetLinesResponse(annee=None, statut=None, lignes=[])
        if service_id is None:
            if len(service_ids) == 1:
                service_id = service_ids[0]
            else:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="service_id requis")
        if service_id not in service_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès interdit")

    if unrestricted and service_id is None:
        return await list_budget_lines(
            annee=annee,
            type=type,
            active=active,
            service_id=None,
            user=user,
            tenant_id=tenant_id,
            db=db,
        )

    if annee is None:
        result = await db.execute(
            select(func.max(BudgetExercice.annee)).where(BudgetExercice.organisation_id == tenant_id)
        )
        annee = result.scalar_one_or_none()

    if annee is None:
        return BudgetLinesResponse(annee=None, statut=None, lignes=[])

    exercice_result = await db.execute(
        select(BudgetExercice).where(
            BudgetExercice.annee == annee,
            BudgetExercice.organisation_id == tenant_id,
        )
    )
    exercice = exercice_result.scalar_one_or_none()
    if exercice is None:
        return BudgetLinesResponse(annee=annee, statut=None, lignes=[])

    query = (
        select(BudgetPoste)
        .join(ServiceRubrique, ServiceRubrique.budget_poste_id == BudgetPoste.id)
        .where(
            BudgetPoste.exercice_id == exercice.id,
            BudgetPoste.organisation_id == tenant_id,
            BudgetPoste.is_deleted.is_(False),
            ServiceRubrique.service_id == service_id,
        )
    )
    if type:
        query = query.where(BudgetPoste.type == type.upper())
    if active is not None:
        query = query.where(BudgetPoste.active == active)
    query = query.order_by(BudgetPoste.code)

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
        pourcentage = (base_consomme / montant_prevu) * Decimal("100") if montant_prevu > 0 else Decimal("0")

        summaries.append(
            BudgetLineSummary(
                id=line.id,
                code=line.code,
                libelle=line.libelle,
                parent_code=line.parent_code,
                parent_id=line.parent_id,
                type=line.type,
                active=line.active,
                is_global=line.is_global,
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


@router.get("/lines/tree", response_model=BudgetLinesTreeResponse)
async def list_budget_lines_tree(
    annee: int | None = None,
    type: str | None = None,
    active: bool | None = None,
    service_id: int | None = None,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> BudgetLinesTreeResponse:
    if annee is None:
        result = await db.execute(
            select(func.max(BudgetExercice.annee)).where(BudgetExercice.organisation_id == tenant_id)
        )
        annee = result.scalar_one_or_none()

    if annee is None:
        return BudgetLinesTreeResponse(annee=None, statut=None, lignes=[])

    exercice_result = await db.execute(
        select(BudgetExercice.id, BudgetExercice.statut).where(
            BudgetExercice.annee == annee,
            BudgetExercice.organisation_id == tenant_id,
        )
    )
    exercice_row = exercice_result.one_or_none()
    if exercice_row is None:
        return BudgetLinesTreeResponse(annee=annee, statut=None, lignes=[])

    exercice_id, exercice_statut = exercice_row

    query = select(
        BudgetPoste.id,
        BudgetPoste.exercice_id,
        BudgetPoste.code,
        BudgetPoste.libelle,
        BudgetPoste.parent_code,
        BudgetPoste.parent_id,
        BudgetPoste.type,
        BudgetPoste.active,
        BudgetPoste.is_global,
        BudgetPoste.montant_prevu,
        BudgetPoste.montant_engage,
        BudgetPoste.montant_paye,
    ).where(
        BudgetPoste.exercice_id == exercice_id,
        BudgetPoste.organisation_id == tenant_id,
        BudgetPoste.is_deleted.is_(False),
    )
    if type:
        query = query.where(BudgetPoste.type == type.upper())
    if active is not None:
        query = query.where(BudgetPoste.active == active)
    query = query.order_by(BudgetPoste.code)

    lines_result = await db.execute(query)
    lines = [
        _BudgetTreeLine(
            id=row.id,
            exercice_id=row.exercice_id,
            code=row.code,
            libelle=row.libelle,
            parent_code=row.parent_code,
            parent_id=row.parent_id,
            type=row.type,
            active=row.active,
            is_global=row.is_global,
            montant_prevu=Decimal(row.montant_prevu or 0),
            montant_engage=Decimal(row.montant_engage or 0),
            montant_paye=Decimal(row.montant_paye or 0),
        )
        for row in lines_result.all()
    ]

    if service_id is not None:
        service_res = await db.execute(
            select(Service).where(
                Service.id == service_id,
                Service.organisation_id == tenant_id,
            )
        )
        if service_res.scalar_one_or_none() is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service non trouvé")

        sorties_res = await db.execute(
            select(
                SortieFonds.budget_poste_id,
                func.coalesce(func.sum(func.coalesce(SortieFonds.montant_paye, 0)), 0),
            )
            .where(
                SortieFonds.service_id == service_id,
                SortieFonds.organisation_id == tenant_id,
                (SortieFonds.statut.is_(None)) | (func.upper(SortieFonds.statut) == "VALIDE"),
            )
            .group_by(SortieFonds.budget_poste_id)
        )
        service_sorties_map = {int(row[0]): Decimal(row[1] or 0) for row in sorties_res.all() if row[0]}

        recettes_res = await db.execute(
            select(
                Encaissement.budget_poste_id,
                func.coalesce(func.sum(func.coalesce(Encaissement.montant_paye, 0)), 0),
            )
            .where(
                Encaissement.service_id == service_id,
                Encaissement.organisation_id == tenant_id,
                Encaissement.est_proforma.is_(False),
            )
            .group_by(Encaissement.budget_poste_id)
        )
        service_recettes_map = {int(row[0]): Decimal(row[1] or 0) for row in recettes_res.all() if row[0]}

        for line in lines:
            if (line.type or "").upper() == "DEPENSE":
                line.montant_paye = service_sorties_map.get(line.id, Decimal("0"))
                line.montant_engage = Decimal("0")
            else:
                line.montant_engage = service_recettes_map.get(line.id, Decimal("0"))
                line.montant_paye = line.montant_engage

    roots = _build_tree_nodes(lines)
    for root in roots:
        _compute_tree_totals(root)

    tree = [_node_to_tree_schema(root) for root in roots]

    return BudgetLinesTreeResponse(
        annee=annee,
        statut=exercice_statut.value if exercice_statut else None,
        lignes=tree,
    )


@router.post("/lines", response_model=BudgetLineSummary, status_code=status.HTTP_201_CREATED)
async def create_budget_line(
    payload: BudgetLineCreate,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> BudgetLineSummary:
    is_super_admin = (user.role or "").lower() == "super_admin"
    if payload.is_global and not is_super_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Réservé au super admin")
    exercice = await _get_or_create_budget_exercice(
        db,
        organisation_id=tenant_id,
        annee=payload.annee,
        statut=StatutBudget.BROUILLON,
    )
    if exercice.statut == StatutBudget.CLOTURE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Exercice clôturé")
    if await _is_locked_exercise(exercice.id, db, tenant_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Exercice verrouillé (année antérieure)")
    if payload.montant_prevu is not None and payload.montant_prevu < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le montant prévu doit être positif")

    parent_id, parent_code = await _resolve_parent_link(
        db,
        exercice_id=exercice.id,
        parent_id=payload.parent_id,
        parent_code=payload.parent_code,
        organisation_id=tenant_id,
    )

    normalized_code = _normalize_budget_code(payload.code)
    line = BudgetPoste(
        organisation_id=tenant_id,
        exercice_id=exercice.id,
        code=normalized_code or payload.code.strip(),
        libelle=payload.libelle.strip(),
        parent_code=parent_code,
        parent_id=parent_id,
        type=payload.type.strip().upper(),
        active=payload.active,
        is_global=payload.is_global,
        montant_prevu=payload.montant_prevu,
    )
    db.add(line)
    await db.flush()
    await _refresh_parent_totals(db, parent_id)
    await db.commit()
    await db.refresh(line)
    await _log_budget_change(
        db,
        exercice_id=exercice.id,
        budget_poste_id=line.id,
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
        parent_id=line.parent_id,
        type=line.type,
        active=line.active,
        is_global=line.is_global,
        montant_prevu=montant_prevu,
        montant_engage=montant_engage,
        montant_paye=montant_paye,
        montant_disponible=disponible,
        pourcentage_consomme=pourcentage,
    )


@router.post("/postes", response_model=BudgetPosteSummary, status_code=status.HTTP_201_CREATED)
async def create_budget_poste(
    payload: BudgetPosteCreate,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> BudgetPosteSummary:
    return await create_budget_line(payload=payload, user=user, tenant_id=tenant_id, db=db)


@router.post("/postes/import", response_model=BudgetPosteImportResponse)
async def import_budget_postes(
    payload: BudgetPosteImportRequest,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> BudgetPosteImportResponse:
    total_rows = len(payload.rows)
    if not payload.rows:
        return BudgetPosteImportResponse(
            success=False,
            imported=0,
            created=0,
            skipped=0,
            total_lignes=0,
            error_count=0,
            errors=[],
            message="Aucune ligne à importer",
        )

    conflict_mode = payload.conflict_mode or "update_existing"
    if conflict_mode not in {"add_only", "update_existing", "replace_exercise"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mode de conflit invalide.")
    if conflict_mode == "replace_exercise" and payload.replace_confirmation != REPLACE_BUDGET_CONFIRMATION:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Confirmation requise: {REPLACE_BUDGET_CONFIRMATION}",
        )

    type_value = (payload.type or "").strip().upper()
    if type_value not in {"DEPENSE", "RECETTE"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Type invalide (DEPENSE/RECETTE).")

    prepared_rows: list[dict] = []
    errors: list[dict] = []
    seen_codes: dict[str, int] = {}
    skipped_blank_rows = 0
    for idx, row in enumerate(payload.rows):
        line_no = idx + 2
        code = _normalize_budget_code(row.code) if row.code else None
        libelle = (row.libelle or "").strip()
        parent_code_value = _normalize_budget_code(row.parent_code) if row.parent_code else None
        plafond_value = row.plafond
        plafond_is_empty = plafond_value is None or str(plafond_value).strip() == ""
        plafond_decimal = Decimal("0")
        if not plafond_is_empty:
            try:
                plafond_decimal = Decimal(str(plafond_value))
            except Exception:
                errors.append({"ligne": line_no, "code": code, "champ": "plafond", "message": "Plafond invalide"})
                plafond_decimal = Decimal("0")

        is_empty_row = not code and not libelle and not parent_code_value and (plafond_is_empty or plafond_decimal == 0)
        if is_empty_row:
            skipped_blank_rows += 1
            continue
        if not code:
            errors.append({"ligne": line_no, "code": code, "champ": "code", "message": "Code obligatoire"})
        if not libelle:
            errors.append({"ligne": line_no, "code": code, "champ": "libelle", "message": "Libellé obligatoire"})
        if plafond_decimal < 0:
            errors.append({"ligne": line_no, "code": code, "champ": "plafond", "message": "Plafond négatif interdit"})
        code_key = (code or "").lower()
        if code_key:
            if code_key in seen_codes:
                errors.append(
                    {
                        "ligne": line_no,
                        "code": code,
                        "champ": "code",
                        "message": f"Code dupliqué dans le fichier (première occurrence ligne {seen_codes[code_key]})",
                    }
                )
            else:
                seen_codes[code_key] = line_no
        if code and libelle and plafond_decimal >= 0:
            prepared_rows.append(
                {
                    "line_no": line_no,
                    "code": code,
                    "libelle": libelle,
                    "parent_id": row.parent_id,
                    "parent_code": parent_code_value,
                    "plafond": plafond_decimal,
                }
            )

    if errors:
        await db.rollback()
        return BudgetPosteImportResponse(
            success=False,
            imported=0,
            created=0,
            updated=0,
            skipped=skipped_blank_rows,
            error_count=len(errors),
            total_lignes=total_rows,
            errors=errors,
            message=f"{len(errors)} erreur(s) détectée(s). Aucun poste n'a été importé.",
        )

    exercice = await _get_or_create_budget_exercice(
        db,
        organisation_id=tenant_id,
        annee=payload.annee,
        statut=StatutBudget.BROUILLON,
    )

    existing_res = await db.execute(
        select(BudgetPoste).where(
            BudgetPoste.exercice_id == exercice.id,
            BudgetPoste.organisation_id == tenant_id,
            BudgetPoste.is_deleted.is_(False),
        )
    )
    existing_lines = existing_res.scalars().all()
    existing_by_code = {
        (_normalize_budget_code(line.code) or "").lower(): line
        for line in existing_lines
        if (_normalize_budget_code(line.code) or "").lower()
    }

    imported_count = 0
    updated_count = 0
    skipped_count = skipped_blank_rows
    backup_path: str | None = None

    try:
        if conflict_mode == "replace_exercise":
            poste_ids = [line.id for line in existing_lines]
            await _assert_budget_replace_has_no_operational_refs(
                db,
                organisation_id=tenant_id,
                poste_ids=poste_ids,
            )
            backup_path = await _write_budget_replace_backup(db, organisation_id=tenant_id, exercice=exercice)
            await _delete_budget_exercise_poste_settings(
                db,
                organisation_id=tenant_id,
                exercice_id=exercice.id,
                poste_ids=poste_ids,
            )
            await db.flush()
            existing_by_code = {}

        for row in prepared_rows:
            code = row["code"]
            libelle = row["libelle"]
            parent_code_value = row["parent_code"]
            existing = existing_by_code.get(code.lower())
            if existing is not None and conflict_mode == "add_only":
                skipped_count += 1
                continue

            if row["parent_id"] is not None:
                parent_id, parent_code = await _resolve_parent_link(
                    db,
                    exercice_id=exercice.id,
                    parent_id=row["parent_id"],
                    parent_code=parent_code_value,
                    organisation_id=tenant_id,
                )
            else:
                if not parent_code_value:
                    code_parts = _split_budget_code(code)
                    if len(code_parts) > 1:
                        parent_code_value = ".".join(code_parts[:-1])
                parent_id, parent_code = await _ensure_budget_parent_chain(
                    db,
                    exercice_id=exercice.id,
                    organisation_id=tenant_id,
                    type_value=type_value,
                    parent_code=parent_code_value or "",
                    existing_by_code=existing_by_code,
                )

            if existing is not None:
                existing.libelle = libelle
                existing.montant_prevu = row["plafond"]
                existing.type = type_value
                existing.parent_id = parent_id
                existing.parent_code = parent_code
                if existing.is_deleted:
                    existing.is_deleted = False
                    existing.deleted_at = None
                    existing.deleted_by = None
                await db.flush()
                updated_count += 1
                continue

            poste = BudgetPoste(
                organisation_id=tenant_id,
                exercice_id=exercice.id,
                code=code,
                libelle=libelle,
                parent_id=parent_id,
                parent_code=parent_code,
                type=type_value,
                active=True,
                montant_prevu=row["plafond"],
                montant_engage=0,
                montant_paye=0,
            )
            db.add(poste)
            await db.flush()
            existing_by_code[code.lower()] = poste
            imported_count += 1

        lines_res = await db.execute(
            select(BudgetPoste).where(
                BudgetPoste.exercice_id == exercice.id,
                BudgetPoste.organisation_id == tenant_id,
                BudgetPoste.is_deleted.is_(False),
            )
        )
        all_lines = lines_res.scalars().all()
        code_map = {(_normalize_budget_code(line.code) or "").lower(): line for line in all_lines}
        for line in all_lines:
            parent_code = _normalize_budget_code(line.parent_code)
            if not parent_code or line.parent_id:
                continue
            parent = code_map.get(parent_code.lower())
            if parent and parent.id != line.id:
                line.parent_id = parent.id

        parent_ids_res = await db.execute(
            select(BudgetPoste.parent_id)
            .where(
                BudgetPoste.exercice_id == exercice.id,
                BudgetPoste.organisation_id == tenant_id,
                BudgetPoste.is_deleted.is_(False),
                BudgetPoste.parent_id.is_not(None),
            )
            .distinct()
        )
        for parent_id in parent_ids_res.scalars().all():
            await _refresh_parent_totals(db, parent_id)

        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise

    message = f"{imported_count} poste(s) créé(s), {updated_count} mis à jour, {skipped_count} ignoré(s)."
    return BudgetPosteImportResponse(
        success=True,
        imported=imported_count + updated_count,
        created=imported_count,
        updated=updated_count,
        skipped=skipped_count,
        error_count=0,
        total_lignes=total_rows,
        errors=[],
        backup_path=backup_path,
        message=message,
    )


@router.put("/lines/{line_id}", response_model=BudgetLineSummary)
async def update_budget_line(
    line_id: int,
    payload: BudgetLineUpdate,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> BudgetLineSummary:
    result = await db.execute(
        select(BudgetPoste).where(
            BudgetPoste.id == line_id,
            BudgetPoste.organisation_id == tenant_id,
            BudgetPoste.is_deleted.is_(False),
        )
    )
    line = result.scalar_one_or_none()
    if line is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ligne budgétaire introuvable")
    is_super_admin = (user.role or "").lower() == "super_admin"
    if line.is_global and not is_super_admin:
        allowed_fields = {"montant_prevu"}
        if any(field not in allowed_fields for field in payload.model_fields_set):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Réservé au super admin")
    ex_res = await db.execute(
        select(BudgetExercice).where(
            BudgetExercice.id == line.exercice_id,
            BudgetExercice.organisation_id == tenant_id,
        )
    )
    exercice = ex_res.scalar_one_or_none()
    if exercice and exercice.statut == StatutBudget.CLOTURE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Exercice clôturé")
    if exercice and await _is_locked_exercise(exercice.id, db, tenant_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Exercice verrouillé (année antérieure)")

    linked_requisitions = await db.execute(
        select(LigneRequisition.id).where(LigneRequisition.budget_poste_id == line.id).limit(1)
    )
    if linked_requisitions.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action impossible : des réquisitions sont liées à cette rubrique",
        )
    linked_enc = await db.execute(
        select(Encaissement.id).where(Encaissement.budget_poste_id == line.id).limit(1)
    )
    if linked_enc.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action impossible : des encaissements sont liés à cette rubrique",
        )
    linked_sorties = await db.execute(
        select(SortieFonds.id).where(SortieFonds.budget_poste_id == line.id).limit(1)
    )
    if linked_sorties.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Action impossible : des sorties de fonds sont liées à cette rubrique",
        )

    if payload.code is not None:
        line.code = _normalize_budget_code(payload.code) or payload.code.strip()
    if payload.libelle is not None:
        line.libelle = payload.libelle.strip()
    if payload.type is not None:
        line.type = payload.type.strip().upper()
    old_parent_id = line.parent_id
    if "parent_id" in payload.model_fields_set or "parent_code" in payload.model_fields_set:
        if payload.parent_id is not None and payload.parent_id == line.id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rubrique parente invalide")
        parent_id, parent_code = await _resolve_parent_link(
            db,
            exercice_id=line.exercice_id,
            parent_id=payload.parent_id,
            parent_code=payload.parent_code,
            organisation_id=tenant_id,
        )
        line.parent_id = parent_id
        line.parent_code = parent_code
    if payload.active is not None:
        line.active = payload.active
    if payload.is_global is not None:
        if not is_super_admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Réservé au super admin")
        line.is_global = payload.is_global
    if payload.montant_prevu is not None:
        if await _has_children(db, line.id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Le montant d'une rubrique parente est calculé automatiquement.",
            )
        old_prevu = Decimal(line.montant_prevu or 0)
        if payload.montant_prevu < 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le montant prévu doit être positif")
        line.montant_prevu = payload.montant_prevu
        new_prevu = Decimal(payload.montant_prevu or 0)
        if new_prevu != old_prevu:
            await _log_budget_change(
                db,
                exercice_id=line.exercice_id,
                budget_poste_id=line.id,
                action="update",
                field_name="montant_prevu",
                old_value=old_prevu,
                new_value=new_prevu,
                user=user,
            )

    await db.flush()
    if payload.montant_prevu is not None or line.parent_id != old_parent_id:
        await _refresh_parent_totals(db, line.parent_id)
        if old_parent_id and old_parent_id != line.parent_id:
            await _refresh_parent_totals(db, old_parent_id)
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
        parent_id=line.parent_id,
        type=line.type,
        active=line.active,
        is_global=line.is_global,
        montant_prevu=montant_prevu,
        montant_engage=montant_engage,
        montant_paye=montant_paye,
        montant_disponible=disponible,
        pourcentage_consomme=pourcentage,
    )


@router.put("/postes/{poste_id}", response_model=BudgetPosteSummary)
async def update_budget_poste(
    poste_id: int,
    payload: BudgetPosteUpdate,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> BudgetPosteSummary:
    return await update_budget_line(line_id=poste_id, payload=payload, user=user, tenant_id=tenant_id, db=db)


@router.delete("/lines/{line_id}")
async def delete_budget_line(
    line_id: int,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(BudgetPoste).where(
            BudgetPoste.id == line_id,
            BudgetPoste.organisation_id == tenant_id,
        )
    )
    line = result.scalar_one_or_none()
    if line is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ligne budgétaire introuvable")
    is_super_admin = (user.role or "").lower() == "super_admin"
    if line.is_global and not is_super_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Réservé au super admin")
    if await _has_children(db, line.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Suppression impossible : la rubrique possède des sous-rubriques.",
        )
    ex_res = await db.execute(
        select(BudgetExercice).where(
            BudgetExercice.id == line.exercice_id,
            BudgetExercice.organisation_id == tenant_id,
        )
    )
    exercice = ex_res.scalar_one_or_none()
    if exercice and exercice.statut == StatutBudget.CLOTURE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Exercice clôturé")
    if exercice and await _is_locked_exercise(exercice.id, db, tenant_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Exercice verrouillé (année antérieure)")
    line.is_deleted = True
    line.deleted_at = datetime.now(timezone.utc)
    line.deleted_by = user.id
    await db.flush()
    await _refresh_parent_totals(db, line.parent_id)
    await _log_budget_change(
        db,
        exercice_id=line.exercice_id,
        budget_poste_id=line.id,
        action="delete",
        field_name="ligne",
        old_value=None,
        new_value=None,
        user=user,
    )
    await db.commit()
    return {"ok": True}


@router.delete("/postes/{poste_id}")
async def delete_budget_poste(
    poste_id: int,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await delete_budget_line(line_id=poste_id, user=user, tenant_id=tenant_id, db=db)


@router.post("/lines/{line_id}/restore")
async def restore_budget_line(
    line_id: int,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(BudgetPoste).where(
            BudgetPoste.id == line_id,
            BudgetPoste.organisation_id == tenant_id,
            BudgetPoste.is_deleted.is_(True),
        )
    )
    line = result.scalar_one_or_none()
    if line is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ligne budgétaire introuvable")
    ex_res = await db.execute(
        select(BudgetExercice).where(
            BudgetExercice.id == line.exercice_id,
            BudgetExercice.organisation_id == tenant_id,
        )
    )
    exercice = ex_res.scalar_one_or_none()
    if exercice and exercice.statut == StatutBudget.CLOTURE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Exercice clôturé")
    if exercice and await _is_locked_exercise(exercice.id, db, tenant_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Exercice verrouillé (année antérieure)")

    line.is_deleted = False
    line.deleted_at = None
    line.deleted_by = None
    await db.flush()
    await _refresh_parent_totals(db, line.parent_id)
    await _log_budget_change(
        db,
        exercice_id=line.exercice_id,
        budget_poste_id=line.id,
        action="restore",
        field_name="ligne",
        old_value=None,
        new_value=None,
        user=user,
    )
    await db.commit()
    return {"ok": True}


@router.post("/postes/{poste_id}/restore")
async def restore_budget_poste(
    poste_id: int,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await restore_budget_line(line_id=poste_id, user=user, tenant_id=tenant_id, db=db)
