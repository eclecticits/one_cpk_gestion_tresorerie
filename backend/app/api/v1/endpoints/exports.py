from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
from typing import Any

import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.encaissement import Encaissement
from app.models.expert_comptable import ExpertComptable
from app.models.budget import BudgetExercice, BudgetLigne
from app.models.ligne_requisition import LigneRequisition
from app.models.requisition import Requisition
from app.models.sortie_fonds import SortieFonds
from app.models.user import User

router = APIRouter()

REQUISITION_STATUTS_VALIDES = ("VALIDEE", "APPROUVEE", "PAYEE", "payee", "approuvee")

OPERATION_LABELS: dict[str, str] = {
    "cotisation_annuelle": "Cotisation annuelle",
    "cotisation_trimestrielle": "Cotisation trimestrielle",
    "inscription_tableau": "Inscription au tableau",
    "reinscription": "Réinscription",
    "formation": "Formation",
    "seminaire_atelier": "Séminaire / Atelier",
    "achat_documents": "Achat de documents",
    "penalites_amendes": "Pénalités / amendes",
    "regularisation": "Régularisation",
    "contribution_speciale": "Contribution spéciale",
    "autres_paiements_pro": "Autres paiements professionnels",
    "achat_formation": "Achat de formation",
    "frais_participation_evenement": "Frais de participation événement",
    "achat_documents_client": "Achat de documents",
    "frais_attestation": "Frais d'attestation",
    "frais_certification": "Frais de certification",
    "frais_service": "Frais de service",
    "contribution": "Contribution",
    "don_soutien": "Don / soutien",
    "depot_bancaire": "Dépôt bancaire",
    "versement_bancaire": "Versement bancaire",
    "virement_bancaire_recu": "Virement bancaire",
    "subvention": "Subvention",
    "appui_financier": "Appui financier",
    "financement_projet": "Financement de projet",
    "interets_bancaires": "Intérêts bancaires",
    "remboursement_bancaire": "Remboursement bancaire",
    "don_institutionnel": "Don institutionnel",
    "transfert_fonds": "Transfert de fonds",
    "partenariat": "Partenariat",
    "sponsoring": "Sponsoring",
    "financement_activite": "Financement d'activité",
    "autre_encaissement": "Autre encaissement",
    "livre": "Livre",
    "autre": "Autre",
}


def _operation_label(value: str | None) -> str:
    if not value:
        return ""
    return OPERATION_LABELS.get(value, value.replace("_", " ").title())


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
        result = await db.execute(select(func.max(BudgetExercice.annee)))
        annee = result.scalar_one_or_none()

    if annee is None:
        raise HTTPException(status_code=404, detail="Aucun exercice budgétaire disponible")

    exercice_res = await db.execute(select(BudgetExercice).where(BudgetExercice.annee == annee))
    exercice = exercice_res.scalar_one_or_none()
    if exercice is None:
        raise HTTPException(status_code=404, detail="Exercice introuvable")

    query = select(BudgetLigne).where(BudgetLigne.exercice_id == exercice.id)
    if type:
        query = query.where(BudgetLigne.type == type.upper())
    query = query.order_by(BudgetLigne.code)
    lignes = (await db.execute(query)).scalars().all()

    wb = Workbook()
    ws = wb.active
    ws.title = f"Budget {annee}"

    headers = [
        "Code",
        "Rubrique",
        "Type",
        "Prévu (USD)",
        "Engagé (USD)",
        "Payé (USD)",
        "Disponible (USD)",
        "% Consommé",
    ]
    ws.append(headers)

    for line in lignes:
        montant_prevu = Decimal(line.montant_prevu or 0)
        montant_engage = Decimal(line.montant_engage or 0)
        montant_paye = Decimal(line.montant_paye or 0)
        disponible = montant_prevu - montant_engage
        pourcentage = (montant_engage / montant_prevu) * Decimal("100") if montant_prevu > 0 else Decimal("0")
        ws.append(
            [
                line.code,
                line.libelle,
                line.type,
                float(montant_prevu),
                float(montant_engage),
                float(montant_paye),
                float(disponible),
                float(pourcentage),
            ]
        )

    _autosize_columns(ws)
    suffix = type.upper() if type else "TOUT"
    filename = f"budget_{annee}_{suffix}.xlsx"
    return _excel_response(filename, wb)


@router.get("/encaissements")
async def export_encaissements(
    date_debut: str | None = Query(default=None),
    date_fin: str | None = Query(default=None),
    statut_paiement: str | None = Query(default=None),
    numero_recu: str | None = Query(default=None),
    client: str | None = Query(default=None),
    type_operation: str | None = Query(default=None),
    type_client: str | None = Query(default=None),
    mode_paiement: str | None = Query(default=None),
    expert_comptable_id: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    query = select(Encaissement, ExpertComptable).outerjoin(
        ExpertComptable, Encaissement.expert_comptable_id == ExpertComptable.id
    )

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
    if type_operation:
        query = query.where(Encaissement.type_operation == type_operation)
    if type_client:
        query = query.where(Encaissement.type_client == type_client)
    if mode_paiement:
        query = query.where(Encaissement.mode_paiement == mode_paiement)
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
        "Description",
        "Devise perçue",
        "Montant perçu",
        "Taux appliqué",
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
        montant_total = enc.montant_total or enc.montant or Decimal("0")
        montant_paye = enc.montant_paye or Decimal("0")
        reste = montant_total - montant_paye
        total_facture += Decimal(montant_total or 0)
        total_paye += Decimal(montant_paye or 0)

        type_operation_label = _operation_label(enc.type_operation)
        ws.append(
            [
                enc.date_encaissement.strftime("%d/%m/%Y") if enc.date_encaissement else "",
                enc.numero_recu,
                enc.type_client,
                client_label,
                type_operation_label,
                enc.description or "",
                enc.devise_perception or "USD",
                float(enc.montant_percu or 0),
                float(enc.taux_change_applique or 0),
                float(montant_total or 0),
                float(montant_paye or 0),
                float(reste or 0),
                enc.mode_paiement,
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
    requisition_numero: str | None = Query(default=None),
    reference: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    query = select(SortieFonds, Requisition).outerjoin(
        Requisition, SortieFonds.requisition_id == Requisition.id
    )

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
    if reference:
        query = query.where(SortieFonds.reference.ilike(f"%{reference}%"))
    if requisition_numero:
        query = query.where(Requisition.numero_requisition.ilike(f"%{requisition_numero}%"))

    query = query.order_by(SortieFonds.date_paiement.desc())

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
    ws.title = "Sorties"

    headers = [
        "Date",
        "N° Réquisition",
        "Objet",
        "Rubrique",
        "Bénéficiaire",
        "Motif",
        "Montant payé (USD)",
        "Mode de paiement",
        "Référence",
        "Commentaire",
    ]
    ws.append(headers)

    total_paye = Decimal("0")

    for sortie, req in rows:
        total_paye += Decimal(sortie.montant_paye or 0)
        rubrique_value = rubriques_map.get(str(req.id), "") if req else ""
        ws.append(
            [
                sortie.date_paiement.strftime("%d/%m/%Y") if sortie.date_paiement else "",
                req.numero_requisition if req else "",
                req.objet if req else "",
                rubrique_value,
                sortie.beneficiaire or "",
                sortie.motif or "",
                float(sortie.montant_paye or 0),
                sortie.mode_paiement,
                sortie.reference or "",
                sortie.commentaire or "",
            ]
        )

    ws.append([
        "",
        "",
        "TOTAL",
        "",
        "",
        "",
        float(total_paye),
        "",
        "",
        "",
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
    user: User = Depends(get_current_user),
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
        query = query.where(ExpertComptable.statut_professionnel == statut_professionnel)
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
