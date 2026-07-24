from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
from typing import Any
import unicodedata

import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
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


@router.get("/budget")
async def export_budget(
    annee: int | None = Query(default=None),
    type: str | None = Query(default=None),
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

    # ── Styles ────────────────────────────────────────────────────────────────
    GREEN = "FF065F46"
    LEVEL_FILLS = ["FF6EE7B7", "FFA7F3D0", "FFC6F6DF", "FFD1FAE5"]
    header_font = Font(bold=True, color="FFFFFFFF", size=10)
    header_fill = PatternFill(fill_type="solid", fgColor=GREEN)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin = Side(style="thin", color="FFD1D5DB")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    MONEY = "#,##0.00"
    PCT = '0.0"%"'

    def _pct(num: Decimal, den: Decimal) -> Decimal:
        return (num / den * Decimal(100)) if den > 0 else Decimal(0)

    wb = Workbook()
    ws = wb.active
    ws.title = f"Budget {annee}"

    vue_label = (
        "RECETTES" if filtre_type == "RECETTE"
        else "DÉPENSES" if filtre_type == "DEPENSE"
        else "GLOBAL"
    )
    ws.merge_cells("A1:L1")
    ws["A1"] = f"BUDGET {vue_label} {annee}"
    ws["A1"].font = Font(bold=True, size=14, color="FFFFFFFF")
    ws["A1"].fill = header_fill
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 22
    ws.merge_cells("A2:L2")
    ws["A2"] = "Suivi de l'exécution budgétaire par poste et sous-poste — montants en USD"
    ws["A2"].font = Font(italic=True, color="FF475569")
    ws["A2"].alignment = Alignment(horizontal="center")

    HEADER_ROW = 4
    FIRST = 5
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

    # Rangée Excel de chaque poste : permet des formules « vivantes » (un parent
    # référence ses enfants, le total référence les racines) — un utilisateur
    # peut modifier une feuille, tout se recalcule sans double comptage.
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
                cell.font = Font(bold=True, color="FF064E3B")
        exec_cell = ws.cell(row=r, column=12)
        if taux_exec >= Decimal(100):
            exec_cell.font = Font(bold=True, color="FFDC2626")
        elif taux_exec >= Decimal(90):
            exec_cell.font = Font(bold=True, color="FFB45309")

    last_data = FIRST + len(ordered) - 1

    # ── Ligne TOTAL : somme des postes RACINES (= toutes les feuilles agrégées,
    #    sans double comptage). Formule vivante elle aussi.
    leaves = [(p, d, ip) for (p, d, ip) in ordered if not ip]
    total_row = last_data + 1
    root_rows = [row_of[p.id] for p in children_map.get(None, [])]
    ws.cell(row=total_row, column=1, value="TOTAL")
    ws.cell(row=total_row, column=4, value="Ensemble des sous-postes")
    for col_letter, col in (("F", 6), ("G", 7), ("H", 8)):
        ws.cell(
            row=total_row, column=col,
            value=("=" + "+".join(f"{col_letter}{rr}" for rr in root_rows)) if root_rows else 0,
        )
    ws.cell(row=total_row, column=9, value=f"=F{total_row}-H{total_row}")
    ws.cell(row=total_row, column=10, value=f"=F{total_row}-G{total_row}")
    ws.cell(row=total_row, column=11, value=f"=IF(F{total_row}>0,G{total_row}/F{total_row}*100,0)")
    ws.cell(row=total_row, column=12, value=f"=IF(F{total_row}>0,H{total_row}/F{total_row}*100,0)")
    for col in range(1, 13):
        cell = ws.cell(row=total_row, column=col)
        cell.font = Font(bold=True, color="FFFFFFFF")
        cell.fill = header_fill
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

    # ── Totaux (Python) pour la feuille de synthèse ────────────────────────────
    tot_prevu = sum((node_totals(p)[0] for p, _, _ in leaves), Decimal(0))
    tot_engage = sum((node_totals(p)[1] for p, _, _ in leaves), Decimal(0))
    tot_paye = sum((node_totals(p)[2] for p, _, _ in leaves), Decimal(0))
    tot_disp = tot_prevu - tot_paye

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
    ws2.append(["Indicateur", "Valeur"])
    for col_idx in (1, 2):
        c = ws2.cell(row=1, column=col_idx)
        c.font = header_font
        c.fill = header_fill
    synth_rows = [
        ("Exercice", annee, None),
        ("Type", (filtre_type or "TOUT"), None),
        ("Nombre de sous-postes", nb_postes, None),
        ("Sous-postes entamés", nb_entames, None),
        ("Proches du plafond (90-99%)", nb_proches, None),
        ("En dépassement (>=100%)", nb_depass, None),
        ("Total prévu (USD)", float(tot_prevu), MONEY),
        ("Total engagé (USD)", float(tot_engage), MONEY),
        ("Total payé (USD)", float(tot_paye), MONEY),
        ("Disponible (USD)", float(tot_disp), MONEY),
        ("Taux d'engagement global %", float(_pct(tot_engage, tot_prevu)), PCT),
        ("Taux d'exécution global %", float(_pct(tot_paye, tot_prevu)), PCT),
    ]
    for label, val, fmt in synth_rows:
        ws2.append([label, val])
        ws2.cell(row=ws2.max_row, column=1).font = Font(bold=True)
        if fmt:
            ws2.cell(row=ws2.max_row, column=2).number_format = fmt

    # ── Graphiques ─────────────────────────────────────────────────────────────
    top = sorted(leaf_stats, key=lambda t: t[3], reverse=True)[:10]
    if top:
        gh = ws2.max_row + 2  # en-tête du bloc de données servant aux graphiques
        ws2.cell(row=gh, column=1, value="Poste")
        ws2.cell(row=gh, column=2, value="Payé (USD)")
        ws2.cell(row=gh, column=3, value="Prévu (USD)")
        for i, (p, pv, en, py, pct) in enumerate(top, start=1):
            rr = gh + i
            ws2.cell(row=rr, column=1, value=(p.libelle or p.code or "")[:30])
            ws2.cell(row=rr, column=2, value=float(py)).number_format = MONEY
            ws2.cell(row=rr, column=3, value=float(pv)).number_format = MONEY
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
        ws2.cell(row=ws2.max_row, column=1).font = Font(bold=True, color="FFDC2626")
        ws2.append(["Code", "Poste", "Plafond", "Payé", "Taux d'exécution %"])
        for col_idx in range(1, 6):
            ws2.cell(row=ws2.max_row, column=col_idx).font = Font(bold=True, color="FFFFFFFF")
            ws2.cell(row=ws2.max_row, column=col_idx).fill = header_fill
        for p, pv, py, pct in depassements:
            ws2.append([p.code or "", p.libelle or "", float(pv), float(py), float(pct)])
            ws2.cell(row=ws2.max_row, column=3).number_format = MONEY
            ws2.cell(row=ws2.max_row, column=4).number_format = MONEY
            ws2.cell(row=ws2.max_row, column=5).number_format = PCT
    _autosize_columns(ws2)

    suffix = filtre_type or "TOUT"
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
    ws.append(headers)

    total_facture = Decimal("0")
    total_paye = Decimal("0")

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

        poste_label = (
            f"{enc.budget_poste_code} - {enc.budget_poste_libelle}"
            if enc.budget_poste_code and enc.budget_poste_libelle
            else (enc.budget_poste_code or enc.budget_poste_libelle or "")
        )
        ws.append(
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
                _format_mode_paiement(enc.mode_paiement),
                enc.reference or "",
                enc.statut_paiement,
            ]
        )

    ws.append([
        "",
        "",
        "",
        "",
        "TOTAL",
        "",
        "",
        "",
        float(total_facture),
        float(total_paye),
        float(total_facture - total_paye),
        "",
        "",
        "",
    ])

    _autosize_columns(ws)

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
    ws.append(headers)

    total_paye = Decimal("0")

    def _person_name(u) -> str:
        if not u:
            return ""
        full = f"{u.prenom or ''} {u.nom or ''}".strip()
        return full or u.email or str(u.id)

    for sortie, req, creator, programmeur in rows:
        total_paye += Decimal(sortie.montant_paye or 0)
        rubrique_value = rubriques_map.get(str(req.id), "") if req else ""

        author_name = _person_name(creator)
        programmeur_name = _person_name(programmeur)

        ws.append(
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
                _format_mode_paiement(sortie.mode_paiement),
                sortie.reference or "",
                (sortie.statut or "VALIDE"),
                sortie.commentaire or "",
            ]
        )

    ws.append([
        "",              # Créée le
        "",              # Heure
        "",              # Date
        "TOTAL",         # Auteur de l'opération
        "",              # Programmé par
        "",              # N° Réquisition
        "",              # Objet
        "",              # Poste budgétaire
        "",              # Bénéficiaire
        "",              # Motif
        float(total_paye),  # Montant payé (USD)
        "",              # Mode de paiement
        "",              # Référence
        "",              # Statut
        "",              # Commentaire
    ])

    _autosize_columns(ws)

    suffix = f"{date_debut or 'debut'}_{date_fin or 'fin'}"
    filename = f"sorties_fonds_{suffix}.xlsx"
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
    ws.append(headers)

    for expert in experts:
        ws.append(
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
        )

    _autosize_columns(ws)

    filename = "experts_comptables.xlsx"
    return _excel_response(filename, wb)
