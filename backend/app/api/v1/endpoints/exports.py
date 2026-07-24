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

    headers = [
        "Code", "Nature", "Niveau", "Poste budgétaire", "Type",
        "Prévu (USD)", "Engagé (USD)", "Payé (USD)", "Disponible (USD)",
        "Reste à engager (USD)", "Taux d'engagement %", "Taux d'exécution %",
    ]
    ws.append(headers)
    for col_idx in range(1, len(headers) + 1):
        c = ws.cell(row=1, column=col_idx)
        c.font = header_font
        c.fill = header_fill
        c.alignment = center
        c.border = border

    for poste, depth, is_parent in ordered:
        prevu, engage, paye = node_totals(poste)
        disponible = prevu - paye
        reste_engager = prevu - engage
        taux_eng = _pct(engage, prevu)
        taux_exec = _pct(paye, prevu)
        marker = ("»" * min(depth + 1, 3) + " ") if is_parent else ""
        libelle = ("    " * depth) + (poste.libelle or "")
        ws.append([
            f"{marker}{poste.code or ''}",
            "Poste parent" if is_parent else "Sous-poste",
            depth,
            libelle,
            poste.type or "",
            float(prevu), float(engage), float(paye), float(disponible),
            float(reste_engager), float(taux_eng), float(taux_exec),
        ])
        r = ws.max_row
        for col in range(6, 11):
            ws.cell(row=r, column=col).number_format = MONEY
        ws.cell(row=r, column=11).number_format = PCT
        ws.cell(row=r, column=12).number_format = PCT
        if is_parent:
            fill = PatternFill(fill_type="solid", fgColor=LEVEL_FILLS[min(depth, len(LEVEL_FILLS) - 1)])
            for col in range(1, 13):
                cell = ws.cell(row=r, column=col)
                cell.fill = fill
                cell.font = Font(bold=True, color="FF064E3B")
        # Alerte visuelle sur le taux d'exécution.
        exec_cell = ws.cell(row=r, column=12)
        if taux_exec >= Decimal(100):
            exec_cell.font = Font(bold=True, color="FFDC2626")
        elif taux_exec >= Decimal(90):
            exec_cell.font = Font(bold=True, color="FFB45309")

    # ── Ligne TOTAL (feuilles uniquement, pas de double comptage) ──────────────
    leaves = [(p, d, ip) for (p, d, ip) in ordered if not ip]
    tot_prevu = sum((node_totals(p)[0] for p, _, _ in leaves), Decimal(0))
    tot_engage = sum((node_totals(p)[1] for p, _, _ in leaves), Decimal(0))
    tot_paye = sum((node_totals(p)[2] for p, _, _ in leaves), Decimal(0))
    tot_disp = tot_prevu - tot_paye
    tot_reste = tot_prevu - tot_engage
    ws.append([
        "TOTAL", "", "", "Ensemble des sous-postes", "",
        float(tot_prevu), float(tot_engage), float(tot_paye), float(tot_disp),
        float(tot_reste), float(_pct(tot_engage, tot_prevu)), float(_pct(tot_paye, tot_prevu)),
    ])
    total_row = ws.max_row
    for col in range(1, 13):
        cell = ws.cell(row=total_row, column=col)
        cell.font = Font(bold=True, color="FFFFFFFF")
        cell.fill = header_fill
    for col in range(6, 11):
        ws.cell(row=total_row, column=col).number_format = MONEY
    ws.cell(row=total_row, column=11).number_format = PCT
    ws.cell(row=total_row, column=12).number_format = PCT

    ws.freeze_panes = "A2"
    if total_row > 2:
        ws.auto_filter.ref = f"A1:L{total_row - 1}"
    _autosize_columns(ws)
    ws.column_dimensions["D"].width = max(ws.column_dimensions["D"].width or 0, 44)

    # ── Feuille « Synthèse » ───────────────────────────────────────────────────
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
