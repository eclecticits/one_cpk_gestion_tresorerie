from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
from typing import Any
import unicodedata

import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.chart import BarChart, DoughnutChart, Reference
from openpyxl.formatting.rule import DataBarRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import func, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, has_permission
from app.db.session import get_db
from app.models.encaissement import Encaissement
from app.models.expert_comptable import ExpertComptable
from app.models.organisation import Organisation
from app.models.budget import BudgetExercice, BudgetPoste
from app.models.ligne_requisition import LigneRequisition
from app.models.requisition import Requisition
from app.models.service import Service
from app.models.service_rubrique import ServiceRubrique
from app.models.sortie_fonds import SortieFonds
from app.models.user import User

router = APIRouter()


async def require_expert_admin(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    role = (user.role or "").lower()
    if role == "super_admin":
        return user
    if role == "admin" and user.organisation_id:
        org_res = await db.execute(select(Organisation.slug).where(Organisation.id == user.organisation_id))
        slug = (org_res.scalar_one_or_none() or "").lower()
        if slug == "cn":
            return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Action réservée au Conseil National (CN).",
    )

REQUISITION_STATUTS_VALIDES = ("APPROUVEE", "PAYEE")


def _strip_accents(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))


def _normalize_statut_professionnel(value: str | None) -> str | None:
    if not value:
        return None
    trimmed = value.strip()
    compact = trimmed.replace("_", " ").replace("-", " ")
    compact = " ".join(compact.split())
    normalized = _strip_accents(compact).lower()
    mapping = {
        "en cabinet": "En Cabinet",
        "independant": "Indépendant",
        "salarie": "Salarié",
        "cabinet": "Cabinet",
    }
    return mapping.get(normalized, trimmed)


def _statut_professionnel_variants(value: str) -> list[str]:
    canonical = _normalize_statut_professionnel(value)
    if not canonical:
        return []
    variants = {
        "En Cabinet": [
            "En Cabinet",
            "En cabinet",
            "en cabinet",
            "EN CABINET",
            "en_cabinet",
            "En_Cabinet",
            "en-cabinet",
            "En-Cabinet",
        ],
        "Indépendant": [
            "Indépendant",
            "indépendant",
            "Independant",
            "independant",
            "INDEPENDANT",
        ],
        "Salarié": [
            "Salarié",
            "salarié",
            "Salarie",
            "salarie",
            "SALARIE",
        ],
        "Cabinet": [
            "Cabinet",
            "cabinet",
            "CABINET",
        ],
    }
    return variants.get(canonical, [canonical])

def _parse_datetime(value: str | None, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if end_of_day and len(value) <= 10:
        dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    return dt


def _excel_response(filename: str, wb: Workbook) -> StreamingResponse:
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _round_money(value: Decimal | float | int | None) -> Decimal:
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _format_mode_paiement(value: str | None) -> str:
    if not value:
        return ""
    val = value.strip().lower()
    mapping = {
        "cash": "Cash",
        "mobile_money": "Mobile Money",
        "virement": "Opération bancaire",
        "card": "Carte (Visa)",
        "cheque": "Chèque",
    }
    return mapping.get(val, value)


def _autosize_columns(ws) -> None:
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            value = cell.value
            if value is None:
                continue
            max_len = max(max_len, len(str(value)))
        ws.column_dimensions[col_letter].width = min(max_len + 2, 60)


# ── Palette & styles partagés (repris du modèle « budget ») ────────────────────
# Promus au niveau module pour être réutilisés par tous les exports sans être
# redéfinis (une seule source de vérité pour la charte visuelle).
GREEN = "FF065F46"
GREEN_DARK = "FF064E3B"
GREEN_LIGHT = "FFD1FAE5"
TEAL_SOFT = "FFCCFBF1"
AMBER_SOFT = "FFFEF3C7"
RED_SOFT = "FFFEE2E2"
SLATE = "FF334155"
SLATE_LIGHT = "FFF8FAFC"
LEVEL_FILLS = ["FF6EE7B7", "FFA7F3D0", "FFC6F6DF", "FFD1FAE5"]
header_font = Font(bold=True, color="FFFFFFFF", size=10)
header_fill = PatternFill(fill_type="solid", fgColor=GREEN)
subheader_fill = PatternFill(fill_type="solid", fgColor=GREEN_LIGHT)
muted_fill = PatternFill(fill_type="solid", fgColor=SLATE_LIGHT)
white_fill = PatternFill(fill_type="solid", fgColor="FFFFFFFF")
center = Alignment(horizontal="center", vertical="center", wrap_text=True)
left = Alignment(horizontal="left", vertical="center", wrap_text=True)
right = Alignment(horizontal="right", vertical="center")
thin = Side(style="thin", color="FFD1D5DB")
border = Border(left=thin, right=thin, top=thin, bottom=thin)
MONEY = "#,##0.00"
PCT = '0.0"%"'


def _write_banner(ws, title: str, subtitle: str | None, ncols: int) -> None:
    """Bandeau titre vert (ligne 1) + sous-titre italique (ligne 2), fusionnés
    sur les ``ncols`` premières colonnes. À appeler APRÈS ``_autosize_columns``
    pour ne pas gonfler la largeur de la colonne A avec le texte du titre."""
    last_col = get_column_letter(max(ncols, 1))
    ws.merge_cells(f"A1:{last_col}1")
    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=16, color="FFFFFFFF")
    ws["A1"].fill = header_fill
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28
    if subtitle:
        ws.merge_cells(f"A2:{last_col}2")
        ws["A2"] = subtitle
        ws["A2"].font = Font(italic=True, color=SLATE)
        ws["A2"].alignment = Alignment(horizontal="center")
        ws.row_dimensions[2].height = 20


def _build_list_sheet(
    ws,
    *,
    title: str,
    subtitle: str | None,
    headers: list[str],
    data_rows: list[list[Any]],
    money_cols: tuple[int, ...] = (),
    total_values: dict[int, Any] | None = None,
    ordinal: bool = True,
) -> int:
    """Construit une feuille « liste » au style budget : bandeau titre, en-tête
    vert, lignes zébrées, formats monétaires, ligne TOTAL, en-tête figé, filtre
    automatique et largeurs auto. Renvoie l'index de la ligne TOTAL.

    Si ``ordinal`` (défaut), une colonne « N° » (1, 2, 3…) est ajoutée en tête pour
    pouvoir référencer chaque ligne dans les rapports ; les index monétaires et de
    total sont décalés automatiquement (+1)."""
    if ordinal:
        headers = ["N°", *headers]
        data_rows = [[idx + 1, *row] for idx, row in enumerate(data_rows)]
        money_cols = tuple(c + 1 for c in money_cols)
        if total_values is not None:
            total_values = {k + 1: v for k, v in total_values.items()}
    ncols = len(headers)
    last_col_letter = get_column_letter(max(ncols, 1))
    money = set(money_cols)
    HEADER_ROW = 4
    first_data = HEADER_ROW + 1

    # En-tête stylé (vert + blanc gras)
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=HEADER_ROW, column=i, value=h)
        c.font = header_font
        c.fill = header_fill
        c.alignment = center
        c.border = border
    ws.row_dimensions[HEADER_ROW].height = 24

    # Lignes de données zébrées
    for ridx, row_values in enumerate(data_rows):
        r = first_data + ridx
        zebra = ridx % 2 == 1
        for i, val in enumerate(row_values, start=1):
            c = ws.cell(row=r, column=i, value=val)
            c.border = border
            if i in money:
                c.number_format = MONEY
                c.alignment = right
            elif ordinal and i == 1:
                c.alignment = center
            else:
                c.alignment = left
            if zebra:
                c.fill = muted_fill

    last_data = HEADER_ROW + len(data_rows)
    total_row = last_data + 1

    # Ligne TOTAL (bandeau vert, gras blanc)
    if total_values is not None:
        ws.cell(row=total_row, column=1, value="TOTAL")
        for col_idx, value in total_values.items():
            ws.cell(row=total_row, column=col_idx, value=value)
        for col in range(1, ncols + 1):
            c = ws.cell(row=total_row, column=col)
            c.font = Font(bold=True, color="FFFFFFFF")
            c.fill = header_fill
            c.border = border
            c.alignment = right if col in money else center
            if col in money:
                c.number_format = MONEY

    # Largeurs auto AVANT le bandeau titre (le titre ne doit pas élargir A)
    _autosize_columns(ws)
    _write_banner(ws, title, subtitle, ncols)

    ws.freeze_panes = f"A{first_data}"
    ws.auto_filter.ref = f"A{HEADER_ROW}:{last_col_letter}{max(last_data, HEADER_ROW)}"
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = GREEN
    return total_row


def _write_synthese_block(
    ws,
    start_row: int,
    block_title: str,
    col_headers: list[str],
    rows: list[list[Any]],
    money_cols: tuple[int, ...] = (),
) -> tuple[int, int, int, int]:
    """Écrit un bloc « titre + en-tête + lignes » stylé sur la feuille Synthèse.
    Renvoie ``(header_row, first_data_row, last_data_row, next_free_row)``."""
    money = set(money_cols)
    ncols = len(col_headers)
    tcell = ws.cell(row=start_row, column=1, value=block_title)
    tcell.font = Font(bold=True, color=GREEN_DARK, size=11)
    for col in range(1, ncols + 1):
        c = ws.cell(row=start_row, column=col)
        c.fill = subheader_fill
        c.border = border
    header_row = start_row + 1
    for i, h in enumerate(col_headers, start=1):
        c = ws.cell(row=header_row, column=i, value=h)
        c.font = header_font
        c.fill = header_fill
        c.alignment = center
        c.border = border
    first = header_row + 1
    for ridx, row_values in enumerate(rows):
        r = first + ridx
        for i, val in enumerate(row_values, start=1):
            c = ws.cell(row=r, column=i, value=val)
            c.border = border
            if i in money:
                c.number_format = MONEY
                c.alignment = right
            else:
                c.alignment = left if i == 1 else center
            c.fill = muted_fill if ridx % 2 == 1 else white_fill
    last = header_row + len(rows)
    return header_row, first, last, last + 2


def _build_synthese_sheet(
    wb: Workbook,
    banner_title: str,
    blocks: list[dict[str, Any]],
    *,
    chart_title: str | None = None,
    chart_block_index: int = 0,
    chart_value_col: int = 2,
) -> None:
    """Crée la feuille « Synthèse » (blocs de totaux + un BarChart), dans le
    même esprit que la feuille de synthèse du modèle budget."""
    ws = wb.create_sheet("Synthèse")
    ws.sheet_properties.tabColor = "FF0F766E"
    ws.sheet_view.showGridLines = False
    row = 3
    refs: list[tuple[int, int, int]] = []
    for b in blocks:
        header_row, first, last, nxt = _write_synthese_block(
            ws, row, b["title"], b["headers"], b["rows"], b.get("money_cols", ())
        )
        refs.append((header_row, first, last))
        row = nxt

    if chart_title and blocks and blocks[chart_block_index]["rows"]:
        header_row, first, last = refs[chart_block_index]
        bar = BarChart()
        bar.type = "col"
        bar.title = chart_title
        bar.height = 8
        bar.width = 16
        bar.add_data(
            Reference(ws, min_col=chart_value_col, min_row=header_row, max_row=last),
            titles_from_data=True,
        )
        bar.set_categories(Reference(ws, min_col=1, min_row=first, max_row=last))
        ws.add_chart(bar, "F3")

    _autosize_columns(ws)
    _write_banner(ws, banner_title, None, 8)


@router.get("/budget")
async def export_budget(
    annee: int | None = Query(default=None),
    type: str | None = Query(default=None),
    service_id: int | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    if annee is None:
        result = await db.execute(select(func.max(BudgetExercice.annee)).where(BudgetExercice.organisation_id == user.organisation_id))
        annee = result.scalar_one_or_none()

    if annee is None:
        raise HTTPException(status_code=404, detail="Aucun exercice budgétaire disponible")

    exercice_res = await db.execute(select(BudgetExercice).where(
        BudgetExercice.annee == annee,
        BudgetExercice.organisation_id == user.organisation_id
    ))
    exercice = exercice_res.scalar_one_or_none()
    if exercice is None:
        raise HTTPException(status_code=404, detail="Exercice introuvable")

    query = select(BudgetPoste).where(
        BudgetPoste.exercice_id == exercice.id,
        BudgetPoste.is_deleted.is_(False),
    )
    filtre_type = type.upper() if type else None
    if filtre_type and filtre_type != "TOUT":
        query = query.where(BudgetPoste.type == filtre_type)
    query = query.order_by(BudgetPoste.code)
    lignes = list((await db.execute(query)).scalars().all())

    service_label: str | None = None
    if service_id is not None:
        service_res = await db.execute(
            select(Service).where(
                Service.id == service_id,
                Service.organisation_id == user.organisation_id,
            )
        )
        service = service_res.scalar_one_or_none()
        if service is not None:
            service_label = f"{service.code} - {service.libelle}"

    # Filtre par service : on ne garde que les rubriques rattachées au service
    # (via ServiceRubrique) et leurs postes parents, pour préserver la hiérarchie.
    if service_id is not None:
        rub_res = await db.execute(
            select(ServiceRubrique.budget_poste_id).where(ServiceRubrique.service_id == service_id)
        )
        allowed = set(rub_res.scalars().all())
        by_id_all = {p.id: p for p in lignes}
        keep: set[int] = set()
        for pid in allowed:
            cur = by_id_all.get(pid)
            while cur is not None and cur.id not in keep:
                keep.add(cur.id)
                cur = by_id_all.get(cur.parent_id) if cur.parent_id else None
        lignes = [p for p in lignes if p.id in keep]

    # ── Arbre hiérarchique : un poste parent = somme de ses sous-postes ────────
    by_id = {p.id: p for p in lignes}
    children_map: dict[int | None, list] = {}
    for p in lignes:
        pid = p.parent_id if (p.parent_id in by_id) else None
        children_map.setdefault(pid, []).append(p)
    for kids in children_map.values():
        kids.sort(key=lambda x: (x.code or ""))

    totals_cache: dict[int, tuple[Decimal, Decimal, Decimal]] = {}

    def node_totals(p) -> tuple[Decimal, Decimal, Decimal]:
        if p.id in totals_cache:
            return totals_cache[p.id]
        kids = children_map.get(p.id, [])
        if kids:
            prevu = engage = paye = Decimal(0)
            for k in kids:
                kp, ke, kpy = node_totals(k)
                prevu += kp
                engage += ke
                paye += kpy
        else:
            prevu = Decimal(p.montant_prevu or 0)
            engage = Decimal(p.montant_engage or 0)
            paye = Decimal(p.montant_paye or 0)
        totals_cache[p.id] = (prevu, engage, paye)
        return totals_cache[p.id]

    ordered: list[tuple[Any, int, bool]] = []

    def walk(nodes, depth: int) -> None:
        for n in nodes:
            kids = children_map.get(n.id, [])
            ordered.append((n, depth, bool(kids)))
            if kids:
                walk(kids, depth + 1)

    walk(children_map.get(None, []), 0)

    # ── Styles ─── constantes & objets de style promus au niveau module ────────
    def _pct(num: Decimal, den: Decimal) -> Decimal:
        return (num / den * Decimal(100)) if den > 0 else Decimal(0)

    wb = Workbook()
    ws = wb.active
    ws.title = f"Budget {annee}"
    ws.sheet_properties.tabColor = GREEN
    ws.sheet_view.showGridLines = False
    if wb.calculation is not None:
        wb.calculation.fullCalcOnLoad = True
        wb.calculation.forceFullCalc = True

    vue_label = (
        "RECETTES" if filtre_type == "RECETTE"
        else "DÉPENSES" if filtre_type == "DEPENSE"
        else "GLOBAL"
    )
    ws.merge_cells("A1:L1")
    ws["A1"] = f"BUDGET {vue_label} {annee}"
    ws["A1"].font = Font(bold=True, size=16, color="FFFFFFFF")
    ws["A1"].fill = header_fill
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28
    ws.merge_cells("A2:L2")
    subtitle_parts = ["Suivi de l'exécution budgétaire par poste et sous-poste", "Montants en USD"]
    if service_label:
        subtitle_parts.insert(1, f"Service : {service_label}")
    ws["A2"] = " | ".join(subtitle_parts)
    ws["A2"].font = Font(italic=True, color=SLATE)
    ws["A2"].alignment = Alignment(horizontal="center")
    ws.row_dimensions[2].height = 22

    leaves = [(p, d, ip) for (p, d, ip) in ordered if not ip]
    tot_prevu = sum((node_totals(p)[0] for p, _, _ in leaves), Decimal(0))
    tot_engage = sum((node_totals(p)[1] for p, _, _ in leaves), Decimal(0))
    tot_paye = sum((node_totals(p)[2] for p, _, _ in leaves), Decimal(0))
    tot_disp = tot_prevu - tot_paye
    tot_reste_engager = tot_prevu - tot_engage

    SUMMARY_LABEL_ROW = 4
    SUMMARY_VALUE_ROW = 5
    summary_cards = [
        ("Budget prévu", float(tot_prevu), MONEY, GREEN_LIGHT),
        ("Engagé", float(tot_engage), MONEY, TEAL_SOFT),
        ("Payé", float(tot_paye), MONEY, AMBER_SOFT),
        ("Disponible", float(tot_disp), MONEY, RED_SOFT if tot_disp < 0 else GREEN_LIGHT),
        ("Taux exécution", float(_pct(tot_paye, tot_prevu)), PCT, SLATE_LIGHT),
        ("Sous-postes", len(leaves), None, SLATE_LIGHT),
    ]
    for idx, (label, value, fmt, fill_color) in enumerate(summary_cards):
        start_col = 1 + idx * 2
        end_col = start_col + 1
        ws.merge_cells(start_row=SUMMARY_LABEL_ROW, start_column=start_col, end_row=SUMMARY_LABEL_ROW, end_column=end_col)
        ws.merge_cells(start_row=SUMMARY_VALUE_ROW, start_column=start_col, end_row=SUMMARY_VALUE_ROW, end_column=end_col)
        label_cell = ws.cell(row=SUMMARY_LABEL_ROW, column=start_col, value=label)
        value_cell = ws.cell(row=SUMMARY_VALUE_ROW, column=start_col, value=value)
        label_cell.font = Font(bold=True, color=SLATE, size=9)
        value_cell.font = Font(bold=True, color=GREEN_DARK, size=12)
        label_cell.alignment = center
        value_cell.alignment = center
        if fmt:
            value_cell.number_format = fmt
        for row in (SUMMARY_LABEL_ROW, SUMMARY_VALUE_ROW):
            for col in range(start_col, end_col + 1):
                cell = ws.cell(row=row, column=col)
                cell.fill = PatternFill(fill_type="solid", fgColor=fill_color)
                cell.border = border

    ws.row_dimensions[4].height = 20
    ws.row_dimensions[5].height = 26

    HEADER_ROW = 7
    FIRST = 8
    headers = [
        "Code", "Nature", "Niveau", "Poste budgétaire", "Type",
        "Prévu (USD)", "Engagé (USD)", "Payé (USD)", "Disponible (USD)",
        "Reste à engager (USD)", "Taux d'engagement %", "Taux d'exécution %",
    ]
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=HEADER_ROW, column=i, value=h)
        c.font = header_font
        c.fill = header_fill
        c.alignment = center
        c.border = border
    ws.row_dimensions[HEADER_ROW].height = 24

    # Rangée Excel de chaque poste : un parent référence ses enfants, et le total
    # référence seulement les sous-postes pour éviter tout double comptage.
    row_of = {poste.id: FIRST + idx for idx, (poste, _, _) in enumerate(ordered)}

    for idx, (poste, depth, is_parent) in enumerate(ordered):
        r = FIRST + idx
        prevu, _engage, paye = node_totals(poste)
        taux_exec = _pct(paye, prevu)
        marker = ("»" * min(depth + 1, 3) + " ") if is_parent else ""
        libelle = ("    " * depth) + (poste.libelle or "")
        ws.cell(row=r, column=1, value=f"{marker}{poste.code or ''}")
        ws.cell(row=r, column=2, value="Poste parent" if is_parent else "Sous-poste")
        ws.cell(row=r, column=3, value=depth)
        ws.cell(row=r, column=4, value=libelle)
        ws.cell(row=r, column=5, value=poste.type or "")
        if is_parent:
            krows = [row_of[k.id] for k in children_map.get(poste.id, [])]
            ws.cell(row=r, column=6, value="=" + "+".join(f"F{k}" for k in krows))
            ws.cell(row=r, column=7, value="=" + "+".join(f"G{k}" for k in krows))
            ws.cell(row=r, column=8, value="=" + "+".join(f"H{k}" for k in krows))
        else:
            ws.cell(row=r, column=6, value=float(prevu))
            ws.cell(row=r, column=7, value=float(_engage))
            ws.cell(row=r, column=8, value=float(paye))
        ws.cell(row=r, column=9, value=f"=F{r}-H{r}")
        ws.cell(row=r, column=10, value=f"=F{r}-G{r}")
        ws.cell(row=r, column=11, value=f"=IF(F{r}>0,G{r}/F{r}*100,0)")
        ws.cell(row=r, column=12, value=f"=IF(F{r}>0,H{r}/F{r}*100,0)")
        for col in range(1, 13):
            cell = ws.cell(row=r, column=col)
            cell.border = border
            cell.alignment = left if col in (1, 4) else center
            if col in (6, 7, 8, 9, 10, 11, 12):
                cell.alignment = right
        ws.cell(row=r, column=3).font = Font(color="FF64748B")
        for col in range(6, 11):
            ws.cell(row=r, column=col).number_format = MONEY
        ws.cell(row=r, column=11).number_format = PCT
        ws.cell(row=r, column=12).number_format = PCT
        # Regroupement pliable : chaque sous-poste est indenté sous son parent.
        if depth > 0:
            ws.row_dimensions[r].outline_level = min(depth, 7)
        if is_parent:
            fill = PatternFill(fill_type="solid", fgColor=LEVEL_FILLS[min(depth, len(LEVEL_FILLS) - 1)])
            for col in range(1, 13):
                cell = ws.cell(row=r, column=col)
                cell.fill = fill
                cell.font = Font(bold=True, color=GREEN_DARK)
        elif idx % 2 == 1:
            for col in range(1, 13):
                ws.cell(row=r, column=col).fill = muted_fill
        exec_cell = ws.cell(row=r, column=12)
        if taux_exec >= Decimal(100):
            exec_cell.font = Font(bold=True, color="FFDC2626")
        elif taux_exec >= Decimal(90):
            exec_cell.font = Font(bold=True, color="FFB45309")

    last_data = FIRST + len(ordered) - 1

    # ── Ligne TOTAL : somme des sous-postes uniquement, donc sans double comptage.
    total_row = last_data + 1
    ws.cell(row=total_row, column=1, value="TOTAL")
    ws.cell(row=total_row, column=2, value="Synthèse")
    ws.cell(row=total_row, column=4, value="Total sans double comptage")
    for col_letter, col in (("F", 6), ("G", 7), ("H", 8)):
        formula = (
            f'=SUMIF($B${FIRST}:$B${last_data},"Sous-poste",{col_letter}${FIRST}:{col_letter}${last_data})'
            if last_data >= FIRST
            else 0
        )
        ws.cell(row=total_row, column=col, value=formula)
    ws.cell(row=total_row, column=9, value=f"=F{total_row}-H{total_row}")
    ws.cell(row=total_row, column=10, value=f"=F{total_row}-G{total_row}")
    ws.cell(row=total_row, column=11, value=f"=IF(F{total_row}>0,G{total_row}/F{total_row}*100,0)")
    ws.cell(row=total_row, column=12, value=f"=IF(F{total_row}>0,H{total_row}/F{total_row}*100,0)")
    for col in range(1, 13):
        cell = ws.cell(row=total_row, column=col)
        cell.font = Font(bold=True, color="FFFFFFFF")
        cell.fill = header_fill
        cell.border = border
        cell.alignment = right if col >= 6 else center
    for col in range(6, 11):
        ws.cell(row=total_row, column=col).number_format = MONEY
    ws.cell(row=total_row, column=11).number_format = PCT
    ws.cell(row=total_row, column=12).number_format = PCT

    # Barres de données sur le taux d'exécution (jauge visuelle par ligne).
    if last_data >= FIRST:
        ws.conditional_formatting.add(
            f"L{FIRST}:L{last_data}",
            DataBarRule(start_type="num", start_value=0, end_type="num",
                        end_value=100, color="FF10B981"),
        )

    ws.freeze_panes = f"A{FIRST}"
    ws.auto_filter.ref = f"A{HEADER_ROW}:L{last_data}"
    if ws.sheet_properties.outlinePr is not None:
        ws.sheet_properties.outlinePr.summaryBelow = False
    for col_letter, w in (("A", 16), ("B", 13), ("C", 8), ("D", 46), ("E", 12),
                          ("F", 15), ("G", 14), ("H", 14), ("I", 15), ("J", 16),
                          ("K", 16), ("L", 16)):
        ws.column_dimensions[col_letter].width = w

    # ── Feuille « Synthèse » (indicateurs + graphiques) ────────────────────────
    leaf_stats = []
    for p, _, _ in leaves:
        pv, en, py = node_totals(p)
        leaf_stats.append((p, pv, en, py, _pct(py, pv)))
    nb_postes = len(leaf_stats)
    nb_entames = sum(1 for _, _, _, py, _ in leaf_stats if py > 0)
    nb_proches = sum(1 for *_, pct in leaf_stats if Decimal(90) <= pct < Decimal(100))
    nb_depass = sum(1 for *_, pct in leaf_stats if pct >= Decimal(100))

    ws2 = wb.create_sheet("Synthèse")
    ws2.sheet_properties.tabColor = "FF0F766E"
    ws2.sheet_view.showGridLines = False
    ws2.append(["Indicateur", "Valeur"])
    for col_idx in (1, 2):
        c = ws2.cell(row=1, column=col_idx)
        c.font = header_font
        c.fill = header_fill
        c.alignment = center
        c.border = border
    synth_rows = [
        ("Exercice", annee, None),
        ("Type", (filtre_type or "TOUT"), None),
        ("Nombre de sous-postes", nb_postes, None),
        ("Sous-postes entamés", nb_entames, None),
        ("Proches du plafond (90-99%)", nb_proches, None),
        ("En dépassement (>=100%)", nb_depass, None),
        ("Total budget prévu (USD)", float(tot_prevu), MONEY),
        ("Total engagé (USD)", float(tot_engage), MONEY),
        (
            "Total recettes réalisées (USD)" if filtre_type == "RECETTE"
            else "Total dépenses effectuées (USD)",
            float(tot_paye), MONEY,
        ),
        ("Disponible (USD)", float(tot_disp), MONEY),
        ("Reste à engager (USD)", float(tot_reste_engager), MONEY),
        ("Taux d'engagement global %", float(_pct(tot_engage, tot_prevu)), PCT),
        ("Taux d'exécution global %", float(_pct(tot_paye, tot_prevu)), PCT),
    ]
    for label, val, fmt in synth_rows:
        ws2.append([label, val])
        row_idx = ws2.max_row
        fill = muted_fill if row_idx % 2 == 0 else PatternFill(fill_type="solid", fgColor="FFFFFFFF")
        if label.startswith("Total") or label.startswith("Disponible") or label.startswith("Reste"):
            fill = subheader_fill
        if label.startswith("En dépassement"):
            fill = PatternFill(fill_type="solid", fgColor=RED_SOFT)
        ws2.cell(row=row_idx, column=1).font = Font(bold=True, color=SLATE)
        ws2.cell(row=row_idx, column=1).border = border
        ws2.cell(row=row_idx, column=2).border = border
        ws2.cell(row=row_idx, column=2).alignment = right
        for col_idx in (1, 2):
            ws2.cell(row=row_idx, column=col_idx).fill = fill
        if fmt:
            ws2.cell(row=row_idx, column=2).number_format = fmt

    # ── Graphiques ─────────────────────────────────────────────────────────────
    top = sorted(leaf_stats, key=lambda t: t[3], reverse=True)[:10]
    if top:
        gh = ws2.max_row + 2  # en-tête du bloc de données servant aux graphiques
        ws2.cell(row=gh, column=1, value="Poste")
        ws2.cell(row=gh, column=2, value="Payé (USD)")
        ws2.cell(row=gh, column=3, value="Prévu (USD)")
        for col_idx in range(1, 4):
            cell = ws2.cell(row=gh, column=col_idx)
            cell.font = header_font
            cell.fill = header_fill
            cell.border = border
            cell.alignment = center
        for i, (p, pv, en, py, pct) in enumerate(top, start=1):
            rr = gh + i
            ws2.cell(row=rr, column=1, value=(p.libelle or p.code or "")[:30])
            ws2.cell(row=rr, column=2, value=float(py)).number_format = MONEY
            ws2.cell(row=rr, column=3, value=float(pv)).number_format = MONEY
            for col_idx in range(1, 4):
                cell = ws2.cell(row=rr, column=col_idx)
                cell.fill = muted_fill if i % 2 == 0 else PatternFill(fill_type="solid", fgColor="FFFFFFFF")
                cell.border = border
        bar = BarChart()
        bar.type = "bar"
        bar.title = "Top postes — Payé vs Prévu"
        bar.height = 9
        bar.width = 22
        bar.add_data(
            Reference(ws2, min_col=2, max_col=3, min_row=gh, max_row=gh + len(top)),
            titles_from_data=True,
        )
        bar.set_categories(Reference(ws2, min_col=1, min_row=gh + 1, max_row=gh + len(top)))
        ws2.add_chart(bar, "E2")

        dg = gh + len(top) + 2
        ws2.cell(row=dg, column=1, value="Payé")
        ws2.cell(row=dg, column=2, value=float(tot_paye)).number_format = MONEY
        ws2.cell(row=dg + 1, column=1, value="Disponible")
        ws2.cell(row=dg + 1, column=2, value=float(tot_disp)).number_format = MONEY
        for row_idx, fill_color in ((dg, AMBER_SOFT), (dg + 1, GREEN_LIGHT if tot_disp >= 0 else RED_SOFT)):
            for col_idx in (1, 2):
                cell = ws2.cell(row=row_idx, column=col_idx)
                cell.fill = PatternFill(fill_type="solid", fgColor=fill_color)
                cell.border = border
                if col_idx == 1:
                    cell.font = Font(bold=True, color=SLATE)
        doughnut = DoughnutChart()
        doughnut.title = "Exécution globale (Payé vs Disponible)"
        doughnut.height = 7
        doughnut.width = 9
        doughnut.add_data(Reference(ws2, min_col=2, min_row=dg, max_row=dg + 1))
        doughnut.set_categories(Reference(ws2, min_col=1, min_row=dg, max_row=dg + 1))
        ws2.add_chart(doughnut, "E20")

    # Liste des dépassements (postes au plafond ou au-delà).
    depassements = sorted(
        [(p, pv, py, pct) for (p, pv, en, py, pct) in leaf_stats if pct >= Decimal(100)],
        key=lambda t: t[3],
        reverse=True,
    )
    if depassements:
        ws2.append([])
        ws2.append(["Postes en dépassement", ""])
        dep_title_row = ws2.max_row
        for col_idx in range(1, 6):
            cell = ws2.cell(row=dep_title_row, column=col_idx)
            cell.fill = PatternFill(fill_type="solid", fgColor=RED_SOFT)
            cell.border = border
        ws2.cell(row=dep_title_row, column=1).font = Font(bold=True, color="FFDC2626")
        ws2.append(["Code", "Poste", "Plafond", "Payé", "Taux d'exécution %"])
        for col_idx in range(1, 6):
            ws2.cell(row=ws2.max_row, column=col_idx).font = Font(bold=True, color="FFFFFFFF")
            ws2.cell(row=ws2.max_row, column=col_idx).fill = PatternFill(fill_type="solid", fgColor="FFDC2626")
            ws2.cell(row=ws2.max_row, column=col_idx).border = border
        for p, pv, py, pct in depassements:
            ws2.append([p.code or "", p.libelle or "", float(pv), float(py), float(pct)])
            row_idx = ws2.max_row
            for col_idx in range(1, 6):
                ws2.cell(row=row_idx, column=col_idx).fill = PatternFill(fill_type="solid", fgColor=RED_SOFT)
                ws2.cell(row=row_idx, column=col_idx).border = border
            ws2.cell(row=row_idx, column=3).number_format = MONEY
            ws2.cell(row=row_idx, column=4).number_format = MONEY
            ws2.cell(row=row_idx, column=5).number_format = PCT
    _autosize_columns(ws2)

    suffix = filtre_type or "TOUT"
    if service_id is not None:
        suffix = f"{suffix}_service{service_id}"
    filename = f"budget_{annee}_{suffix}.xlsx"
    return _excel_response(filename, wb)


@router.get("/encaissements", dependencies=[Depends(has_permission("menu_encaissements"))])
async def export_encaissements(
    date_debut: str | None = Query(default=None),
    date_fin: str | None = Query(default=None),
    statut_paiement: str | None = Query(default=None),
    numero_recu: str | None = Query(default=None),
    client: str | None = Query(default=None),
    budget_poste_id: int | None = Query(default=None),
    type_client: str | None = Query(default=None),
    mode_paiement: str | None = Query(default=None),
    expert_comptable_id: str | None = Query(default=None),
    est_proforma: bool | None = Query(default=False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    query = select(Encaissement, ExpertComptable).outerjoin(
        ExpertComptable, Encaissement.expert_comptable_id == ExpertComptable.id
    ).where(Encaissement.organisation_id == user.organisation_id)

    start_dt = _parse_datetime(date_debut)
    end_dt = _parse_datetime(date_fin, end_of_day=True)
    if start_dt:
        query = query.where(Encaissement.date_encaissement >= start_dt)
    if end_dt:
        query = query.where(Encaissement.date_encaissement <= end_dt)

    if statut_paiement:
        query = query.where(Encaissement.statut_paiement == statut_paiement)
    if numero_recu:
        query = query.where(Encaissement.numero_recu.ilike(f"%{numero_recu}%"))
    if budget_poste_id:
        query = query.where(Encaissement.budget_poste_id == budget_poste_id)
    if type_client:
        query = query.where(Encaissement.type_client == type_client)
    if mode_paiement:
        query = query.where(Encaissement.mode_paiement == mode_paiement)
    if est_proforma is not None:
        query = query.where(Encaissement.est_proforma.is_(est_proforma))
    if est_proforma is False:
        query = query.where((Encaissement.statut_operation.is_(None)) | (Encaissement.statut_operation == "ACTIVE"))
    if expert_comptable_id:
        try:
            exp_uid = uuid.UUID(expert_comptable_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid expert_comptable_id UUID")
        query = query.where(Encaissement.expert_comptable_id == exp_uid)

    if client:
        query = query.where(
            or_(
                Encaissement.client_nom.ilike(f"%{client}%"),
                ExpertComptable.nom_denomination.ilike(f"%{client}%"),
                ExpertComptable.numero_ordre.ilike(f"%{client}%"),
            )
        )

    query = query.order_by(Encaissement.date_encaissement.desc())

    rows = (await db.execute(query)).all()

    req_ids = [req.id for _, req in rows if req is not None]
    rubriques_map: dict[str, str] = {}
    if req_ids:
        lignes = (
            await db.execute(
                select(LigneRequisition).where(LigneRequisition.requisition_id.in_(req_ids))
            )
        ).scalars().all()
        grouped: dict[str, set[str]] = {}
        for ligne in lignes:
            key = str(ligne.requisition_id)
            grouped.setdefault(key, set()).add(ligne.rubrique)
        rubriques_map = {k: ", ".join(sorted(v)) for k, v in grouped.items()}

    wb = Workbook()
    ws = wb.active
    ws.title = "Encaissements"

    headers = [
        "Date",
        "N° Reçu",
        "Type de client",
        "Client",
        "Libellé",
        "Poste budgétaire",
        "Description",
        "Devise perçue",
        "Montant perçu",
        "Montant total (USD)",
        "Montant payé (USD)",
        "Reste à payer (USD)",
        "Mode de paiement",
        "Référence",
        "Statut paiement",
    ]

    data_rows: list[list[Any]] = []
    total_facture = Decimal("0")
    total_paye = Decimal("0")
    totals_by_mode: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    totals_by_type_client: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))

    for enc, expert in rows:
        client_label = (
            f"{expert.numero_ordre} - {expert.nom_denomination}"
            if expert is not None
            else (enc.client_nom or "")
        )
        montant_total = _round_money(enc.montant_total or enc.montant or Decimal("0"))
        montant_paye = _round_money(enc.montant_percu or enc.montant_paye or Decimal("0"))
        reste = _round_money(montant_total - montant_paye)
        if abs(reste) < Decimal("0.05"):
            reste = Decimal("0.00")
            montant_paye = montant_total
        total_facture += Decimal(montant_total or 0)
        total_paye += Decimal(montant_paye or 0)

        mode_label = _format_mode_paiement(enc.mode_paiement)
        totals_by_mode[mode_label or "Non précisé"] += Decimal(montant_paye or 0)
        totals_by_type_client[enc.type_client or "Non précisé"] += Decimal(montant_total or 0)

        poste_label = (
            f"{enc.budget_poste_code} - {enc.budget_poste_libelle}"
            if enc.budget_poste_code and enc.budget_poste_libelle
            else (enc.budget_poste_code or enc.budget_poste_libelle or "")
        )
        data_rows.append(
            [
                enc.date_encaissement.strftime("%d/%m/%Y") if enc.date_encaissement else "",
                enc.numero_recu,
                enc.type_client,
                client_label,
                enc.libelle or "",
                poste_label,
                enc.description or "",
                enc.devise_perception or "USD",
                float(enc.montant_percu or 0),
                float(montant_total or 0),
                float(montant_paye or 0),
                float(reste or 0),
                mode_label,
                enc.reference or "",
                enc.statut_paiement,
            ]
        )

    periode = f"{date_debut or 'début'} → {date_fin or 'fin'}"
    _build_list_sheet(
        ws,
        title="ENCAISSEMENTS",
        subtitle=f"Période : {periode}  |  Montants en USD",
        headers=headers,
        data_rows=data_rows,
        money_cols=(9, 10, 11, 12),
        total_values={
            10: float(total_facture),
            11: float(total_paye),
            12: float(total_facture - total_paye),
        },
    )

    mode_rows = [
        [mode, float(amount)]
        for mode, amount in sorted(totals_by_mode.items(), key=lambda kv: kv[1], reverse=True)
    ]
    type_rows = [
        [tc, float(amount)]
        for tc, amount in sorted(totals_by_type_client.items(), key=lambda kv: kv[1], reverse=True)
    ]
    _build_synthese_sheet(
        wb,
        "Synthèse — Encaissements",
        [
            {
                "title": "Répartition par mode de paiement",
                "headers": ["Mode de paiement", "Montant payé (USD)"],
                "rows": mode_rows,
                "money_cols": (2,),
            },
            {
                "title": "Répartition par type de client",
                "headers": ["Type de client", "Montant total (USD)"],
                "rows": type_rows,
                "money_cols": (2,),
            },
        ],
        chart_title="Encaissements par mode de paiement",
        chart_block_index=0,
        chart_value_col=2,
    )

    suffix = f"{date_debut or 'debut'}_{date_fin or 'fin'}"
    filename = f"encaissements_{suffix}.xlsx"
    return _excel_response(filename, wb)


@router.get("/sorties-fonds")
async def export_sorties_fonds(
    date_debut: str | None = Query(default=None),
    date_fin: str | None = Query(default=None),
    type_sortie: str | None = Query(default=None),
    mode_paiement: str | None = Query(default=None),
    statut: str | None = Query(default=None),
    requisition_numero: str | None = Query(default=None),
    reference: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    Auteur = aliased(User)
    Programmeur = aliased(User)
    query = select(SortieFonds, Requisition, Auteur, Programmeur).outerjoin(
        Requisition, SortieFonds.requisition_id == Requisition.id
    ).outerjoin(
        Auteur, SortieFonds.created_by == Auteur.id
    ).outerjoin(
        Programmeur, SortieFonds.programme_par_id == Programmeur.id
    ).where(SortieFonds.organisation_id == user.organisation_id)

    query = query.where(
        or_(
            SortieFonds.requisition_id.is_(None),
            Requisition.status.in_(REQUISITION_STATUTS_VALIDES),
        )
    )

    start_dt = _parse_datetime(date_debut)
    end_dt = _parse_datetime(date_fin, end_of_day=True)
    if start_dt:
        query = query.where(SortieFonds.date_paiement >= start_dt)
    if end_dt:
        query = query.where(SortieFonds.date_paiement <= end_dt)

    if type_sortie:
        query = query.where(SortieFonds.type_sortie == type_sortie)
    if mode_paiement:
        query = query.where(SortieFonds.mode_paiement == mode_paiement)
    if statut:
        statut_value = statut.strip().upper()
        if statut_value == "ALL":
            query = query
        elif statut_value == "VALIDE":
            query = query.where(
                (SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE")
            )
        else:
            query = query.where(SortieFonds.statut == statut_value)
    else:
        query = query.where(
            (SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE")
        )
    if reference:
        query = query.where(SortieFonds.reference.ilike(f"%{reference}%"))
    if requisition_numero:
        query = query.where(Requisition.numero_requisition.ilike(f"%{requisition_numero}%"))

    query = query.order_by(SortieFonds.created_at.desc())

    rows = (await db.execute(query)).all()

    req_ids = [req.id for _, req, _, _ in rows if req is not None]
    rubriques_map: dict[str, str] = {}
    if req_ids:
        lignes = (
            await db.execute(
                select(LigneRequisition).where(LigneRequisition.requisition_id.in_(req_ids))
            )
        ).scalars().all()
        grouped: dict[str, set[str]] = {}
        for ligne in lignes:
            key = str(ligne.requisition_id)
            grouped.setdefault(key, set()).add(ligne.rubrique)
        rubriques_map = {k: ", ".join(sorted(v)) for k, v in grouped.items()}

    wb = Workbook()
    ws = wb.active
    ws.title = "Sorties"

    headers = [
        "Créée le",
        "Heure",
        "Date",
        "Auteur de l'opération",
        "Programmé par",
        "N° Réquisition",
        "Objet",
        "Poste budgétaire",
        "Bénéficiaire",
        "Motif",
        "Montant payé (USD)",
        "Mode de paiement",
        "Référence",
        "Statut",
        "Commentaire",
    ]

    data_rows: list[list[Any]] = []
    total_paye = Decimal("0")
    totals_by_type: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    totals_by_mode: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))

    def _person_name(u) -> str:
        if not u:
            return ""
        full = f"{u.prenom or ''} {u.nom or ''}".strip()
        return full or u.email or str(u.id)

    for sortie, req, creator, programmeur in rows:
        montant = Decimal(sortie.montant_paye or 0)
        total_paye += montant
        rubrique_value = rubriques_map.get(str(req.id), "") if req else ""

        author_name = _person_name(creator)
        programmeur_name = _person_name(programmeur)

        mode_label = _format_mode_paiement(sortie.mode_paiement)
        totals_by_type[sortie.type_sortie or "Non précisé"] += montant
        totals_by_mode[mode_label or "Non précisé"] += montant

        data_rows.append(
            [
                sortie.created_at.strftime("%d/%m/%Y") if sortie.created_at else "",
                sortie.created_at.strftime("%H:%M") if sortie.created_at else "",
                sortie.date_paiement.strftime("%d/%m/%Y") if sortie.date_paiement else "",
                author_name,
                programmeur_name,
                req.numero_requisition if req else "",
                req.objet if req else "",
                rubrique_value,
                sortie.beneficiaire or "",
                sortie.motif or "",
                float(sortie.montant_paye or 0),
                mode_label,
                sortie.reference or "",
                (sortie.statut or "VALIDE"),
                sortie.commentaire or "",
            ]
        )

    periode = f"{date_debut or 'début'} → {date_fin or 'fin'}"
    _build_list_sheet(
        ws,
        title="SORTIES DE FONDS",
        subtitle=f"Période : {periode}  |  Montants en USD",
        headers=headers,
        data_rows=data_rows,
        money_cols=(11,),
        total_values={11: float(total_paye)},
    )

    type_rows = [
        [t, float(amount)]
        for t, amount in sorted(totals_by_type.items(), key=lambda kv: kv[1], reverse=True)
    ]
    mode_rows = [
        [mode, float(amount)]
        for mode, amount in sorted(totals_by_mode.items(), key=lambda kv: kv[1], reverse=True)
    ]
    _build_synthese_sheet(
        wb,
        "Synthèse — Sorties de fonds",
        [
            {
                "title": "Répartition par type de sortie",
                "headers": ["Type de sortie", "Montant payé (USD)"],
                "rows": type_rows,
                "money_cols": (2,),
            },
            {
                "title": "Répartition par mode de paiement",
                "headers": ["Mode de paiement", "Montant payé (USD)"],
                "rows": mode_rows,
                "money_cols": (2,),
            },
        ],
        chart_title="Sorties par type",
        chart_block_index=0,
        chart_value_col=2,
    )

    suffix = f"{date_debut or 'debut'}_{date_fin or 'fin'}"
    filename = f"sorties_fonds_{suffix}.xlsx"
    return _excel_response(filename, wb)


@router.get("/requisitions", dependencies=[Depends(has_permission("requisitions"))])
async def export_requisitions(
    date_debut: str | None = Query(default=None),
    date_fin: str | None = Query(default=None),
    statut: str | None = Query(default=None),
    service_id: int | None = Query(default=None),
    type_requisition: str | None = Query(default=None),
    mode_paiement: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    query = select(Requisition, Service).outerjoin(
        Service, Requisition.service_id == Service.id
    ).where(
        Requisition.organisation_id == user.organisation_id,
        Requisition.is_deleted.is_(False),
    )

    start_dt = _parse_datetime(date_debut)
    end_dt = _parse_datetime(date_fin, end_of_day=True)
    if start_dt:
        query = query.where(Requisition.created_at >= start_dt)
    if end_dt:
        query = query.where(Requisition.created_at <= end_dt)

    if statut:
        statut_value = statut.strip().upper()
        if statut_value != "ALL":
            query = query.where(Requisition.status == statut_value)
    if service_id is not None:
        query = query.where(Requisition.service_id == service_id)
    if type_requisition:
        query = query.where(Requisition.type_requisition == type_requisition)
    if mode_paiement:
        query = query.where(Requisition.mode_paiement == mode_paiement)

    query = query.order_by(Requisition.created_at.desc())

    rows = (await db.execute(query)).all()

    # Montant déjà payé par réquisition = somme des sorties de fonds validées
    # (même règle que la liste des réquisitions).
    montant_paye_map: dict[Any, Decimal] = {}
    req_ids = [req.id for req, _ in rows]
    if req_ids:
        sortie_res = await db.execute(
            select(
                SortieFonds.requisition_id,
                func.coalesce(func.sum(SortieFonds.montant_paye), 0),
            )
            .where(SortieFonds.requisition_id.in_(req_ids))
            .where((SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE"))
            .group_by(SortieFonds.requisition_id)
        )
        montant_paye_map = {row[0]: Decimal(row[1] or 0) for row in sortie_res.all()}

    wb = Workbook()
    ws = wb.active
    ws.title = "Réquisitions"

    headers = [
        "N° Réquisition",
        "Date",
        "Objet",
        "Service",
        "Type",
        "Statut",
        "Montant total (USD)",
        "Montant déjà payé (USD)",
        "Reliquat (USD)",
    ]

    data_rows: list[list[Any]] = []
    total_montant = Decimal("0")
    total_paye = Decimal("0")
    by_statut_count: dict[str, int] = defaultdict(int)
    by_statut_amount: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    by_service_amount: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))

    for req, service in rows:
        montant_total = _round_money(req.montant_total)
        paye = _round_money(montant_paye_map.get(req.id, Decimal("0")))
        reliquat = _round_money(montant_total - paye)
        total_montant += montant_total
        total_paye += paye

        service_label = f"{service.code} - {service.libelle}" if service else ""
        statut_label = req.status or "Non précisé"
        by_statut_count[statut_label] += 1
        by_statut_amount[statut_label] += montant_total
        by_service_amount[service_label or "Sans service"] += montant_total

        data_rows.append(
            [
                req.numero_requisition or "",
                req.created_at.strftime("%d/%m/%Y") if req.created_at else "",
                req.objet or "",
                service_label,
                req.type_requisition or "",
                statut_label,
                float(montant_total),
                float(paye),
                float(reliquat),
            ]
        )

    periode = f"{date_debut or 'début'} → {date_fin or 'fin'}"
    _build_list_sheet(
        ws,
        title="RÉQUISITIONS",
        subtitle=f"Période : {periode}  |  Montants en USD",
        headers=headers,
        data_rows=data_rows,
        money_cols=(7, 8, 9),
        total_values={
            7: float(total_montant),
            8: float(total_paye),
            9: float(total_montant - total_paye),
        },
    )

    statut_rows = [
        [statut_label, by_statut_count[statut_label], float(by_statut_amount[statut_label])]
        for statut_label in sorted(
            by_statut_amount, key=lambda s: by_statut_amount[s], reverse=True
        )
    ]
    service_rows = [
        [svc, float(amount)]
        for svc, amount in sorted(by_service_amount.items(), key=lambda kv: kv[1], reverse=True)
    ]
    _build_synthese_sheet(
        wb,
        "Synthèse — Réquisitions",
        [
            {
                "title": "Répartition par statut",
                "headers": ["Statut", "Nombre", "Montant total (USD)"],
                "rows": statut_rows,
                "money_cols": (3,),
            },
            {
                "title": "Répartition par service",
                "headers": ["Service", "Montant total (USD)"],
                "rows": service_rows,
                "money_cols": (2,),
            },
        ],
        chart_title="Montant total par statut",
        chart_block_index=0,
        chart_value_col=3,
    )

    suffix = f"{date_debut or 'debut'}_{date_fin or 'fin'}"
    filename = f"requisitions_{suffix}.xlsx"
    return _excel_response(filename, wb)


@router.get("/experts-comptables")
async def export_experts(
    q: str | None = Query(default=None),
    statut_professionnel: str | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    active: bool | None = Query(default=True),
    order: str | None = Query(default=None),
    user: User = Depends(require_expert_admin),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    query = select(ExpertComptable)

    if q:
        q_value = f"%{q.strip()}%"
        query = query.where(
            or_(
                ExpertComptable.numero_ordre.ilike(q_value),
                ExpertComptable.nom_denomination.ilike(q_value),
                ExpertComptable.email.ilike(q_value),
                ExpertComptable.cabinet_attache.ilike(q_value),
            )
        )
    if statut_professionnel:
        variants = _statut_professionnel_variants(statut_professionnel)
        if variants:
            query = query.where(func.trim(ExpertComptable.statut_professionnel).in_(variants))
    if not include_inactive and active is not None:
        query = query.where(ExpertComptable.active == active)

    if order:
        parts = order.split(".")
        field = parts[0]
        direction = parts[1] if len(parts) > 1 else "asc"
        column_map = {
            "numero_ordre": ExpertComptable.numero_ordre,
            "nom_denomination": ExpertComptable.nom_denomination,
            "created_at": ExpertComptable.created_at,
            "statut_professionnel": ExpertComptable.statut_professionnel,
        }
        col = column_map.get(field)
        if col is not None:
            query = query.order_by(col.desc() if direction.lower() == "desc" else col.asc())
        else:
            query = query.order_by(ExpertComptable.numero_ordre.asc())
    else:
        query = query.order_by(ExpertComptable.numero_ordre.asc())

    experts = (await db.execute(query)).scalars().all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Experts"

    headers = [
        "N° Ordre",
        "Nom/Dénomination",
        "Type",
        "Catégorie Personne",
        "Statut Professionnel",
        "Cabinet Attache",
        "Email",
        "Téléphone",
        "État",
    ]
    data_rows = [
        [
            expert.numero_ordre,
            expert.nom_denomination,
            expert.type_ec,
            expert.categorie_personne or "",
            expert.statut_professionnel or "",
            expert.cabinet_attache or "",
            expert.email or "",
            expert.telephone or "",
            "Actif" if expert.active else "Archivé",
        ]
        for expert in experts
    ]
    _build_list_sheet(
        ws,
        title="Experts-comptables",
        subtitle=f"{len(experts)} expert(s)",
        headers=headers,
        data_rows=data_rows,
    )

    filename = "experts_comptables.xlsx"
    return _excel_response(filename, wb)
