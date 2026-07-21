from __future__ import annotations

import uuid
import hashlib
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import logging
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status, Request
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, get_current_tenant_id, has_permission
from app.db.session import get_db
from app.models.budget import BudgetPoste
from app.models.cloture_caisse import ClotureCaisse
from app.models.caisse_centrale import CaisseCentrale
from app.models.encaissement import Encaissement, EncaissementArticle
from app.models.organisation import Organisation
from app.models.print_settings import PrintSettings
from app.models.system_settings import SystemSettings
from app.models.expert_comptable import ExpertComptable
from app.models.compte_bancaire import CompteBancaire
from app.models.payment_history import PaymentHistory
from app.models.user import User
from app.models.service import Service
from app.models.service_rubrique import ServiceRubrique
from app.models.rbac import Permission, role_permissions
from app.schemas.payment import EncaissementCancelPayload, EncaissementCreate, EncaissementResponse, EncaissementsListResponse, ProformaConversion
from app.services.document_sequences import generate_document_number
from app.services.service_access import get_user_service_ids
from app.services.whatsapp import normalize_whatsapp_numbers, send_whatsapp_message
from app.services.audit_service import get_request_ip, log_action

router = APIRouter(dependencies=[Depends(has_permission("menu_encaissements"))])
logger = logging.getLogger("onec_cpk_api.encaissements")


TYPE_CLIENTS = {
    "expert_comptable",
    "client_externe",
    "banque_institution",
    "partenaire",
    "organisation",
    "autre",
}
STATUT_PAIEMENT = {"non_paye", "partiel", "complet", "avance"}
MODE_PAIEMENT = {"cash", "mobile_money", "virement", "card", "cheque"}
CANAL_PAIEMENT = {"CAISSE", "BANQUE"}
OPERATION_STATUS = {"ACTIVE", "ANNULEE"}


def _user_info(user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "id": str(user.id),
        "prenom": getattr(user, "prenom", None),
        "nom": getattr(user, "nom", None),
        "email": getattr(user, "email", None),
    }


def _clean_money(value: Decimal | str | int | float | None) -> Decimal:
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


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


def _normalize_text(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def _build_duplicate_identity(
    tenant_id: int,
    payload: EncaissementCreate,
    service_id: int | None,
    montant_total: Decimal,
    montant_paye: Decimal,
    date_encaissement: datetime,
) -> str:
    if payload.type_client == "expert_comptable" and payload.expert_comptable_id:
        client_key = f"expert:{payload.expert_comptable_id}"
    else:
        client_key = f"client:{_normalize_text(payload.client_nom)}"
    service_key = str(service_id) if service_id is not None else "null"
    return "|".join(
        [
            str(tenant_id),
            payload.type_client,
            client_key,
            service_key,
            str(payload.budget_poste_id or ""),
            _normalize_text(payload.libelle),
            str(payload.mode_paiement or ""),
            str(montant_total),
            str(montant_paye),
            date_encaissement.date().isoformat(),
        ]
    )


def _advisory_lock_key(identity: str) -> int:
    digest = hashlib.sha256(identity.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


async def _find_duplicate_encaissement(
    db: AsyncSession,
    tenant_id: int,
    payload: EncaissementCreate,
    service_id: int | None,
    montant_total: Decimal,
    montant_paye: Decimal,
    date_encaissement: datetime,
) -> Encaissement | None:
    start_dt = date_encaissement.replace(hour=0, minute=0, second=0, microsecond=0)
    end_dt = date_encaissement.replace(hour=23, minute=59, second=59, microsecond=999999)
    query = (
        select(Encaissement)
        .where(
            Encaissement.organisation_id == tenant_id,
            Encaissement.is_deleted.is_(False),
            Encaissement.est_proforma.is_(False),
            Encaissement.type_client == payload.type_client,
            Encaissement.budget_poste_id == payload.budget_poste_id,
            Encaissement.mode_paiement == payload.mode_paiement,
            Encaissement.libelle == payload.libelle.strip(),
            Encaissement.montant_total == montant_total,
            Encaissement.montant_paye == montant_paye,
            Encaissement.date_encaissement >= start_dt,
            Encaissement.date_encaissement <= end_dt,
        )
        .order_by(Encaissement.created_at.desc())
        .limit(10)
    )
    if service_id is None:
        query = query.where(Encaissement.service_id.is_(None))
    else:
        query = query.where(Encaissement.service_id == service_id)

    if payload.type_client == "expert_comptable":
        query = query.where(Encaissement.expert_comptable_id == payload.expert_comptable_id)
    else:
        query = query.where(Encaissement.client_nom == payload.client_nom)

    existing = (await db.execute(query)).scalars().all()
    expected_client = _normalize_text(payload.client_nom)
    expected_libelle = _normalize_text(payload.libelle)
    for enc in existing:
        same_client = (
            payload.type_client == "expert_comptable"
            and enc.expert_comptable_id == payload.expert_comptable_id
        ) or (
            payload.type_client != "expert_comptable"
            and _normalize_text(enc.client_nom) == expected_client
        )
        if same_client and _normalize_text(enc.libelle) == expected_libelle:
            return enc
    return None


async def _user_has_permission(db: AsyncSession, user: User, permission_code: str) -> bool:
    if (user.role or "").lower() in {"admin", "super_admin"}:
        return True
    if not user.role_id:
        return False
    res = await db.execute(
        select(Permission.id)
        .join(role_permissions, role_permissions.c.permission_id == Permission.id)
        .where(role_permissions.c.role_id == user.role_id)
        .where(Permission.code == permission_code)
        .limit(1)
    )
    return res.scalar_one_or_none() is not None


def _encaissement_to_response(
    enc: Encaissement,
    expert: ExpertComptable | None = None,
    *,
    creator: User | None = None,
    canceller: User | None = None,
) -> dict[str, Any]:
    articles = enc.__dict__.get("articles") or []
    return {
        "id": str(enc.id),
        "numero_recu": enc.numero_recu,
        "numero_proforma": enc.numero_proforma,
        "est_proforma": enc.est_proforma,
        "source_proforma_id": str(enc.source_proforma_id) if enc.source_proforma_id else None,
        "type_client": enc.type_client,
        "expert_comptable_id": str(enc.expert_comptable_id) if enc.expert_comptable_id else None,
        "client_nom": enc.client_nom,
        "libelle": enc.libelle,
        "description": enc.description,
        "montant": enc.montant,
        "montant_total": enc.montant_total,
        "montant_paye": enc.montant_paye,
        "montant_percu": enc.montant_percu,
        "devise_perception": enc.devise_perception,
        "taux_change_applique": enc.taux_change_applique,
        "budget_poste_id": enc.budget_poste_id,
        "budget_poste_code": enc.budget_poste_code,
        "budget_poste_libelle": enc.budget_poste_libelle,
        "service_id": enc.service_id,
        "statut_paiement": enc.statut_paiement,
        "statut_operation": enc.statut_operation,
        "motif_annulation": enc.motif_annulation,
        "annulee_le": enc.annulee_le,
        "annulee_par_id": str(enc.annulee_par_id) if enc.annulee_par_id else None,
        "annulation_ip": enc.annulation_ip,
        "ancien_statut_operation": enc.ancien_statut_operation,
        "mode_paiement": enc.mode_paiement,
        "reference": enc.reference,
        "canal": enc.canal,
        "compte_bancaire_id": enc.compte_bancaire_id,
        "piece_jointe": enc.piece_jointe,
        "date_encaissement": enc.date_encaissement,
        "date_paiement": enc.date_paiement,
        "created_by": str(enc.created_by) if enc.created_by else None,
        "created_by_user": _user_info(creator),
        "annulee_par_user": _user_info(canceller),
        "created_at": enc.created_at,
        "is_reconciled": enc.is_reconciled,
        "reconciled_at": enc.reconciled_at,
        "reconciled_by_id": str(enc.reconciled_by_id) if enc.reconciled_by_id else None,
        "bank_statement_ref": enc.bank_statement_ref,
        "articles": [
            {
                "id": str(article.id),
                "encaissement_id": str(article.encaissement_id),
                "libelle": article.libelle,
                "description": article.description,
                "quantite": article.quantite,
                "prix_unitaire": article.prix_unitaire,
                "montant": article.montant,
                "sort_order": article.sort_order,
                "created_at": article.created_at,
            }
            for article in sorted(articles, key=lambda item: item.sort_order)
        ],
        "expert_comptable": None
        if expert is None
        else {
            "id": str(expert.id),
            "numero_ordre": expert.numero_ordre,
            "nom_denomination": expert.nom_denomination,
            "type_ec": expert.type_ec,
            "active": expert.active,
        },
    }


def _normalize_article_payloads(payload: EncaissementCreate, montant_total: Decimal) -> list[dict[str, Any]]:
    articles = payload.articles or []
    normalized: list[dict[str, Any]] = []

    for idx, article in enumerate(articles):
        libelle = (article.libelle or "").strip()
        if not libelle:
            raise HTTPException(status_code=400, detail="libelle article requis")

        quantite = _clean_money(article.quantite or 1)
        prix_unitaire = _clean_money(article.prix_unitaire or 0)
        montant = _clean_money(article.montant if article.montant is not None else quantite * prix_unitaire)
        if quantite <= 0:
            raise HTTPException(status_code=400, detail="quantite article invalide")
        if prix_unitaire < 0 or montant < 0:
            raise HTTPException(status_code=400, detail="montant article invalide")

        normalized.append(
            {
                "libelle": libelle,
                "description": article.description,
                "quantite": quantite,
                "prix_unitaire": prix_unitaire,
                "montant": montant,
                "sort_order": idx,
            }
        )

    if not normalized:
        normalized.append(
            {
                "libelle": payload.libelle.strip(),
                "description": payload.description,
                "quantite": Decimal("1.00"),
                "prix_unitaire": montant_total,
                "montant": montant_total,
                "sort_order": 0,
            }
        )

    articles_total = _clean_money(sum((item["montant"] for item in normalized), Decimal("0.00")))
    if articles_total != montant_total:
        raise HTTPException(status_code=400, detail="Le total des articles doit correspondre au montant total")

    return normalized


def _add_encaissement_articles(
    db: AsyncSession,
    encaissement: Encaissement,
    tenant_id: int,
    articles: list[dict[str, Any]],
) -> None:
    for article in articles:
        db.add(
            EncaissementArticle(
                organisation_id=tenant_id,
                encaissement_id=encaissement.id,
                libelle=article["libelle"],
                description=article["description"],
                quantite=article["quantite"],
                prix_unitaire=article["prix_unitaire"],
                montant=article["montant"],
                sort_order=article["sort_order"],
            )
        )


async def _get_or_create_caisse(db: AsyncSession, tenant_id: int) -> CaisseCentrale:
    res = await db.execute(select(CaisseCentrale).where(CaisseCentrale.organisation_id == tenant_id).limit(1))
    caisse = res.scalar_one_or_none()
    if caisse is None:
        caisse = CaisseCentrale(organisation_id=tenant_id, solde_usd=0, solde_cdf=0)
        db.add(caisse)
        await db.flush()
    return caisse


async def _resolve_service(service_id: int, db: AsyncSession) -> Service:
    res = await db.execute(select(Service).where(Service.id == service_id, Service.is_active.is_(True)))
    service = res.scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="service_id invalide")
    return service


def _parse_order(order: str | None):
    if not order:
        return Encaissement.date_encaissement.desc()
    parts = order.split(".")
    field = parts[0]
    direction = parts[1] if len(parts) > 1 else "asc"
    column_map = {
        "date_encaissement": Encaissement.date_encaissement,
        "created_at": Encaissement.created_at,
        "numero_recu": Encaissement.numero_recu,
        "montant_total": Encaissement.montant_total,
        "montant_paye": Encaissement.montant_paye,
    }
    col = column_map.get(field)
    if col is None:
        return Encaissement.date_encaissement.desc()
    return col.desc() if direction.lower() == "desc" else col.asc()


async def _generate_numero_recu(tenant_id: int, db: AsyncSession) -> str:
    result = await db.execute(select(func.generate_recu_numero(tenant_id)))
    return result.scalar_one()


@router.post("/generate-numero-recu")
async def generate_numero_recu(
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> str:
    return await _generate_numero_recu(tenant_id=tenant_id, db=db)


@router.get("/verify")
async def verify_encaissement(
    numero_recu: str = Query(..., description="Numéro de reçu"),
    amount: float = Query(..., description="Montant attendu"),
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    res = await db.execute(
        select(Encaissement).where(
            Encaissement.numero_recu == numero_recu,
            Encaissement.organisation_id == tenant_id,
            Encaissement.is_deleted.is_(False),
            Encaissement.est_proforma.is_(False),
        )
    )
    enc = res.scalar_one_or_none()
    if enc is None:
        return {"ok": False, "reason": "not_found", "numero_recu": numero_recu, "amount": amount}

    montant = float(enc.montant_total or 0)
    ok = abs(montant - float(amount)) <= 0.01
    return {
        "ok": ok,
        "numero_recu": enc.numero_recu,
        "amount": amount,
        "montant_total": montant,
        "statut_paiement": enc.statut_paiement,
        "date_encaissement": enc.date_encaissement,
        "client_nom": enc.client_nom,
    }


@router.get("", response_model=list[EncaissementResponse] | EncaissementsListResponse)
async def list_encaissements(
    include: str | None = Query(default=None, description="Relations à inclure (expert_comptable)"),
    date_debut: str | None = Query(default=None),
    date_fin: str | None = Query(default=None),
    statut_paiement: str | None = Query(default=None),
    numero_recu: str | None = Query(default=None),
    client: str | None = Query(default=None),
    budget_poste_id: int | None = Query(default=None),
    type_client: str | None = Query(default=None),
    mode_paiement: str | None = Query(default=None),
    canal: str | None = Query(default=None),
    compte_bancaire_id: int | None = Query(default=None),
    expert_comptable_id: str | None = Query(default=None),
    operation_status: str | None = Query(default="ACTIVE", description="ACTIVE, ANNULEE, ALL"),
    est_proforma: bool | None = Query(default=False),
    order: str | None = Query(default=None, description="Ex: date_encaissement.desc"),
    limit: int = Query(default=50, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    include_summary: bool = Query(default=False),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    include_parts = {part.strip() for part in (include or "").split(",") if part.strip()}
    include_expert = "expert_comptable" in include_parts or bool(client)
    needs_expert_join = include_expert or bool(client)

    conditions = [Encaissement.organisation_id == tenant_id]
    op_status = (operation_status or "ACTIVE").strip().upper()
    if op_status not in {"ACTIVE", "ANNULEE", "ALL"}:
        raise HTTPException(status_code=400, detail="operation_status invalide (ACTIVE, ANNULEE, ALL)")
    can_view_cancelled = await _user_has_permission(db, user, "view_cancelled_financial_operations")
    if op_status in {"ANNULEE", "ALL"} and not can_view_cancelled:
        raise HTTPException(status_code=403, detail="Privilèges insuffisants (view_cancelled_financial_operations)")

    if user.role != "admin":
        service_ids = await get_user_service_ids(db, user)
        if not service_ids:
            return []
        conditions.append(Encaissement.service_id.in_(service_ids))

    start_dt = _parse_datetime(date_debut)
    end_dt = _parse_datetime(date_fin, end_of_day=True)
    if start_dt:
        conditions.append(Encaissement.date_encaissement >= start_dt)
    if end_dt:
        conditions.append(Encaissement.date_encaissement <= end_dt)

    if statut_paiement:
        conditions.append(Encaissement.statut_paiement == statut_paiement)
    if numero_recu:
        conditions.append(Encaissement.numero_recu.ilike(f"%{numero_recu}%"))
    if est_proforma is not None:
        conditions.append(Encaissement.est_proforma.is_(est_proforma))
    if budget_poste_id:
        conditions.append(Encaissement.budget_poste_id == budget_poste_id)
    if type_client:
        conditions.append(Encaissement.type_client == type_client)
    if mode_paiement:
        conditions.append(Encaissement.mode_paiement == mode_paiement)
    if canal:
        conditions.append(Encaissement.canal == canal.upper())
    if compte_bancaire_id:
        conditions.append(Encaissement.compte_bancaire_id == compte_bancaire_id)
    if expert_comptable_id:
        try:
            exp_uid = uuid.UUID(expert_comptable_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid expert_comptable_id UUID")
        conditions.append(Encaissement.expert_comptable_id == exp_uid)

    if client:
        conditions.append(
            or_(
                Encaissement.client_nom.ilike(f"%{client}%"),
                ExpertComptable.nom_denomination.ilike(f"%{client}%"),
                ExpertComptable.numero_ordre.ilike(f"%{client}%"),
            )
        )

    if op_status == "ACTIVE":
        conditions.append((Encaissement.statut_operation.is_(None)) | (Encaissement.statut_operation == "ACTIVE"))
    elif op_status == "ANNULEE":
        conditions.append(Encaissement.statut_operation == "ANNULEE")

    if include_expert:
        query = select(Encaissement, ExpertComptable).options(selectinload(Encaissement.articles)).outerjoin(
            ExpertComptable, Encaissement.expert_comptable_id == ExpertComptable.id
        )
    else:
        query = select(Encaissement).options(selectinload(Encaissement.articles))

    conditions.append(Encaissement.is_deleted.is_(False))
    if conditions:
        query = query.where(*conditions)

    query = query.order_by(_parse_order(order)).offset(offset).limit(limit)

    result = await db.execute(query)
    users_map: dict[uuid.UUID, User] = {}
    if include_expert:
        rows = result.all()
        user_ids = {
            user_id
            for enc, _expert in rows
            for user_id in (enc.created_by, enc.annulee_par_id)
            if user_id
        }
        if user_ids:
            u_res = await db.execute(select(User).where(User.id.in_(list(user_ids)), User.organisation_id == tenant_id))
            users_map = {u.id: u for u in u_res.scalars().all()}
        logger.info(
            "encaissements list date_debut=%s date_fin=%s count=%s",
            date_debut,
            date_fin,
            len(rows),
        )
        items = [
            _encaissement_to_response(
                enc,
                expert,
                creator=users_map.get(enc.created_by) if enc.created_by else None,
                canceller=users_map.get(enc.annulee_par_id) if enc.annulee_par_id else None,
            )
            for enc, expert in rows
        ]
    else:
        encaissements = result.scalars().all()
        user_ids = {
            user_id
            for enc in encaissements
            for user_id in (enc.created_by, enc.annulee_par_id)
            if user_id
        }
        if user_ids:
            u_res = await db.execute(select(User).where(User.id.in_(list(user_ids)), User.organisation_id == tenant_id))
            users_map = {u.id: u for u in u_res.scalars().all()}
        logger.info(
            "encaissements list date_debut=%s date_fin=%s count=%s",
            date_debut,
            date_fin,
            len(encaissements),
        )
        items = [
            _encaissement_to_response(
                enc,
                creator=users_map.get(enc.created_by) if enc.created_by else None,
                canceller=users_map.get(enc.annulee_par_id) if enc.annulee_par_id else None,
            )
            for enc in encaissements
        ]

    if not include_summary:
        return items

    count_query = select(func.count()).select_from(Encaissement).where(Encaissement.organisation_id == tenant_id)
    sum_query = select(
        func.coalesce(func.sum(func.coalesce(Encaissement.montant_total, Encaissement.montant, 0)), 0),
        func.coalesce(func.sum(func.coalesce(Encaissement.montant_paye, 0)), 0),
    ).select_from(Encaissement).where(Encaissement.organisation_id == tenant_id)
    if needs_expert_join:
        count_query = count_query.outerjoin(ExpertComptable, Encaissement.expert_comptable_id == ExpertComptable.id)
        sum_query = sum_query.outerjoin(ExpertComptable, Encaissement.expert_comptable_id == ExpertComptable.id)
    if conditions:
        count_query = count_query.where(*conditions)
        sum_query = sum_query.where(*conditions)
    sum_query = sum_query.where((Encaissement.statut_operation.is_(None)) | (Encaissement.statut_operation == "ACTIVE"))

    total_count = int((await db.execute(count_query)).scalar_one() or 0)
    totals_row = (await db.execute(sum_query)).first()
    total_montant_facture = Decimal(totals_row[0] or 0) if totals_row else Decimal("0")
    total_montant_paye = Decimal(totals_row[1] or 0) if totals_row else Decimal("0")

    return EncaissementsListResponse(
        items=items,
        total=total_count,
        total_montant_facture=total_montant_facture,
        total_montant_paye=total_montant_paye,
    )


@router.post("/proformas", response_model=EncaissementResponse, status_code=status.HTTP_201_CREATED)
async def create_proforma(
    payload: EncaissementCreate,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    current_user_id = getattr(user, "id", None)
    if current_user_id is None:
        raise HTTPException(status_code=401, detail="Utilisateur invalide")
    if payload.type_client not in TYPE_CLIENTS:
        raise HTTPException(status_code=400, detail="type_client invalide")

    canal = (payload.canal or "CAISSE").upper()
    if canal not in CANAL_PAIEMENT:
        raise HTTPException(status_code=400, detail="canal invalide")

    if not payload.libelle or not payload.libelle.strip():
        raise HTTPException(status_code=400, detail="libelle requis")

    devise = (payload.devise_perception or "USD").upper()
    if devise not in {"USD", "CDF"}:
        raise HTTPException(status_code=400, detail="devise_perception invalide")

    compte_bancaire = None
    if payload.compte_bancaire_id is not None:
        res = await db.execute(
            select(CompteBancaire).where(
                CompteBancaire.id == payload.compte_bancaire_id,
                CompteBancaire.organisation_id == tenant_id,
            )
        )
        compte_bancaire = res.scalar_one_or_none()
        if compte_bancaire is None or compte_bancaire.is_active is False:
            raise HTTPException(status_code=400, detail="compte_bancaire_id invalide")
        if (compte_bancaire.devise or "").upper() != devise:
            raise HTTPException(status_code=400, detail="devise_perception incompatible avec le compte bancaire")
        if canal == "BANQUE" and (compte_bancaire.account_type or "").upper() != "BANK":
            raise HTTPException(status_code=400, detail="compte_bancaire_id invalide")
        if canal == "CAISSE" and (compte_bancaire.account_type or "").upper() != "CASH":
            raise HTTPException(status_code=400, detail="compte_bancaire_id invalide")
    if canal == "BANQUE" and payload.compte_bancaire_id is None:
        raise HTTPException(status_code=400, detail="compte_bancaire_id requis pour canal BANQUE")

    taux_change = _clean_money(payload.taux_change_applique or 0)
    if devise == "CDF":
        settings_res = await db.execute(
            select(PrintSettings).where(PrintSettings.organisation_id == tenant_id).limit(1)
        )
        ps = settings_res.scalar_one_or_none()
        try:
            if ps and ps.exchange_rate_cdf:
                taux_change = _clean_money(ps.exchange_rate_cdf or 0)
            else:
                taux_change = _clean_money(ps.exchange_rate or 0) if ps else Decimal("0")
        except Exception:
            taux_change = Decimal("0.00")
        if taux_change <= 0:
            raise HTTPException(status_code=400, detail="Taux de change invalide (paramètres)")

    montant_percu = _clean_money(payload.montant_percu or 0)
    montant_total = _clean_money(payload.montant_total or 0)
    montant = _clean_money(payload.montant or 0)

    if devise == "CDF":
        if montant_percu <= 0:
            montant_percu = montant_total or montant
        montant_total = (montant_percu / taux_change) if taux_change > 0 else Decimal("0.00")
    else:
        if montant_total == 0 and montant > 0:
            montant_total = montant
        if montant_percu == 0:
            montant_percu = montant_total or montant
        taux_change = Decimal("1.00")

    montant = _clean_money(montant)
    montant_total = _clean_money(montant_total)
    montant_percu = _clean_money(montant_percu)
    article_payloads = _normalize_article_payloads(payload, montant_total)

    expert_uid: uuid.UUID | None = None
    if payload.type_client == "expert_comptable":
        if not payload.expert_comptable_id:
            raise HTTPException(status_code=400, detail="expert_comptable_id requis")
        expert_uid = payload.expert_comptable_id
        res = await db.execute(select(ExpertComptable).where(ExpertComptable.id == expert_uid))
        if not res.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Expert-comptable non trouvé")
    else:
        if not payload.client_nom or not payload.client_nom.strip():
            raise HTTPException(status_code=400, detail="client_nom requis pour ce type_client")

    if payload.budget_poste_id is None:
        raise HTTPException(status_code=400, detail="budget_poste_id requis pour une proforma")

    budget_res = await db.execute(
        select(BudgetPoste).where(
            BudgetPoste.id == payload.budget_poste_id,
            BudgetPoste.is_deleted.is_(False),
        )
    )
    budget_line = budget_res.scalar_one_or_none()
    if budget_line is None or (budget_line.type or "").upper() != "RECETTE":
        raise HTTPException(status_code=400, detail="budget_poste_id invalide (type RECETTE requis)")
    if budget_line.active is False:
        raise HTTPException(status_code=400, detail="Rubrique budgétaire inactive")

    service_id = None
    if user.role != "admin":
        service_ids = await get_user_service_ids(db, user)
        if not service_ids:
            raise HTTPException(status_code=403, detail="Aucun service assigné")
        if payload.service_id is None:
            if len(service_ids) == 1:
                service_id = service_ids[0]
            else:
                raise HTTPException(status_code=400, detail="service_id requis")
        else:
            if payload.service_id not in service_ids:
                raise HTTPException(status_code=403, detail="Accès interdit à ce service")
            service_id = payload.service_id
    else:
        if payload.service_id is not None:
            await _resolve_service(payload.service_id, db)
            service_id = payload.service_id

    if service_id is not None:
        allowed_res = await db.execute(
            select(ServiceRubrique)
            .where(
                ServiceRubrique.service_id == service_id,
                ServiceRubrique.budget_poste_id == budget_line.id,
            )
        )
        if allowed_res.scalar_one_or_none() is None:
            raise HTTPException(status_code=403, detail="Rubrique non autorisée pour ce service")

    date_emission = payload.date_encaissement or datetime.now(timezone.utc)
    if isinstance(date_emission, str):
        parsed = _parse_datetime(date_emission)
        if not parsed:
            raise HTTPException(status_code=400, detail="date_encaissement invalide")
        date_emission = parsed
    if isinstance(date_emission, datetime) and date_emission.tzinfo is None:
        date_emission = date_emission.replace(tzinfo=timezone.utc)

    numero_proforma = await generate_document_number(
        db, doc_type="PROF", tenant_id=tenant_id, service_id=service_id
    )

    encaissement = Encaissement(
        numero_recu=None,
        numero_proforma=numero_proforma,
        est_proforma=True,
        source_proforma_id=None,
        organisation_id=tenant_id,
        type_client=payload.type_client,
        expert_comptable_id=expert_uid,
        client_nom=None if payload.type_client == "expert_comptable" else payload.client_nom,
        libelle=payload.libelle.strip(),
        description=payload.description,
        montant=montant,
        montant_total=montant_total,
        montant_paye=Decimal("0.00"),
        montant_percu=montant_percu,
        devise_perception=devise,
        taux_change_applique=taux_change,
        budget_poste_id=payload.budget_poste_id,
        budget_poste_code=budget_line.code,
        budget_poste_libelle=budget_line.libelle,
        service_id=service_id,
        statut_paiement="non_paye",
        mode_paiement=payload.mode_paiement,
        reference=payload.reference,
        canal=canal,
        compte_bancaire_id=payload.compte_bancaire_id,
        piece_jointe=payload.piece_jointe,
        date_encaissement=date_emission,
        date_paiement=None,
        created_by=current_user_id,
    )
    db.add(encaissement)
    await db.flush()
    _add_encaissement_articles(db, encaissement, tenant_id, article_payloads)
    await db.commit()
    res = await db.execute(
        select(Encaissement).options(selectinload(Encaissement.articles)).where(Encaissement.id == encaissement.id)
    )
    encaissement = res.scalar_one()

    expert = None
    if expert_uid:
        res = await db.execute(select(ExpertComptable).where(ExpertComptable.id == expert_uid))
        expert = res.scalar_one_or_none()

    return _encaissement_to_response(encaissement, expert)


@router.post("", response_model=EncaissementResponse, status_code=status.HTTP_201_CREATED)
async def create_encaissement(
    payload: EncaissementCreate,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    current_user_id = getattr(user, "id", None)
    if current_user_id is None:
        raise HTTPException(status_code=401, detail="Utilisateur invalide")
    if payload.type_client not in TYPE_CLIENTS:
        raise HTTPException(status_code=400, detail="type_client invalide")
    if payload.statut_paiement not in STATUT_PAIEMENT:
        raise HTTPException(status_code=400, detail="statut_paiement invalide")
    if payload.mode_paiement not in MODE_PAIEMENT:
        raise HTTPException(status_code=400, detail="mode_paiement invalide")

    canal = (payload.canal or "CAISSE").upper()
    if canal not in CANAL_PAIEMENT:
        raise HTTPException(status_code=400, detail="canal invalide")

    if not payload.libelle or not payload.libelle.strip():
        raise HTTPException(status_code=400, detail="libelle requis")

    devise = (payload.devise_perception or "USD").upper()
    if devise not in {"USD", "CDF"}:
        raise HTTPException(status_code=400, detail="devise_perception invalide")

    compte_bancaire = None
    if payload.compte_bancaire_id is not None:
        res = await db.execute(
            select(CompteBancaire).where(
                CompteBancaire.id == payload.compte_bancaire_id,
                CompteBancaire.organisation_id == tenant_id,
            )
        )
        compte_bancaire = res.scalar_one_or_none()
        if compte_bancaire is None or compte_bancaire.is_active is False:
            raise HTTPException(status_code=400, detail="compte_bancaire_id invalide")
        if (compte_bancaire.devise or "").upper() != devise:
            raise HTTPException(status_code=400, detail="devise_perception incompatible avec le compte bancaire")
        if canal == "BANQUE" and (compte_bancaire.account_type or "").upper() != "BANK":
            raise HTTPException(status_code=400, detail="compte_bancaire_id invalide")
        if canal == "CAISSE" and (compte_bancaire.account_type or "").upper() != "CASH":
            raise HTTPException(status_code=400, detail="compte_bancaire_id invalide")
    if canal == "BANQUE" and payload.compte_bancaire_id is None:
        raise HTTPException(status_code=400, detail="compte_bancaire_id requis pour canal BANQUE")

    taux_change = _clean_money(payload.taux_change_applique or 0)
    if devise == "CDF":
        settings_res = await db.execute(
            select(PrintSettings).where(PrintSettings.organisation_id == tenant_id).limit(1)
        )
        ps = settings_res.scalar_one_or_none()
        try:
            if ps and ps.exchange_rate_cdf:
                taux_change = _clean_money(ps.exchange_rate_cdf or 0)
            else:
                taux_change = _clean_money(ps.exchange_rate or 0) if ps else Decimal("0")
        except Exception:
            taux_change = Decimal("0.00")
        if taux_change <= 0:
            raise HTTPException(status_code=400, detail="Taux de change invalide (paramètres)")

    montant_percu = _clean_money(payload.montant_percu or 0)
    montant_total = _clean_money(payload.montant_total or 0)
    montant = _clean_money(payload.montant or 0)
    montant_paye = _clean_money(payload.montant_paye or 0)

    if devise == "CDF":
        if montant_percu <= 0:
            montant_percu = montant_total or montant or montant_paye
        montant_total = (montant_percu / taux_change) if taux_change > 0 else Decimal("0.00")
        montant_paye = montant_total
    else:
        if montant_total == 0 and montant > 0:
            montant_total = montant
        if montant_percu == 0:
            montant_percu = montant_paye or montant_total or montant
        taux_change = Decimal("1.00")

    montant = _clean_money(montant)
    montant_total = _clean_money(montant_total)
    montant_paye = _clean_money(montant_paye)
    montant_percu = _clean_money(montant_percu)
    article_payloads = _normalize_article_payloads(payload, montant_total)

    statut_paiement = payload.statut_paiement
    if montant_paye > montant_total and statut_paiement != "avance":
        statut_paiement = "avance"
    elif montant_paye >= montant_total and montant_total > 0:
        statut_paiement = "complet"
    elif montant_paye > 0:
        statut_paiement = "partiel"
    else:
        statut_paiement = "non_paye"

    expert_uid: uuid.UUID | None = None
    if payload.type_client == "expert_comptable":
        if not payload.expert_comptable_id:
            raise HTTPException(status_code=400, detail="expert_comptable_id requis")
        expert_uid = payload.expert_comptable_id
        res = await db.execute(select(ExpertComptable).where(ExpertComptable.id == expert_uid))
        if not res.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Expert-comptable non trouvé")
    else:
        if not payload.client_nom or not payload.client_nom.strip():
            raise HTTPException(status_code=400, detail="client_nom requis pour ce type_client")

    budget_line = None
    if payload.budget_poste_id is None:
        raise HTTPException(status_code=400, detail="budget_poste_id requis pour un encaissement")
    budget_res = await db.execute(
        select(BudgetPoste).where(
            BudgetPoste.id == payload.budget_poste_id,
            BudgetPoste.is_deleted.is_(False),
        )
    )
    budget_line = budget_res.scalar_one_or_none()
    if budget_line is None or (budget_line.type or "").upper() != "RECETTE":
        raise HTTPException(status_code=400, detail="budget_poste_id invalide (type RECETTE requis)")
    if budget_line.active is False:
        raise HTTPException(status_code=400, detail="Rubrique budgétaire inactive")
    budget_poste_code = budget_line.code
    budget_poste_libelle = budget_line.libelle
    budget_line_id = budget_line.id

    service_id = None
    if user.role != "admin":
        service_ids = await get_user_service_ids(db, user)
        if not service_ids:
            raise HTTPException(status_code=403, detail="Aucun service assigné")
        if payload.service_id is None:
            if len(service_ids) == 1:
                service_id = service_ids[0]
            else:
                raise HTTPException(status_code=400, detail="service_id requis")
        else:
            if payload.service_id not in service_ids:
                raise HTTPException(status_code=403, detail="Accès interdit à ce service")
            service_id = payload.service_id
    else:
        if payload.service_id is not None:
            await _resolve_service(payload.service_id, db)
            service_id = payload.service_id

    if service_id is not None:
        allowed_res = await db.execute(
            select(ServiceRubrique)
            .where(
                ServiceRubrique.service_id == service_id,
                ServiceRubrique.budget_poste_id == budget_line.id,
            )
        )
        if allowed_res.scalar_one_or_none() is None:
            raise HTTPException(status_code=403, detail="Rubrique non autorisée pour ce service")

    date_encaissement = payload.date_encaissement or datetime.now(timezone.utc)
    if isinstance(date_encaissement, str):
        parsed = _parse_datetime(date_encaissement)
        if not parsed:
            raise HTTPException(status_code=400, detail="date_encaissement invalide")
        date_encaissement = parsed
    if isinstance(date_encaissement, datetime) and date_encaissement.tzinfo is None:
        date_encaissement = date_encaissement.replace(tzinfo=timezone.utc)

    duplicate_identity = _build_duplicate_identity(
        tenant_id=tenant_id,
        payload=payload,
        service_id=service_id,
        montant_total=montant_total,
        montant_paye=montant_paye,
        date_encaissement=date_encaissement,
    )
    await db.execute(select(func.pg_advisory_xact_lock(_advisory_lock_key(duplicate_identity))))
    duplicate = await _find_duplicate_encaissement(
        db=db,
        tenant_id=tenant_id,
        payload=payload,
        service_id=service_id,
        montant_total=montant_total,
        montant_paye=montant_paye,
        date_encaissement=date_encaissement,
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Un encaissement similaire existe déjà pour cette opération (reçu {duplicate.numero_recu or '—'}).",
        )

    last_cloture_res = await db.execute(
        select(ClotureCaisse).order_by(ClotureCaisse.date_cloture.desc()).limit(1)
    )
    last_cloture = last_cloture_res.scalar_one_or_none()
    last_cloture_dt = last_cloture.date_cloture if last_cloture else None
    if isinstance(last_cloture_dt, datetime) and last_cloture_dt.tzinfo is None:
        last_cloture_dt = last_cloture_dt.replace(tzinfo=timezone.utc)
    if canal == "CAISSE" and last_cloture_dt and date_encaissement.date() <= last_cloture_dt.date():
        raise HTTPException(
            status_code=403,
            detail="Caisse clôturée pour cette journée",
        )
    allow_custom_recu = (user.role or "").lower() == "super_admin"
    provided_recu = payload.numero_recu.strip() if allow_custom_recu and payload.numero_recu else ""
    should_regenerate = not provided_recu
    last_error: Exception | None = None
    max_attempts = 50

    for attempt in range(max_attempts):
        numero_recu = provided_recu or await _generate_numero_recu(tenant_id=tenant_id, db=db)
        encaissement = Encaissement(
            numero_recu=numero_recu,
            numero_proforma=None,
            est_proforma=False,
            source_proforma_id=None,
            organisation_id=tenant_id,
            type_client=payload.type_client,
            expert_comptable_id=expert_uid,
            client_nom=None if payload.type_client == "expert_comptable" else payload.client_nom,
            libelle=payload.libelle.strip(),
            description=payload.description,
            montant=montant,
            montant_total=montant_total,
            montant_paye=montant_paye,
            montant_percu=montant_percu,
            devise_perception=devise,
            taux_change_applique=taux_change,
            budget_poste_id=payload.budget_poste_id,
            budget_poste_code=budget_poste_code,
            budget_poste_libelle=budget_poste_libelle,
            service_id=service_id,
            statut_paiement=statut_paiement,
            mode_paiement=payload.mode_paiement,
            reference=payload.reference,
            canal=canal,
            compte_bancaire_id=payload.compte_bancaire_id,
            piece_jointe=payload.piece_jointe,
            date_encaissement=date_encaissement,
            date_paiement=date_encaissement,
            created_by=current_user_id,
        )
        db.add(encaissement)
        try:
            # Ensure encaissement.id is generated before creating payment history (FK not null).
            await db.flush()
            _add_encaissement_articles(db, encaissement, tenant_id, article_payloads)
            if montant_paye > 0:
                notes_paiement = None
                if payload.notes_paiement and payload.notes_paiement.strip():
                    notes_paiement = payload.notes_paiement.strip()
                payment = PaymentHistory(
                    organisation_id=tenant_id,
                    encaissement_id=encaissement.id,
                    montant=montant_paye,
                    mode_paiement=payload.mode_paiement,
                    reference=payload.reference,
                    notes=notes_paiement,
                    created_by=current_user_id,
                )
                db.add(payment)

            if canal == "CAISSE":
                caisse = await _get_or_create_caisse(db, tenant_id)
                if not caisse.est_ouverte:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Caisse fermée : ouvrez la caisse avant d'enregistrer un encaissement.",
                    )
                if devise == "USD":
                    caisse.solde_usd = (caisse.solde_usd or 0) + montant_paye
                else:
                    caisse.solde_cdf = (caisse.solde_cdf or 0) + montant_paye
                caisse.derniere_maj = datetime.now(timezone.utc)
            else:
                compte_bancaire = compte_bancaire or (
                    await db.execute(
                        select(CompteBancaire).where(
                            CompteBancaire.id == payload.compte_bancaire_id,
                            CompteBancaire.organisation_id == tenant_id,
                        )
                    )
                ).scalar_one()
                compte_bancaire.solde_actuel = (compte_bancaire.solde_actuel or 0) + montant_paye

            if montant_paye > 0:
                await db.execute(
                    update(BudgetPoste)
                    .where(BudgetPoste.id == budget_line_id)
                    .values(montant_paye=BudgetPoste.montant_paye + montant_paye)
                )

            await db.commit()
            res = await db.execute(
                select(Encaissement)
                .options(selectinload(Encaissement.articles))
                .where(Encaissement.id == encaissement.id)
            )
            encaissement = res.scalar_one()
            last_error = None
            break
        except IntegrityError as exc:
            last_error = exc
            await db.rollback()
            compte_bancaire = None
            constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            is_unique = getattr(exc.orig, "pgcode", None) == "23505"
            if constraint == "ck_encaissements_mode_paiement":
                raise HTTPException(
                    status_code=500,
                    detail="Contrainte SQL non mise à jour sur encaissements.mode_paiement. Appliquer la migration backend.",
                )
            if constraint == "ck_payment_history_mode_paiement":
                raise HTTPException(
                    status_code=500,
                    detail="Contrainte SQL non mise à jour sur payment_history.mode_paiement. Appliquer la migration backend.",
                )
            if constraint and constraint != "uq_encaissements_org_numero":
                logger.error("Erreur d'intégrité encaissement: %s", exc, exc_info=True)
                raise HTTPException(status_code=500, detail="Erreur d'intégrité lors de la création")
            if constraint is None and not is_unique:
                logger.error("Erreur d'intégrité encaissement: %s", exc, exc_info=True)
                raise HTTPException(status_code=500, detail="Erreur d'intégrité lors de la création")
            if not should_regenerate:
                break
            provided_recu = ""
            continue

    if last_error is not None:
        raise HTTPException(status_code=409, detail="numero_recu déjà utilisé")

    expert = None
    if expert_uid:
        res = await db.execute(select(ExpertComptable).where(ExpertComptable.id == expert_uid))
        expert = res.scalar_one_or_none()

    return _encaissement_to_response(encaissement, expert)


@router.post("/{encaissement_id}/convertir", response_model=EncaissementResponse)
async def convertir_proforma(
    encaissement_id: str,
    payload: ProformaConversion,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        uid = uuid.UUID(encaissement_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid encaissement_id UUID")

    res = await db.execute(
        select(Encaissement).options(selectinload(Encaissement.articles)).where(
            Encaissement.id == uid,
            Encaissement.organisation_id == tenant_id,
            Encaissement.is_deleted.is_(False),
        )
    )
    encaissement = res.scalar_one_or_none()
    if not encaissement:
        raise HTTPException(status_code=404, detail="Encaissement introuvable")
    if not encaissement.est_proforma:
        raise HTTPException(status_code=400, detail="Cet encaissement n'est pas une proforma")

    if user.role != "admin":
        service_ids = await get_user_service_ids(db, user)
        if encaissement.service_id and encaissement.service_id not in service_ids:
            raise HTTPException(status_code=403, detail="Accès interdit à ce service")

    canal = (payload.canal or encaissement.canal or "CAISSE").upper()
    if canal not in CANAL_PAIEMENT:
        raise HTTPException(status_code=400, detail="canal invalide")

    mode_paiement = payload.mode_paiement or encaissement.mode_paiement or "cash"
    if mode_paiement not in MODE_PAIEMENT:
        raise HTTPException(status_code=400, detail="mode_paiement invalide")

    devise = (encaissement.devise_perception or "USD").upper()
    if devise not in {"USD", "CDF"}:
        raise HTTPException(status_code=400, detail="devise_perception invalide")

    compte_bancaire_id = payload.compte_bancaire_id or encaissement.compte_bancaire_id
    compte_bancaire = None
    if compte_bancaire_id is not None:
        res = await db.execute(
            select(CompteBancaire).where(
                CompteBancaire.id == compte_bancaire_id,
                CompteBancaire.organisation_id == tenant_id,
            )
        )
        compte_bancaire = res.scalar_one_or_none()
        if compte_bancaire is None or compte_bancaire.is_active is False:
            raise HTTPException(status_code=400, detail="compte_bancaire_id invalide")
        if (compte_bancaire.devise or "").upper() != devise:
            raise HTTPException(status_code=400, detail="devise_perception incompatible avec le compte bancaire")
        if canal == "BANQUE" and (compte_bancaire.account_type or "").upper() != "BANK":
            raise HTTPException(status_code=400, detail="compte_bancaire_id invalide")
        if canal == "CAISSE" and (compte_bancaire.account_type or "").upper() != "CASH":
            raise HTTPException(status_code=400, detail="compte_bancaire_id invalide")
    if canal == "BANQUE" and compte_bancaire_id is None:
        raise HTTPException(status_code=400, detail="compte_bancaire_id requis pour canal BANQUE")

    taux_change = _clean_money(encaissement.taux_change_applique or 0)
    if devise == "CDF" and taux_change <= 0:
        raise HTTPException(status_code=400, detail="Taux de change invalide")

    montant_total = _clean_money(encaissement.montant_total or encaissement.montant or 0)
    montant = _clean_money(encaissement.montant or montant_total)
    montant_paye_input = payload.montant_paye

    if devise == "CDF":
        montant_percu = _clean_money(
            montant_paye_input if montant_paye_input is not None else (encaissement.montant_percu or 0)
        )
        if montant_percu <= 0:
            montant_percu = _clean_money(encaissement.montant_percu or 0)
        if montant_percu <= 0:
            raise HTTPException(status_code=400, detail="montant_percu requis pour devise CDF")
        montant_total = (montant_percu / taux_change) if taux_change > 0 else Decimal("0.00")
        montant_paye = montant_total
    else:
        montant_paye = _clean_money(
            montant_paye_input if montant_paye_input is not None else montant_total
        )
        montant_percu = montant_paye

    if montant_paye <= 0:
        raise HTTPException(status_code=400, detail="montant_paye invalide")

    statut_paiement = encaissement.statut_paiement
    if montant_paye > montant_total and statut_paiement != "avance":
        statut_paiement = "avance"
    elif montant_paye >= montant_total and montant_total > 0:
        statut_paiement = "complet"
    elif montant_paye > 0:
        statut_paiement = "partiel"
    else:
        statut_paiement = "non_paye"

    date_paiement = payload.date_paiement or datetime.now(timezone.utc)
    if isinstance(date_paiement, str):
        parsed = _parse_datetime(date_paiement)
        if not parsed:
            raise HTTPException(status_code=400, detail="date_paiement invalide")
        date_paiement = parsed
    if isinstance(date_paiement, datetime) and date_paiement.tzinfo is None:
        date_paiement = date_paiement.replace(tzinfo=timezone.utc)

    last_cloture_res = await db.execute(
        select(ClotureCaisse).order_by(ClotureCaisse.date_cloture.desc()).limit(1)
    )
    last_cloture = last_cloture_res.scalar_one_or_none()
    last_cloture_dt = last_cloture.date_cloture if last_cloture else None
    if isinstance(last_cloture_dt, datetime) and last_cloture_dt.tzinfo is None:
        last_cloture_dt = last_cloture_dt.replace(tzinfo=timezone.utc)
    if canal == "CAISSE" and last_cloture_dt and date_paiement.date() <= last_cloture_dt.date():
        raise HTTPException(status_code=403, detail="Caisse clôturée pour cette journée")

    numero_recu = await _generate_numero_recu(tenant_id=tenant_id, db=db)

    encaissement.numero_recu = numero_recu
    encaissement.est_proforma = False
    encaissement.source_proforma_id = encaissement.id
    encaissement.date_paiement = date_paiement
    encaissement.date_encaissement = date_paiement
    encaissement.mode_paiement = mode_paiement
    encaissement.reference = payload.reference or encaissement.reference
    encaissement.canal = canal
    encaissement.compte_bancaire_id = compte_bancaire_id
    encaissement.montant = montant
    encaissement.montant_total = montant_total
    encaissement.montant_paye = montant_paye
    encaissement.montant_percu = montant_percu
    encaissement.statut_paiement = statut_paiement

    notes_paiement = None
    if payload.notes_paiement and payload.notes_paiement.strip():
        notes_paiement = payload.notes_paiement.strip()

    payment = PaymentHistory(
        organisation_id=tenant_id,
        encaissement_id=encaissement.id,
        montant=montant_paye,
        mode_paiement=mode_paiement,
        reference=payload.reference or encaissement.reference,
        notes=notes_paiement,
        created_by=getattr(user, "id", None),
    )
    db.add(payment)

    if canal == "CAISSE":
        caisse = await _get_or_create_caisse(db, tenant_id)
        if devise == "USD":
            caisse.solde_usd = (caisse.solde_usd or 0) + montant_paye
        else:
            caisse.solde_cdf = (caisse.solde_cdf or 0) + montant_paye
        caisse.derniere_maj = datetime.now(timezone.utc)
    else:
        if compte_bancaire is None:
            res = await db.execute(
                select(CompteBancaire).where(
                    CompteBancaire.id == compte_bancaire_id,
                    CompteBancaire.organisation_id == tenant_id,
                )
            )
            compte_bancaire = res.scalar_one()
        compte_bancaire.solde_actuel = (compte_bancaire.solde_actuel or 0) + montant_paye

    if montant_paye > 0 and encaissement.budget_poste_id:
        await db.execute(
            update(BudgetPoste)
            .where(BudgetPoste.id == encaissement.budget_poste_id)
            .values(montant_paye=BudgetPoste.montant_paye + montant_paye)
        )

    await db.commit()
    res = await db.execute(
        select(Encaissement).options(selectinload(Encaissement.articles)).where(Encaissement.id == encaissement.id)
    )
    encaissement = res.scalar_one()

    expert = None
    if encaissement.expert_comptable_id:
        res = await db.execute(
            select(ExpertComptable).where(ExpertComptable.id == encaissement.expert_comptable_id)
        )
        expert = res.scalar_one_or_none()

    try:
        settings_res = await db.execute(
            select(SystemSettings).where(SystemSettings.organisation_id == tenant_id).limit(1)
        )
        ns = settings_res.scalar_one_or_none()
        if ns and ns.whatsapp_api_url:
            target_numbers = []
            if expert and expert.telephone:
                target_numbers = normalize_whatsapp_numbers(expert.telephone)
            if target_numbers:
                org_res = await db.execute(
                    select(Organisation.nom).where(Organisation.id == tenant_id).limit(1)
                )
                org_name = org_res.scalar_one_or_none() or "ONEC"
                message = (
                    "✅ Paiement confirmé\n"
                    f"Proforma : {encaissement.numero_proforma or '-'}\n"
                    f"Reçu : {encaissement.numero_recu}\n"
                    f"Montant : {float(encaissement.montant_total or 0):,.2f} $\n"
                    f"Organisation : {org_name}"
                )
                for number in target_numbers:
                    background_tasks.add_task(
                        send_whatsapp_message,
                        ns.whatsapp_api_url,
                        ns.whatsapp_api_key,
                        number,
                        message,
                    )
    except Exception:
        logger.exception("Failed to schedule proforma conversion WhatsApp notification")

    return _encaissement_to_response(encaissement, expert)


@router.get("/{encaissement_id}", response_model=EncaissementResponse)
async def get_encaissement(
    encaissement_id: str,
    include: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        uid = uuid.UUID(encaissement_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID")

    include_parts = {part.strip() for part in (include or "").split(",") if part.strip()}
    include_expert = "expert_comptable" in include_parts
    can_view_cancelled = await _user_has_permission(db, user, "view_cancelled_financial_operations")

    if include_expert:
        result = await db.execute(
            select(Encaissement, ExpertComptable)
            .options(selectinload(Encaissement.articles))
            .outerjoin(ExpertComptable, Encaissement.expert_comptable_id == ExpertComptable.id)
            .where(
                Encaissement.id == uid,
                Encaissement.organisation_id == tenant_id,
                Encaissement.is_deleted.is_(False),
            )
        )
        row = result.first()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encaissement non trouvé")
        enc, expert = row
        if (enc.statut_operation or "ACTIVE").upper() == "ANNULEE" and not can_view_cancelled:
            raise HTTPException(status_code=403, detail="Privilèges insuffisants (view_cancelled_financial_operations)")
        return _encaissement_to_response(enc, expert)

    result = await db.execute(
        select(Encaissement).options(selectinload(Encaissement.articles)).where(
            Encaissement.id == uid,
            Encaissement.organisation_id == tenant_id,
            Encaissement.is_deleted.is_(False),
        )
    )
    encaissement = result.scalar_one_or_none()
    if not encaissement:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encaissement non trouvé")
    if (encaissement.statut_operation or "ACTIVE").upper() == "ANNULEE" and not can_view_cancelled:
        raise HTTPException(status_code=403, detail="Privilèges insuffisants (view_cancelled_financial_operations)")
    return _encaissement_to_response(encaissement)


@router.post("/{encaissement_id}/soft-delete", response_model=EncaissementResponse)
async def soft_delete_encaissement(
    encaissement_id: str,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        uid = uuid.UUID(encaissement_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID")

    result = await db.execute(
        select(Encaissement).where(
            Encaissement.id == uid,
            Encaissement.organisation_id == tenant_id,
            Encaissement.is_deleted.is_(False),
        )
    )
    encaissement = result.scalar_one_or_none()
    if not encaissement:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encaissement non trouvé")

    encaissement.is_deleted = True
    encaissement.deleted_at = datetime.now(timezone.utc)
    encaissement.deleted_by = user.id
    await db.commit()
    await db.refresh(encaissement)
    return _encaissement_to_response(encaissement)


@router.post("/{encaissement_id}/restore", response_model=EncaissementResponse)
async def restore_encaissement(
    encaissement_id: str,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        uid = uuid.UUID(encaissement_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID")

    result = await db.execute(
        select(Encaissement).where(
            Encaissement.id == uid,
            Encaissement.organisation_id == tenant_id,
            Encaissement.is_deleted.is_(True),
        )
    )
    encaissement = result.scalar_one_or_none()
    if not encaissement:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encaissement non trouvé")

    encaissement.is_deleted = False
    encaissement.deleted_at = None
    encaissement.deleted_by = None
    await db.commit()
    await db.refresh(encaissement)
    return _encaissement_to_response(encaissement)


@router.post("/{encaissement_id}/cancel-proforma", response_model=EncaissementResponse)
async def cancel_proforma(
    encaissement_id: str,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        uid = uuid.UUID(encaissement_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID")

    result = await db.execute(
        select(Encaissement).where(
            Encaissement.id == uid,
            Encaissement.organisation_id == tenant_id,
            Encaissement.est_proforma.is_(True),
            Encaissement.is_deleted.is_(False),
        )
    )
    encaissement = result.scalar_one_or_none()
    if not encaissement:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proforma non trouvée")

    encaissement.is_deleted = True
    encaissement.deleted_at = datetime.now(timezone.utc)
    encaissement.deleted_by = user.id
    await db.commit()
    await db.refresh(encaissement)
    return _encaissement_to_response(encaissement)


@router.post("/{encaissement_id}/cancel-operation", response_model=EncaissementResponse)
async def cancel_encaissement_operation(
    encaissement_id: str,
    payload: EncaissementCancelPayload,
    request: Request,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if not await _user_has_permission(db, user, "cancel_encaissement"):
        raise HTTPException(status_code=403, detail="Privilèges insuffisants (cancel_encaissement)")
    try:
        uid = uuid.UUID(encaissement_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID")

    result = await db.execute(
        select(Encaissement).where(
            Encaissement.id == uid,
            Encaissement.organisation_id == tenant_id,
            Encaissement.is_deleted.is_(False),
            Encaissement.est_proforma.is_(False),
        )
    )
    encaissement = result.scalar_one_or_none()
    if not encaissement:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encaissement non trouvé")
    if (encaissement.statut_operation or "ACTIVE").upper() == "ANNULEE":
        raise HTTPException(status_code=400, detail="Cet encaissement est déjà annulé")

    reference_time = encaissement.date_paiement or encaissement.date_encaissement or encaissement.created_at
    if encaissement.canal == "CAISSE":
        last_cloture_res = await db.execute(select(ClotureCaisse).order_by(ClotureCaisse.date_cloture.desc()).limit(1))
        last_cloture = last_cloture_res.scalar_one_or_none()
        last_cloture_dt = last_cloture.date_cloture if last_cloture else None
        if isinstance(last_cloture_dt, datetime) and last_cloture_dt.tzinfo is None:
            last_cloture_dt = last_cloture_dt.replace(tzinfo=timezone.utc)
        if isinstance(reference_time, datetime) and reference_time.tzinfo is None:
            reference_time = reference_time.replace(tzinfo=timezone.utc)
        if last_cloture_dt and reference_time and reference_time.date() <= last_cloture_dt.date():
            raise HTTPException(status_code=403, detail="Caisse clôturée pour cette journée")

    montant_paye = _clean_money(encaissement.montant_paye or 0)
    if encaissement.canal == "CAISSE":
        caisse = await _get_or_create_caisse(db, tenant_id)
        res = await db.execute(
            select(CaisseCentrale)
            .where(CaisseCentrale.id == caisse.id, CaisseCentrale.organisation_id == tenant_id)
            .with_for_update()
        )
        caisse = res.scalar_one()
        if encaissement.devise_perception == "USD":
            caisse.solde_usd = max(0, (caisse.solde_usd or 0) - montant_paye)
        else:
            caisse.solde_cdf = max(0, (caisse.solde_cdf or 0) - montant_paye)
        caisse.derniere_maj = datetime.now(timezone.utc)
    elif encaissement.compte_bancaire_id:
        res = await db.execute(
            select(CompteBancaire)
            .where(
                CompteBancaire.id == encaissement.compte_bancaire_id,
                CompteBancaire.organisation_id == tenant_id,
            )
            .with_for_update()
        )
        compte_bancaire = res.scalar_one_or_none()
        if compte_bancaire is None:
            raise HTTPException(status_code=400, detail="Compte de dépôt introuvable pour annuler cet encaissement")
        compte_bancaire.solde_actuel = max(0, (compte_bancaire.solde_actuel or 0) - montant_paye)

    if encaissement.budget_poste_id and montant_paye > 0:
        await db.execute(
            update(BudgetPoste)
            .where(BudgetPoste.id == encaissement.budget_poste_id)
            .values(montant_paye=func.greatest(BudgetPoste.montant_paye - montant_paye, 0))
        )

    previous_status = encaissement.statut_operation or "ACTIVE"
    encaissement.ancien_statut_operation = previous_status
    encaissement.statut_operation = "ANNULEE"
    encaissement.motif_annulation = payload.motif_annulation.strip()
    encaissement.annulee_le = datetime.now(timezone.utc)
    encaissement.annulee_par_id = user.id
    encaissement.annulation_ip = get_request_ip(request)

    await log_action(
        db,
        user_id=user.id,
        action="ENCAISSEMENT_CANCELLED",
        target_table="encaissements",
        target_id=str(encaissement.id),
        old_value={"statut_operation": previous_status},
        new_value={
            "statut_operation": encaissement.statut_operation,
            "motif_annulation": encaissement.motif_annulation,
            "annulee_le": encaissement.annulee_le.isoformat() if encaissement.annulee_le else None,
        },
        ip_address=get_request_ip(request),
    )
    await db.commit()
    await db.refresh(encaissement)
    return _encaissement_to_response(encaissement)
