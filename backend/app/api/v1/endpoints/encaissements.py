from __future__ import annotations

import uuid
import hashlib
import os
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import logging
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, status, Request, UploadFile
from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, get_current_tenant_id, has_permission
from app.core.auth_user import AuthUser, cached_permission_codes
from app.core.config import settings as app_settings
from app.core.horodatage import resoudre_date_operation
from app.db.session import get_db
from app.models.budget import BudgetPoste
from app.models.client import Client
from app.models.cloture_caisse import ClotureCaisse
from app.models.caisse_centrale import CaisseCentrale
from app.models.encaissement import Encaissement, EncaissementArticle
from app.models.encaissement_piece_jointe import EncaissementPieceJointe
from app.models.fonds_tiers_operation import FondsTiersOperation
from app.models.organisation import Organisation
from app.models.print_settings import PrintSettings
from app.models.expert_comptable import ExpertComptable
from app.models.compte_bancaire import CompteBancaire
from app.models.payment_history import PaymentHistory
from app.models.user import User
from app.models.service import Service
from app.models.service_rubrique import ServiceRubrique
from app.models.projet_activite import ProjetActivite
from app.models.rbac import Permission, role_permissions
from app.modules.comptabilite.models import ComptaEcriture
from app.modules.comptabilite.services.generation_service import annuler_ecriture_operation
from app.modules.comptabilite.services.integration_mode import is_accounting_automatic  # compatibility for existing tests
from app.schemas.payment import AffecterBudgetPayload, EncaissementCancelPayload, EncaissementCreate, EncaissementResponse, EncaissementsListResponse, ProformaConversion
from app.services.document_sequences import generate_document_number
from app.services.entrees_caisse import list_entrees_internes_caisse
from app.services.report_cache import invalidate_report_summary_cache
from app.services.recherche_documents import condition_numero
from app.services.service_access import get_user_service_ids, has_module_menu_access
from app.utils.upload_validation import (
    content_length_exceeds,
    matches_declared_type,
    read_upload_limited,
)
from app.services.client_receipt_email import schedule_client_payment_email
from app.services.encaissement_payments import record_encaissement_payment, cancel_encaissement_payment
from app.services.fonds_tiers import (
    assert_fonds_tiers_origin_can_be_cancelled,
    create_fonds_tiers_operation,
    resolve_fonds_tiers_display_name,
    resolve_fonds_tiers_display_names,
)
from app.services.mouvements_budgetaires import (
    cancel_budget_imputations,
    hors_budget_initial_status,
    impact_for_nature,
    normalize_nature,
    sum_active_by_encaissement,
)
from app.services.regularisations_budgetaires import affecter_encaissement_hors_budget

# Encadrement des relances de solde : au-delà du plafond, le recouvrement
# doit passer par un autre canal (appel, courrier) plutôt que des emails sans fin.
MAX_RELANCES_PAR_RECU = 3
RELANCE_DELAI_MIN_JOURS = 7
from app.services.notifications import (
    PAYMENT_PROFORMA_CONVERTED,
    PAYMENT_RECEIVED,
    PAYMENT_REMINDER,
    build_settings as build_whatsapp_settings,
    notify_whatsapp,
    resolve_client_recipient,
)
from app.services.system_settings_service import get_system_settings
from app.services.audit_service import get_request_ip, log_action

router = APIRouter(dependencies=[Depends(has_permission("menu_encaissements"))])
logger = logging.getLogger("onec_cpk_api.encaissements")


TYPE_CLIENTS = {
    "expert_comptable",
    "personne_physique",
    "personne_morale",
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
PIECE_MAX_SIZE = 3 * 1024 * 1024
# Marge pour l'enveloppe multipart (frontières, en-têtes de parties) lors du
# refus anticipé basé sur Content-Length.
PIECE_MAX_SIZE_WITH_OVERHEAD = PIECE_MAX_SIZE + 64 * 1024
PIECE_ALLOWED_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/jpg"}
PIECE_ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
PIECE_FORMAT_DETAIL = "Format non autorisé. Formats acceptés : PDF, JPG, JPEG, PNG."

#: `entity_type` porté par les lignes de `notification_logs` de ce module.
NOTIF_ENTITY_ENCAISSEMENT = "encaissement"

#: Libellés lisibles des modes de paiement, pour les gabarits WhatsApp.
MODE_PAIEMENT_LABELS = {
    "cash": "Espèces",
    "mobile_money": "Mobile money",
    "virement": "Virement bancaire",
    "card": "Carte bancaire",
    "cheque": "Chèque",
}


def _fmt_montant(value: Any) -> str:
    """Montant lisible dans un message : « 1 234.50 ». Sans devise (variable à part)."""
    try:
        return f"{float(value or 0):,.2f}".replace(",", " ")
    except (TypeError, ValueError):
        return "0.00"


def _mode_paiement_label(mode: str | None) -> str:
    key = (mode or "").strip().lower()
    return MODE_PAIEMENT_LABELS.get(key, key.replace("_", " ").capitalize() if key else "")


async def _notify_paiement_whatsapp(
    db: AsyncSession,
    background_tasks: BackgroundTasks | None,
    *,
    encaissement: Encaissement,
    tenant_id: int,
    event_type: str,
    expert: ExpertComptable | None = None,
    montant_recu: Any = None,
    entity_type: str = NOTIF_ENTITY_ENCAISSEMENT,
    entity_id: str | None = None,
    nonce: str = "",
) -> None:
    """Notifie le client par WhatsApp, en écho de `schedule_client_payment_email`.

    À appeler **après** le `commit()` de l'opération de caisse. Ne lève jamais :
    tout est enfermé dans un `try`, et `notify_whatsapp` lui-même ne remonte
    aucune exception. Un canal fermé, un numéro absent ou une panne du
    fournisseur laissent une ligne dans `notification_logs` — jamais une erreur
    HTTP sur une opération d'argent déjà validée.

    `entity_id`/`nonce` : la dé-duplication porte sur (organisation, événement,
    entité, canal, destinataire). Un événement qui peut légitimement se répéter
    pour un même encaissement (complément, relance) doit donc apporter lui-même
    de quoi se distinguer, sinon le second envoi serait avalé en silence.
    """
    try:
        ns = await get_system_settings(db, tenant_id)
        if ns is None:
            return
        # Canal fermé pour ce tenant : on sort avant toute autre requête. C'est
        # le chemin le plus fréquent tant que WhatsApp n'est pas activé, et une
        # opération de caisse n'a pas à payer trois SELECT pour rien.
        if not build_whatsapp_settings(ns, "").accepts(event_type):
            return

        org_name = (
            await db.execute(select(Organisation.nom).where(Organisation.id == tenant_id).limit(1))
        ).scalar_one_or_none() or ""
        settings_obj = build_whatsapp_settings(ns, org_name)

        if expert is None and encaissement.expert_comptable_id:
            expert = (
                await db.execute(
                    select(ExpertComptable).where(
                        ExpertComptable.id == encaissement.expert_comptable_id
                    )
                )
            ).scalar_one_or_none()

        client = None
        if getattr(encaissement, "client_id", None):
            client = (
                await db.execute(select(Client).where(Client.id == encaissement.client_id))
            ).scalar_one_or_none()

        # L'expert-comptable prime, sinon le client : même règle que l'email.
        # Le client non-expert n'est plus ignoré, contrairement à l'ancien bloc.
        recipient = resolve_client_recipient(expert=expert, client=client)
        if recipient is None:
            logger.info(
                "WhatsApp : aucun numéro exploitable pour l'encaissement %s", encaissement.id
            )
            return

        total = _clean_money(encaissement.montant_total or 0)
        paye = _clean_money(encaissement.montant_paye or 0)
        reste = total - paye
        if reste < 0:
            reste = Decimal("0")

        date_operation = encaissement.date_paiement or encaissement.date_encaissement

        # `nom` est un repli : `queue_whatsapp` préfère le nom porté par le
        # destinataire, mais `resolve_client_recipient` ne sait pas lire
        # `nom_denomination` (propre à ExpertComptable) ni `client_nom`.
        nom_affiche = (
            (getattr(expert, "nom_denomination", "") or "")
            or (getattr(client, "nom", "") or "")
            or (encaissement.client_nom or "")
        )

        await notify_whatsapp(
            db,
            background_tasks,
            organisation_id=tenant_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id or str(encaissement.id),
            recipients=[recipient],
            variables={
                "nom": str(nom_affiche).strip(),
                "reference": encaissement.numero_recu or encaissement.numero_proforma or "",
                "date": date_operation.strftime("%d/%m/%Y") if date_operation else "",
                # `montant` = ce qui vient d'être encaissé ; à défaut, le
                # montant de la pièce (cas de la relance, où rien n'est reçu).
                "montant": _fmt_montant(total if montant_recu is None else montant_recu),
                "devise": encaissement.devise_perception or "USD",
                "motif": encaissement.libelle or "",
                # `total` = montant total de la pièce (cf. TEMPLATE_VARIABLES).
                "total": _fmt_montant(total),
                "reste_a_payer": _fmt_montant(reste),
                "mode_paiement": _mode_paiement_label(encaissement.mode_paiement),
                "canal": _mode_paiement_label(encaissement.mode_paiement)
                or ("Caisse" if (encaissement.canal or "") == "CAISSE" else "Banque"),
            },
            settings=settings_obj,
            nonce=nonce,
        )
    except Exception:
        # Ceinture et bretelles : `notify_whatsapp` avale déjà tout, mais la
        # résolution du destinataire ci-dessus interroge la base.
        logger.exception(
            "Échec de préparation de la notification WhatsApp (encaissement %s, %s)",
            getattr(encaissement, "id", None),
            event_type,
        )


async def _encaissement_financial_impact(
    db: AsyncSession,
    *,
    encaissement: Encaissement,
    tenant_id: int,
) -> dict[str, Any]:
    montant_paye = _clean_money(encaissement.montant_paye or 0)

    payment_total_res = await db.execute(
        select(func.coalesce(func.sum(PaymentHistory.montant), 0)).where(
            PaymentHistory.organisation_id == tenant_id,
            PaymentHistory.encaissement_id == encaissement.id,
        )
    )
    payment_history_total = _clean_money(payment_total_res.scalar_one() or 0)

    accounting_res = await db.execute(
        select(func.count()).select_from(ComptaEcriture).where(
            ComptaEcriture.organisation_id == tenant_id,
            ComptaEcriture.module_origine == "encaissements",
            ComptaEcriture.type_origine == "encaissement",
            ComptaEcriture.objet_origine_id == str(encaissement.id),
        )
    )
    accounting_entries = int(accounting_res.scalar_one() or 0)

    treasury_movement_recorded = montant_paye > 0 and not encaissement.est_proforma
    budget_execution_recorded = (
        encaissement.budget_poste_id is not None
        and not encaissement.est_proforma
        and (montant_paye > 0 or payment_history_total > 0)
    )

    return {
        "has_impact": any(
            [
                montant_paye > 0,
                payment_history_total > 0,
                accounting_entries > 0,
                treasury_movement_recorded,
                budget_execution_recorded,
            ]
        ),
        "montant_paye": str(montant_paye),
        "payment_history_total": str(payment_history_total),
        "accounting_entries": accounting_entries,
        "treasury_movement_recorded": treasury_movement_recorded,
        "budget_execution_recorded": budget_execution_recorded,
    }


async def _adjust_encaissement_budget_impact(
    db: AsyncSession,
    *,
    encaissement: Encaissement,
    tenant_id: int,
    direction: int,
) -> None:
    if (
        encaissement.budget_poste_id is None
        or encaissement.est_proforma
        or (encaissement.statut_operation or "ACTIVE").upper() != "ACTIVE"
    ):
        return
    montant = _clean_money(encaissement.montant_paye or 0)
    if montant <= 0:
        return
    res = await db.execute(
        select(BudgetPoste)
        .where(
            BudgetPoste.id == encaissement.budget_poste_id,
            BudgetPoste.organisation_id == tenant_id,
        )
        .with_for_update()
    )
    poste = res.scalar_one_or_none()
    if poste is None:
        return
    current = _clean_money(poste.montant_paye or 0)
    next_value = current + (montant * direction)
    poste.montant_paye = max(Decimal("0.00"), _clean_money(next_value))
PIECE_TOO_LARGE_DETAIL = "Fichier trop volumineux (maximum 3 Mo)."
DEFAULT_UPLOAD_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "uploads")
)
# Même racine que secure_uploads.py : les pièces sont servies via
# /api/v1/secure-uploads/ (contrôle de tenant), pas par le montage statique.
PIECE_UPLOAD_ROOT = os.path.abspath(app_settings.upload_dir) if app_settings.upload_dir else DEFAULT_UPLOAD_ROOT


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


async def _user_has_permission(db: AsyncSession, user: User | AuthUser, permission_code: str) -> bool:
    if (user.role or "").lower() in {"admin", "super_admin"}:
        return True
    resolved_permissions = cached_permission_codes(user)
    if resolved_permissions is not None:
        return permission_code in resolved_permissions
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


def _est_hors_budget(enc: Encaissement) -> bool:
    """Vrai pour un encaissement encaissé hors budget, donc encore à imputer."""
    return (getattr(enc, "nature_mouvement", None) or "BUDGETAIRE").upper() == "HORS_BUDGET_A_REGULARISER"


def _encaissement_to_response(
    enc: Encaissement,
    expert: ExpertComptable | None = None,
    *,
    creator: User | None = None,
    canceller: User | None = None,
    montant_affecte_budget: Decimal | None = None,
    fonds_tiers_display_name: str | None = None,
    fonds_tiers_type: str | None = None,
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
        "client_id": str(enc.client_id) if getattr(enc, "client_id", None) else None,
        "relance_count": getattr(enc, "relance_count", 0) or 0,
        "derniere_relance_le": getattr(enc, "derniere_relance_le", None),
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
        "project_activity_id": getattr(enc, "project_activity_id", None),
        "project_activity_name": None,
        "statut_paiement": enc.statut_paiement,
        "nature_mouvement": getattr(enc, "nature_mouvement", None) or "BUDGETAIRE",
        "impact_budgetaire": getattr(enc, "impact_budgetaire", None),
        "hors_budget_status": getattr(enc, "hors_budget_status", None),
        "fonds_tiers_display_name": fonds_tiers_display_name,
        "fonds_tiers_type": fonds_tiers_type,
        # Part déjà imputée au budget par régularisation : c'est elle qui donne
        # le reste à affecter, une régularisation pouvant être partielle.
        "montant_affecte_budget": montant_affecte_budget if montant_affecte_budget is not None else Decimal("0"),
        "statut_operation": enc.statut_operation,
        "statut_comptabilisation": getattr(enc, "statut_comptabilisation", "NON_COMPTABILISEE"),
        "message_comptabilisation": getattr(enc, "message_comptabilisation", None),
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
        "is_deleted": bool(enc.is_deleted),
        "deleted_at": enc.deleted_at,
        "deleted_by": str(enc.deleted_by) if enc.deleted_by else None,
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


async def _fonds_tiers_display_by_encaissement(
    db: AsyncSession,
    *,
    tenant_id: int,
    encaissement_ids: list[uuid.UUID],
) -> dict[uuid.UUID, tuple[str, str]]:
    """Deux lectures au total, quel que soit le nombre d'encaissements : les
    opérations, puis les noms d'organisations en un lot."""
    if not encaissement_ids:
        return {}
    res = await db.execute(
        select(FondsTiersOperation).where(
            FondsTiersOperation.organisation_id == tenant_id,
            FondsTiersOperation.encaissement_id.in_(encaissement_ids),
        )
    )
    operations = res.scalars().all()
    resolved = await resolve_fonds_tiers_display_names(db, operations)
    return {op.encaissement_id: resolved[op.id] for op in operations}


def _est_fonds_de_tiers(mouvement: Any) -> bool:
    return (getattr(mouvement, "nature_mouvement", None) or "").upper() == "FONDS_DE_TIERS"


async def _encaissement_response(
    db: AsyncSession,
    enc: Encaissement,
    expert: ExpertComptable | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Réponse unitaire, nom du tiers compris.

    Les réponses unitaires et la liste alimentent le même cache côté client :
    si seule la liste portait le tiers, le nom apparaîtrait puis disparaîtrait
    au premier rafraîchissement du détail. La lecture supplémentaire n'a lieu
    que pour un fonds de tiers — les autres mouvements n'ont pas de tiers.
    """
    display_name: str | None = None
    tiers_type: str | None = None
    if _est_fonds_de_tiers(enc):
        noms = await _fonds_tiers_display_by_encaissement(
            db,
            tenant_id=enc.organisation_id,
            encaissement_ids=[enc.id],
        )
        display_name, tiers_type = noms.get(enc.id) or (None, None)
    return _encaissement_to_response(
        enc,
        expert,
        fonds_tiers_display_name=display_name,
        fonds_tiers_type=tiers_type,
        **kwargs,
    )


async def _resolve_project_activity(
    db: AsyncSession,
    project_activity_id: int | None,
    tenant_id: int,
) -> int | None:
    if project_activity_id is None:
        return None
    item = await db.scalar(
        select(ProjetActivite).where(
            ProjetActivite.id == project_activity_id,
            ProjetActivite.organisation_id == tenant_id,
            ProjetActivite.is_active.is_(True),
        )
    )
    if item is None:
        raise HTTPException(status_code=400, detail="Projet ou activité invalide ou inactive.")
    return item.id


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
        await db.execute(
            pg_insert(CaisseCentrale)
            .values(organisation_id=tenant_id, solde_usd=0, solde_cdf=0)
            .on_conflict_do_nothing(index_elements=["organisation_id"])
        )
        res = await db.execute(select(CaisseCentrale).where(CaisseCentrale.organisation_id == tenant_id).limit(1))
        caisse = res.scalar_one()
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
    return await generate_document_number(db, doc_type="ND", tenant_id=tenant_id, service_id=None)


@router.post("/generate-numero-recu")
async def generate_numero_recu(
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> str:
    return await _generate_numero_recu(tenant_id=tenant_id, db=db)


@router.get("/verify")
async def verify_encaissement(
    numero_recu: str = Query(..., description="Numéro de note de débit"),
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


@router.get("/suggestions-numero")
async def suggerer_numeros_note_debit(
    q: str = Query(..., min_length=1, description="Numéro, même partiel ou mal ponctué"),
    limit: int = Query(default=8, ge=1, le=20),
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Propose les notes dont le numéro ressemble à ce qui est tapé.

    Le champ « N° Note de débit » filtrait la liste à chaque caractère : l'écran
    se réorganisait sous les doigts, les totaux sautaient, la pagination
    repartait à 1. Cette route sert le même rôle que la recherche de client du
    formulaire — proposer, sans rien changer derrière. Le filtre ne s'applique
    qu'au numéro choisi.

    Elle rend peu de colonnes, et peu de lignes : de quoi reconnaître la bonne
    note (client, montant, date), pas de quoi remplir un écran.
    """
    conditions = [Encaissement.organisation_id == tenant_id]
    # Même restriction que la liste : sans accès au menu, on ne voit que ses
    # services. Une suggestion est une lecture comme une autre — la contourner
    # laisserait deviner l'existence de notes hors de son périmètre.
    if not await has_module_menu_access(db, user, "menu_encaissements"):
        service_ids = await get_user_service_ids(db, user)
        if not service_ids:
            return []
        conditions.append(Encaissement.service_id.in_(service_ids))

    condition_recherche = condition_numero(
        q, Encaissement.numero_recu, Encaissement.numero_proforma
    )
    if condition_recherche is None:
        return []
    conditions.append(condition_recherche)

    if not await _user_has_permission(db, user, "view_cancelled_financial_operations"):
        conditions.append(Encaissement.statut_operation != "ANNULEE")

    res = await db.execute(
        select(Encaissement)
        .where(*conditions, Encaissement.is_deleted.is_(False))
        .order_by(Encaissement.date_encaissement.desc())
        .limit(limit)
    )
    return [
        {
            "numero": enc.numero_recu or enc.numero_proforma or "",
            "est_proforma": bool(enc.est_proforma),
            "client_nom": enc.client_nom or "",
            "montant_total": str(enc.montant_total or 0),
            "devise": enc.devise_perception or "USD",
            "date_encaissement": enc.date_encaissement.isoformat() if enc.date_encaissement else None,
            "statut_paiement": enc.statut_paiement,
        }
        for enc in res.scalars().all()
        if (enc.numero_recu or enc.numero_proforma)
    ]


@router.get("/suggestions-client")
async def suggerer_payeurs(
    q: str = Query(..., min_length=2, description="Nom, dénomination ou numéro d'ordre"),
    limit: int = Query(default=8, ge=1, le=20),
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Propose les payeurs qui ont RÉELLEMENT des encaissements ici.

    Même geste que les propositions de numéro : on tape, on choisit, et c'est le
    choix qui filtre — la liste derrière ne bouge pas pendant la frappe.

    Les propositions viennent des encaissements eux-mêmes, jamais du référentiel
    clients. Un client du référentiel peut n'avoir aucune opération, ou en avoir
    sous un nom orthographié autrement : le proposer mènerait à une liste vide,
    exactement le défaut qu'on cherche à supprimer. Ici, tout ce qui est proposé
    rend au moins une ligne — et le compte annoncé le dit d'avance.

    Le filtre cherche sur trois colonnes (nom saisi, dénomination de l'expert,
    numéro d'ordre) : les propositions couvrent le même terrain, sinon elles
    désigneraient autre chose que ce qu'elles déclenchent.
    """
    terme = q.strip()
    if not terme:
        return []
    motif = f"%{terme}%"

    portee = [Encaissement.organisation_id == tenant_id, Encaissement.is_deleted.is_(False)]
    if not await has_module_menu_access(db, user, "menu_encaissements"):
        service_ids = await get_user_service_ids(db, user)
        if not service_ids:
            return []
        portee.append(Encaissement.service_id.in_(service_ids))
    if not await _user_has_permission(db, user, "view_cancelled_financial_operations"):
        portee.append(Encaissement.statut_operation != "ANNULEE")

    # Les payeurs saisis à la main, groupés sur le nom tel qu'il a été écrit.
    noms = (await db.execute(
        select(
            Encaissement.client_nom,
            func.count().label("nb"),
            func.max(Encaissement.date_encaissement).label("dernier"),
        )
        .where(*portee, Encaissement.client_nom.isnot(None), Encaissement.client_nom.ilike(motif))
        .group_by(Encaissement.client_nom)
        .order_by(func.count().desc())
        .limit(limit)
    )).all()

    # Les experts comptables, atteignables par leur dénomination OU leur numéro
    # d'ordre — c'est ce dernier qu'on retient comme valeur de filtre : il est
    # unique, là où deux experts peuvent porter des dénominations proches.
    experts = (await db.execute(
        select(
            ExpertComptable.nom_denomination,
            ExpertComptable.numero_ordre,
            func.count(Encaissement.id).label("nb"),
            func.max(Encaissement.date_encaissement).label("dernier"),
        )
        .join(ExpertComptable, Encaissement.expert_comptable_id == ExpertComptable.id)
        .where(
            *portee,
            or_(
                ExpertComptable.nom_denomination.ilike(motif),
                ExpertComptable.numero_ordre.ilike(motif),
            ),
        )
        .group_by(ExpertComptable.nom_denomination, ExpertComptable.numero_ordre)
        .order_by(func.count(Encaissement.id).desc())
        .limit(limit)
    )).all()

    propositions = [
        {
            "valeur": ligne.client_nom,
            "libelle": ligne.client_nom,
            "detail": None,
            "type": "client",
            "nb": int(ligne.nb or 0),
            "dernier": ligne.dernier.isoformat() if ligne.dernier else None,
        }
        for ligne in noms
    ] + [
        {
            "valeur": ligne.numero_ordre or ligne.nom_denomination,
            "libelle": ligne.nom_denomination or ligne.numero_ordre or "",
            "detail": ligne.numero_ordre,
            "type": "expert",
            "nb": int(ligne.nb or 0),
            "dernier": ligne.dernier.isoformat() if ligne.dernier else None,
        }
        for ligne in experts
    ]
    propositions.sort(key=lambda p: p["nb"], reverse=True)
    return [p for p in propositions if p["valeur"]][:limit]


@router.get("/entrees-caisse")
async def list_entrees_caisse(
    date_debut: str | None = Query(default=None),
    date_fin: str | None = Query(default=None),
    devise: str | None = Query(default=None, description="USD ou CDF"),
    limit: int = Query(default=200, ge=1, le=1000),
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Entrées de caisse qui ne passent pas par une note de débit.

    Les approvisionnements banque → caisse du chemin historique, et les
    transferts du moteur dédié dont la destination est la caisse. Les premiers
    sont enregistrés comme des sorties du compte bancaire, mais côté caisse ce
    sont bien des entrées — l'écran des encaissements doit pouvoir les montrer
    sans les confondre avec des recettes clients (elles sont donc renvoyées à
    part, et jamais additionnées aux totaux d'encaissements).
    """
    if devise and devise.upper() not in {"USD", "CDF"}:
        raise HTTPException(status_code=400, detail="devise invalide")
    lignes = await list_entrees_internes_caisse(
        db,
        tenant_id=tenant_id,
        date_debut=_parse_datetime(date_debut),
        date_fin=_parse_datetime(date_fin, end_of_day=True),
        devise=devise,
        limit=limit,
    )
    total_usd = sum((l["montant"] for l in lignes if l["devise"] == "USD"), Decimal("0"))
    total_cdf = sum((l["montant"] for l in lignes if l["devise"] == "CDF"), Decimal("0"))
    return {
        "items": [{**ligne, "montant": str(ligne["montant"])} for ligne in lignes],
        "total": len(lignes),
        "total_usd": str(total_usd),
        "total_cdf": str(total_cdf),
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
    deleted_status: str | None = Query(default="all", description="all, active, deleted"),
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
    include_articles = "articles" in include_parts
    needs_expert_join = include_expert or bool(client)

    conditions = [Encaissement.organisation_id == tenant_id]
    op_status = (operation_status or "ACTIVE").strip().upper()
    if op_status not in {"ACTIVE", "ANNULEE", "ALL"}:
        raise HTTPException(status_code=400, detail="operation_status invalide (ACTIVE, ANNULEE, ALL)")
    deleted_filter = (deleted_status if isinstance(deleted_status, str) else "all").strip().lower()
    if deleted_filter not in {"all", "active", "deleted"}:
        raise HTTPException(status_code=400, detail="deleted_status invalide (all, active, deleted)")
    can_view_cancelled = await _user_has_permission(db, user, "view_cancelled_financial_operations")
    if op_status in {"ANNULEE", "ALL"} and not can_view_cancelled:
        raise HTTPException(status_code=403, detail="Privilèges insuffisants (view_cancelled_financial_operations)")

    if not await has_module_menu_access(db, user, "menu_encaissements"):
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
        # Le numéro est comparé sur ses lettres et ses chiffres : un numéro collé
        # depuis un courriel arrive avec des espaces, et recopié à la main il
        # arrive souvent sans ses tirets. Les deux doivent trouver la note.
        # `numero_proforma` est cherché aussi : une pro forma de note de débit
        # porte un numéro que l'utilisateur lit sur le même écran.
        condition_numero_recu = condition_numero(
            numero_recu, Encaissement.numero_recu, Encaissement.numero_proforma
        )
        if condition_numero_recu is not None:
            conditions.append(condition_numero_recu)
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
        query = select(Encaissement, ExpertComptable).outerjoin(
            ExpertComptable, Encaissement.expert_comptable_id == ExpertComptable.id
        )
    else:
        query = select(Encaissement)
    if include_articles:
        query = query.options(selectinload(Encaissement.articles))

    if deleted_filter == "active":
        conditions.append(Encaissement.is_deleted.is_(False))
    elif deleted_filter == "deleted":
        conditions.append(Encaissement.is_deleted.is_(True))
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
        affectations = await sum_active_by_encaissement(
            db,
            organisation_id=tenant_id,
            encaissement_ids=[enc.id for enc, _ in rows if _est_hors_budget(enc)],
        )
        fonds_tiers_names = await _fonds_tiers_display_by_encaissement(
            db,
            tenant_id=tenant_id,
            encaissement_ids=[enc.id for enc, _ in rows if _est_fonds_de_tiers(enc)],
        )
        items = [
            _encaissement_to_response(
                enc,
                expert,
                creator=users_map.get(enc.created_by) if enc.created_by else None,
                canceller=users_map.get(enc.annulee_par_id) if enc.annulee_par_id else None,
                montant_affecte_budget=affectations.get(enc.id),
                fonds_tiers_display_name=fonds_tiers_names.get(enc.id, (None, None))[0],
                fonds_tiers_type=fonds_tiers_names.get(enc.id, (None, None))[1],
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
        affectations = await sum_active_by_encaissement(
            db,
            organisation_id=tenant_id,
            encaissement_ids=[enc.id for enc in encaissements if _est_hors_budget(enc)],
        )
        fonds_tiers_names = await _fonds_tiers_display_by_encaissement(
            db,
            tenant_id=tenant_id,
            encaissement_ids=[enc.id for enc in encaissements if _est_fonds_de_tiers(enc)],
        )
        items = [
            _encaissement_to_response(
                enc,
                creator=users_map.get(enc.created_by) if enc.created_by else None,
                canceller=users_map.get(enc.annulee_par_id) if enc.annulee_par_id else None,
                montant_affecte_budget=affectations.get(enc.id),
                fonds_tiers_display_name=fonds_tiers_names.get(enc.id, (None, None))[0],
                fonds_tiers_type=fonds_tiers_names.get(enc.id, (None, None))[1],
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
    sum_query = sum_query.where(Encaissement.is_deleted.is_(False))

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
    if normalize_nature(payload.nature_mouvement) != "BUDGETAIRE":
        raise HTTPException(status_code=400, detail="Une pro forma est réservée aux encaissements budgétaires")

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

    nature_mouvement = normalize_nature(payload.nature_mouvement)
    if nature_mouvement == "TRANSFERT_INTERNE":
        raise HTTPException(status_code=400, detail="Un encaissement ne crée pas un transfert interne")

    expert_uid: uuid.UUID | None = None
    if payload.type_client == "expert_comptable":
        if not payload.expert_comptable_id:
            raise HTTPException(status_code=400, detail="expert_comptable_id requis")
        expert_uid = payload.expert_comptable_id
        res = await db.execute(select(ExpertComptable).where(ExpertComptable.id == expert_uid))
        if not res.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Expert-comptable non trouvé")
    elif nature_mouvement != "FONDS_DE_TIERS":
        if not payload.client_id and (not payload.client_nom or not payload.client_nom.strip()):
            raise HTTPException(status_code=400, detail="client_nom requis pour ce type_client")

    # Référentiel clients : retrouve ou crée la fiche (anti-doublons).
    proforma_client_id = await _resolve_or_create_client(db, tenant_id, payload, current_user_id)

    if payload.budget_poste_id is None:
        raise HTTPException(status_code=400, detail="budget_poste_id requis pour une pro forma de note de débit")

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

    date_emission = payload.date_encaissement
    if isinstance(date_emission, str):
        parsed = _parse_datetime(date_emission)
        if not parsed:
            raise HTTPException(status_code=400, detail="date_encaissement invalide")
        date_emission = parsed
    # L'horloge du serveur fait foi, sauf pour un super administrateur.
    date_emission = resoudre_date_operation(
        date_emission, user=user, champ="date_encaissement"
    )

    numero_proforma = await generate_document_number(
        db, doc_type="PF-ND", tenant_id=tenant_id, service_id=None
    )

    project_activity_id = await _resolve_project_activity(db, payload.project_activity_id, tenant_id)
    encaissement = Encaissement(
        numero_recu=None,
        numero_proforma=numero_proforma,
        est_proforma=True,
        source_proforma_id=None,
        organisation_id=tenant_id,
        type_client=payload.type_client,
        expert_comptable_id=expert_uid,
        client_nom=None if payload.type_client == "expert_comptable" else payload.client_nom,
        client_id=proforma_client_id,
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
        project_activity_id=project_activity_id,
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

    return await _encaissement_response(db, encaissement, expert)


async def _resolve_or_create_client(
    db: AsyncSession,
    tenant_id: int,
    payload: EncaissementCreate,
    user_id: uuid.UUID | None,
) -> uuid.UUID | None:
    """Référentiel clients (anti-doublons).

    - client_id fourni → réutilise la fiche existante (et la complète si
      email/téléphone sont fournis et absents de la fiche).
    - sinon, get-or-create sur lower(nom) : un client qui revient après des
      mois est retrouvé au lieu d'être dupliqué.
    Ne s'applique pas aux experts-comptables (référentiel séparé).
    """
    if payload.type_client == "expert_comptable":
        return None
    email = (payload.client_email or "").strip() or None
    telephone = (payload.client_telephone or "").strip() or None

    client: Client | None = None
    if payload.client_id:
        res = await db.execute(
            select(Client).where(
                Client.id == payload.client_id,
                Client.organisation_id == tenant_id,
            )
        )
        client = res.scalar_one_or_none()
        if client is None:
            raise HTTPException(status_code=404, detail="Client introuvable")
    else:
        nom = (payload.client_nom or "").strip()
        if not nom:
            return None
        res = await db.execute(
            select(Client).where(
                Client.organisation_id == tenant_id,
                func.lower(Client.nom) == nom.lower(),
            )
        )
        client = res.scalar_one_or_none()
        if client is None:
            client = Client(
                organisation_id=tenant_id,
                nom=nom,
                type_client=payload.type_client,
                email=email,
                telephone=telephone,
                active=True,
                created_by=user_id,
            )
            db.add(client)
            await db.flush()

    # Compléter la fiche sans écraser l'existant.
    if email and not client.email:
        client.email = email
    if telephone and not client.telephone:
        client.telephone = telephone
    if payload.type_client and not client.type_client:
        client.type_client = payload.type_client
    client.updated_at = datetime.now(timezone.utc)
    # Snapshot du nom canonique sur l'encaissement.
    payload.client_nom = client.nom
    return client.id


@router.post("", response_model=EncaissementResponse, status_code=status.HTTP_201_CREATED)
async def create_encaissement(
    payload: EncaissementCreate,
    background_tasks: BackgroundTasks,
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
    initial_montant_paye = montant_paye
    article_payloads = _normalize_article_payloads(payload, montant_total)

    nature_mouvement = normalize_nature(payload.nature_mouvement)
    if nature_mouvement == "TRANSFERT_INTERNE":
        raise HTTPException(status_code=400, detail="Un encaissement ne crée pas un transfert interne")

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
    elif nature_mouvement != "FONDS_DE_TIERS":
        if not payload.client_id and (not payload.client_nom or not payload.client_nom.strip()):
            raise HTTPException(status_code=400, detail="client_nom requis pour ce type_client")

    impact_budgetaire = impact_for_nature(nature_mouvement)
    if payload.impact_budgetaire is not None and bool(payload.impact_budgetaire) != impact_budgetaire:
        raise HTTPException(status_code=400, detail="impact_budgetaire incompatible avec nature_mouvement")
    if nature_mouvement == "FONDS_DE_TIERS" and payload.fonds_tiers is None:
        raise HTTPException(status_code=400, detail="fonds_tiers requis pour un fonds de tiers")
    if nature_mouvement != "FONDS_DE_TIERS" and payload.fonds_tiers is not None:
        raise HTTPException(status_code=400, detail="fonds_tiers réservé aux mouvements FONDS_DE_TIERS")
    if nature_mouvement == "FONDS_DE_TIERS" and initial_montant_paye <= 0:
        raise HTTPException(status_code=400, detail="Un fonds de tiers doit être encaissé immédiatement")

    budget_line = None
    budget_poste_code = None
    budget_poste_libelle = None
    budget_line_id = None
    if impact_budgetaire:
        if payload.budget_poste_id is None:
            raise HTTPException(status_code=400, detail="budget_poste_id requis pour un encaissement budgétaire")
        budget_res = await db.execute(
            select(BudgetPoste).where(
                BudgetPoste.id == payload.budget_poste_id,
                BudgetPoste.organisation_id == tenant_id,
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
    elif payload.budget_poste_id is not None:
        raise HTTPException(status_code=400, detail="Un mouvement sans impact budgétaire ne doit pas porter de poste budgétaire")

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

    if service_id is not None and budget_line is not None:
        allowed_res = await db.execute(
            select(ServiceRubrique)
            .where(
                ServiceRubrique.service_id == service_id,
                ServiceRubrique.budget_poste_id == budget_line.id,
            )
        )
        if allowed_res.scalar_one_or_none() is None:
            raise HTTPException(status_code=403, detail="Rubrique non autorisée pour ce service")

    date_encaissement = payload.date_encaissement
    if isinstance(date_encaissement, str):
        parsed = _parse_datetime(date_encaissement)
        if not parsed:
            raise HTTPException(status_code=400, detail="date_encaissement invalide")
        date_encaissement = parsed
    # L'horloge du serveur fait foi, sauf pour un super administrateur.
    date_encaissement = resoudre_date_operation(
        date_encaissement, user=user, champ="date_encaissement"
    )

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
            detail=f"Un encaissement similaire existe déjà pour cette opération (note de débit {duplicate.numero_recu or '—'}).",
        )

    allow_custom_recu = (user.role or "").lower() == "super_admin"
    provided_recu = payload.numero_recu.strip() if allow_custom_recu and payload.numero_recu else ""
    should_regenerate = not provided_recu
    last_error: Exception | None = None
    max_attempts = 50

    for attempt in range(max_attempts):
        numero_recu = provided_recu or await _generate_numero_recu(tenant_id=tenant_id, db=db)
        # Référentiel clients (anti-doublons), résolu DANS la boucle : un rollback
        # de retry (numéro dupliqué) annulerait une fiche créée avant la boucle,
        # laissant un client_id orphelin → violation FK. On la (re)crée ici.
        client_id = await _resolve_or_create_client(db, tenant_id, payload, current_user_id)
        project_activity_id = await _resolve_project_activity(db, payload.project_activity_id, tenant_id)
        encaissement = Encaissement(
            numero_recu=numero_recu,
            numero_proforma=None,
            est_proforma=False,
            source_proforma_id=None,
            organisation_id=tenant_id,
            type_client=payload.type_client,
            expert_comptable_id=expert_uid,
            client_nom=None if payload.type_client == "expert_comptable" else payload.client_nom,
            client_id=client_id,
            libelle=payload.libelle.strip(),
            description=payload.description,
            montant=montant,
            montant_total=montant_total,
            montant_paye=Decimal("0.00"),
            montant_percu=Decimal("0.00"),
            devise_perception=devise,
            taux_change_applique=taux_change,
            budget_poste_id=payload.budget_poste_id,
            budget_poste_code=budget_poste_code,
            budget_poste_libelle=budget_poste_libelle,
            service_id=service_id,
            project_activity_id=project_activity_id,
            statut_paiement="non_paye",
            mode_paiement=payload.mode_paiement,
            nature_mouvement=nature_mouvement,
            impact_budgetaire=impact_budgetaire,
            hors_budget_status=hors_budget_initial_status(nature_mouvement),
            reference=payload.reference,
            canal=canal,
            compte_bancaire_id=payload.compte_bancaire_id,
            piece_jointe=payload.piece_jointe,
            date_encaissement=date_encaissement,
            date_paiement=None,
            created_by=current_user_id,
        )
        db.add(encaissement)
        try:
            # Ensure encaissement.id is generated before creating payment history (FK not null).
            await db.flush()
            if nature_mouvement == "FONDS_DE_TIERS" and payload.fonds_tiers is not None:
                await create_fonds_tiers_operation(
                    db,
                    organisation_id=tenant_id,
                    encaissement=encaissement,
                    tiers_organisation_id=payload.fonds_tiers.tiers_organisation_id,
                    tiers_nom_libre=payload.fonds_tiers.tiers_nom_libre,
                    payeur_origine=payload.fonds_tiers.payeur_origine,
                    motif=payload.fonds_tiers.motif,
                    reference=payload.fonds_tiers.reference,
                    piece_justificative=payload.fonds_tiers.piece_justificative,
                    created_by=current_user_id,
                )
            _add_encaissement_articles(db, encaissement, tenant_id, article_payloads)
            if initial_montant_paye > 0:
                notes_paiement = None
                if payload.notes_paiement and payload.notes_paiement.strip():
                    notes_paiement = payload.notes_paiement.strip()
                await record_encaissement_payment(
                    db,
                    organisation_id=tenant_id,
                    encaissement_id=encaissement.id,
                    montant=initial_montant_paye,
                    mode_paiement=payload.mode_paiement,
                    reference=payload.reference,
                    notes=notes_paiement,
                    user_id=current_user_id,
                    date_paiement=date_encaissement,
                )

            await db.commit()
            await invalidate_report_summary_cache(tenant_id)
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
            if constraint in ("ck_encaissements_mode_paiement", "ck_payment_history_mode_paiement"):
                # Détail technique (migration à appliquer) réservé aux logs :
                # ne pas exposer la structure SQL au client.
                logger.error(
                    "Contrainte de mode de paiement violée (%s) — migration backend requise: %s",
                    constraint,
                    exc,
                    exc_info=True,
                )
                raise HTTPException(
                    status_code=500,
                    detail="Erreur de configuration côté serveur. Contactez l'administrateur.",
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

    # Note de débit par email au client (expert-comptable ou client externe), avec le
    # reste à payer le cas échéant.
    if montant_paye > 0:
        await schedule_client_payment_email(db, background_tasks, encaissement, tenant_id)

    expert = None
    if expert_uid:
        res = await db.execute(select(ExpertComptable).where(ExpertComptable.id == expert_uid))
        expert = res.scalar_one_or_none()

    # Accusé de réception WhatsApp, aux mêmes conditions que l'email ci-dessus :
    # une note de débit sans paiement immédiat ne notifie personne.
    if montant_paye > 0:
        await _notify_paiement_whatsapp(
            db,
            background_tasks,
            encaissement=encaissement,
            tenant_id=tenant_id,
            event_type=PAYMENT_RECEIVED,
            expert=expert,
            montant_recu=montant_paye,
        )

    return await _encaissement_response(db, encaissement, expert)


@router.post("/{encaissement_id}/affecter-budget", dependencies=[Depends(has_permission("budget"))])
async def affecter_encaissement_budget(
    encaissement_id: str,
    payload: AffecterBudgetPayload,
    request: Request,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        encaissement_uid = uuid.UUID(encaissement_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="encaissement_id invalide")
    regularisation = await affecter_encaissement_hors_budget(
        db,
        organisation_id=tenant_id,
        encaissement_id=encaissement_uid,
        lignes=[(ligne.budget_poste_id, ligne.montant) for ligne in payload.lignes],
        justification=payload.justification,
        reference=payload.reference,
        idempotency_key=payload.idempotency_key,
        user_id=user.id,
    )
    await log_action(
        db,
        user_id=user.id,
        action="ENCAISSEMENT_HORS_BUDGET_AFFECTE",
        target_table="regularisations_budgetaires",
        target_id=str(regularisation.id),
        new_value={
            "encaissement_id": encaissement_id,
            "montant": str(regularisation.montant_mouvement),
            "reference": regularisation.reference,
        },
        ip_address=get_request_ip(request),
    )
    await db.commit()
    await invalidate_report_summary_cache(tenant_id)
    return {"id": str(regularisation.id), "status": "ok"}


@router.get("/{encaissement_id}/pieces-justificatives")
async def list_pieces_justificatives(
    encaissement_id: str,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    try:
        enc_id = uuid.UUID(encaissement_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Identifiant d'encaissement invalide") from exc
    exists = await db.scalar(select(Encaissement.id).where(Encaissement.id == enc_id, Encaissement.organisation_id == tenant_id))
    if exists is None:
        raise HTTPException(status_code=404, detail="Encaissement introuvable")
    result = await db.execute(
        select(EncaissementPieceJointe)
        .where(EncaissementPieceJointe.encaissement_id == enc_id, EncaissementPieceJointe.organisation_id == tenant_id)
        .order_by(EncaissementPieceJointe.uploaded_at.asc())
    )
    return [
        {
            "id": str(item.id),
            "original_name": item.original_name,
            "mime_type": item.mime_type,
            "size_bytes": item.size_bytes,
            "uploaded_by": str(item.uploaded_by) if item.uploaded_by else None,
            "uploaded_at": item.uploaded_at,
            "path": item.stored_path,
        }
        for item in result.scalars().all()
    ]


@router.post("/{encaissement_id}/pieces-justificatives", status_code=status.HTTP_201_CREATED)
async def upload_piece_justificative(
    encaissement_id: str,
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if content_length_exceeds(request.headers.get("content-length"), PIECE_MAX_SIZE_WITH_OVERHEAD):
        raise HTTPException(status_code=400, detail=PIECE_TOO_LARGE_DETAIL)
    try:
        enc_id = uuid.UUID(encaissement_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Identifiant d'encaissement invalide") from exc
    encaissement = await db.scalar(
        select(Encaissement).where(
            Encaissement.id == enc_id,
            Encaissement.organisation_id == tenant_id,
            Encaissement.is_deleted.is_(False),
        )
    )
    if encaissement is None:
        raise HTTPException(status_code=404, detail="Encaissement introuvable")

    content_type = (file.content_type or "").lower()
    original_name = file.filename or "piece-justificative"
    extension = os.path.splitext(original_name)[1].lower()
    if content_type not in PIECE_ALLOWED_TYPES or extension not in PIECE_ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=PIECE_FORMAT_DETAIL)
    contents = await read_upload_limited(file, PIECE_MAX_SIZE, error_detail=PIECE_TOO_LARGE_DETAIL)
    # Content-Type et extension sont déclarés par le client : on confirme le
    # format sur la signature binaire réelle du fichier.
    if not matches_declared_type(contents, content_type):
        raise HTTPException(status_code=400, detail=PIECE_FORMAT_DETAIL)

    organisation = await db.scalar(select(Organisation).where(Organisation.id == tenant_id))
    if organisation is None:
        raise HTTPException(status_code=400, detail="Organisation introuvable")
    now = datetime.now(timezone.utc)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", os.path.basename(original_name)).strip(".-") or "piece"
    filename = f"{encaissement.numero_recu or encaissement.numero_proforma or enc_id}-piece-{uuid.uuid4().hex}{extension}"
    target_dir = os.path.join(PIECE_UPLOAD_ROOT, "tenants", str(organisation.uuid), "encaissements", f"{now.year:04d}", f"{now.month:02d}")
    os.makedirs(target_dir, exist_ok=True)
    fs_path = os.path.join(target_dir, filename)
    with open(fs_path, "wb") as handle:
        handle.write(contents)
    stored_path = f"/uploads/tenants/{organisation.uuid}/encaissements/{now.year:04d}/{now.month:02d}/{filename}"
    piece = EncaissementPieceJointe(
        organisation_id=tenant_id,
        encaissement_id=enc_id,
        original_name=safe_name,
        stored_path=stored_path,
        mime_type=content_type,
        size_bytes=len(contents),
        uploaded_by=user.id,
        uploaded_at=now,
    )
    db.add(piece)
    await db.flush()
    await log_action(
        db,
        user_id=user.id,
        action="ENCAISSEMENT_PIECE_JOINTE_AJOUTEE",
        target_table="encaissements",
        target_id=str(enc_id),
        new_value={"piece_id": str(piece.id), "nom": safe_name, "taille": len(contents), "type": content_type},
    )
    await db.commit()
    return {
        "id": str(piece.id),
        "original_name": piece.original_name,
        "mime_type": piece.mime_type,
        "size_bytes": piece.size_bytes,
        "uploaded_at": piece.uploaded_at,
        "path": piece.stored_path,
    }


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
        raise HTTPException(status_code=400, detail="Cet encaissement n'est pas une pro forma de note de débit")

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
    encaissement.montant_paye = Decimal("0.00")
    encaissement.montant_percu = Decimal("0.00")
    encaissement.statut_paiement = "non_paye"

    notes_paiement = None
    if payload.notes_paiement and payload.notes_paiement.strip():
        notes_paiement = payload.notes_paiement.strip()

    await record_encaissement_payment(
        db,
        organisation_id=tenant_id,
        encaissement_id=encaissement.id,
        montant=montant_paye,
        mode_paiement=mode_paiement,
        reference=payload.reference or encaissement.reference,
        notes=notes_paiement,
        user_id=getattr(user, "id", None),
        date_paiement=date_paiement,
    )

    await db.commit()
    await invalidate_report_summary_cache(tenant_id)
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

    # Note de débit par email au client, avec le reste à payer le cas échéant.
    await schedule_client_payment_email(db, background_tasks, encaissement, tenant_id)

    # WhatsApp : le bloc artisanal qui vivait ici est absorbé par le service.
    # Trois différences voulues — le client non-expert n'est plus ignoré, la clé
    # API n'est plus lue en clair (elle est chiffrée depuis la migration
    # 20260823_whatsapp_notifs), et l'envoi laisse une trace dans
    # `notification_logs` au lieu de disparaître dans un `logger.exception`.
    await _notify_paiement_whatsapp(
        db,
        background_tasks,
        encaissement=encaissement,
        tenant_id=tenant_id,
        event_type=PAYMENT_PROFORMA_CONVERTED,
        expert=expert,
        montant_recu=montant_paye,
    )

    return await _encaissement_response(db, encaissement, expert)


@router.post("/{encaissement_id}/relance-solde")
async def relancer_solde_client(
    encaissement_id: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Relance par email un client qui n'a pas soldé son paiement."""
    try:
        uid = uuid.UUID(encaissement_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid encaissement_id UUID")

    res = await db.execute(
        select(Encaissement).where(
            Encaissement.id == uid,
            Encaissement.organisation_id == tenant_id,
            Encaissement.is_deleted.is_(False),
        )
    )
    encaissement = res.scalar_one_or_none()
    if encaissement is None:
        raise HTTPException(status_code=404, detail="Encaissement introuvable")
    if str(encaissement.statut_operation or "ACTIVE").upper() == "ANNULEE":
        raise HTTPException(status_code=400, detail="Opération annulée : relance impossible")

    reste = float(encaissement.montant_total or 0) - float(encaissement.montant_paye or 0)
    if reste <= 0.009:
        raise HTTPException(status_code=400, detail="Aucun solde restant : cette note de débit est déjà soldée")

    # --- Encadrement des relances : plafond et délai minimum. Sans cela,
    # un même client pourrait être relancé indéfiniment.
    relances_envoyees = int(encaissement.relance_count or 0)
    if relances_envoyees >= MAX_RELANCES_PAR_RECU:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Limite atteinte : {MAX_RELANCES_PAR_RECU} relances ont déjà été envoyées "
                "pour cette note de débit. Envisagez un contact direct ou une autre procédure de recouvrement."
            ),
        )
    if encaissement.derniere_relance_le is not None:
        derniere = encaissement.derniere_relance_le
        if derniere.tzinfo is None:
            derniere = derniere.replace(tzinfo=timezone.utc)
        ecart = datetime.now(timezone.utc) - derniere
        if ecart.days < RELANCE_DELAI_MIN_JOURS:
            restant_jours = RELANCE_DELAI_MIN_JOURS - ecart.days
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Relance déjà envoyée le {derniere.strftime('%d/%m/%Y')}. "
                    f"Prochaine relance possible dans {restant_jours} jour{'s' if restant_jours > 1 else ''} "
                    f"(délai minimum : {RELANCE_DELAI_MIN_JOURS} jours)."
                ),
            )

    # Envoi synchrone : la relance n'est comptée que si l'email part réellement.
    email = await schedule_client_payment_email(
        db, background_tasks, encaissement, tenant_id, relance=True, send_now=True
    )
    if not email:
        raise HTTPException(
            status_code=400,
            detail=(
                "Relance non envoyée : le client n'a pas d'adresse email enregistrée, "
                "le SMTP n'est pas configuré, ou l'envoi a échoué. Vérifiez la fiche client "
                "et la configuration email, puis réessayez."
            ),
        )

    encaissement.relance_count = relances_envoyees + 1
    encaissement.derniere_relance_le = datetime.now(timezone.utc)

    await log_action(
        db,
        user_id=user.id,
        action="ENCAISSEMENT_RELANCE_SOLDE",
        target_table="encaissements",
        target_id=str(encaissement.id),
        new_value={
            "numero_recu": encaissement.numero_recu,
            "email": email,
            "reste": round(reste, 2),
            "relance_numero": encaissement.relance_count,
        },
        ip_address=None,
    )
    await db.commit()

    # Relance WhatsApp, en doublon volontaire de l'email : deux canaux pour un
    # même rappel de solde. Contrairement à l'email ci-dessus, celle-ci n'est
    # PAS bloquante — un échec WhatsApp ne doit ni annuler la relance déjà
    # comptée ni renvoyer une erreur au caissier. Le `nonce` porte le numéro de
    # relance : sans lui, la dé-duplication (organisation, événement, entité,
    # canal, destinataire) avalerait en silence les relances 2 et 3.
    await _notify_paiement_whatsapp(
        db,
        background_tasks,
        encaissement=encaissement,
        tenant_id=tenant_id,
        event_type=PAYMENT_REMINDER,
        nonce=f"relance-{encaissement.relance_count}",
    )

    return {
        "detail": (
            f"Relance {encaissement.relance_count}/{MAX_RELANCES_PAR_RECU} envoyée à {email}"
        ),
        "email": email,
        "reste": round(reste, 2),
        "relance_count": encaissement.relance_count,
        "max_relances": MAX_RELANCES_PAR_RECU,
    }


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
            )
        )
        row = result.first()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encaissement non trouvé")
        enc, expert = row
        if (enc.statut_operation or "ACTIVE").upper() == "ANNULEE" and not can_view_cancelled:
            raise HTTPException(status_code=403, detail="Privilèges insuffisants (view_cancelled_financial_operations)")
        return await _encaissement_response(db, enc, expert)

    result = await db.execute(
        select(Encaissement).options(selectinload(Encaissement.articles)).where(
            Encaissement.id == uid,
            Encaissement.organisation_id == tenant_id,
        )
    )
    encaissement = result.scalar_one_or_none()
    if not encaissement:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encaissement non trouvé")
    if (encaissement.statut_operation or "ACTIVE").upper() == "ANNULEE" and not can_view_cancelled:
        raise HTTPException(status_code=403, detail="Privilèges insuffisants (view_cancelled_financial_operations)")
    return await _encaissement_response(db, encaissement)


@router.post("/{encaissement_id}/soft-delete", response_model=EncaissementResponse)
async def soft_delete_encaissement(
    encaissement_id: str,
    request: Request,
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
        ).with_for_update()
    )
    encaissement = result.scalar_one_or_none()
    if not encaissement:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encaissement non trouvé")

    old_value = {
        "is_deleted": encaissement.is_deleted,
        "deleted_at": encaissement.deleted_at.isoformat() if encaissement.deleted_at else None,
        "deleted_by": str(encaissement.deleted_by) if encaissement.deleted_by else None,
        "montant_paye": str(_clean_money(encaissement.montant_paye or 0)),
        "budget_poste_id": encaissement.budget_poste_id,
    }
    encaissement.is_deleted = True
    encaissement.deleted_at = datetime.now(timezone.utc)
    encaissement.deleted_by = user.id
    await _adjust_encaissement_budget_impact(db, encaissement=encaissement, tenant_id=tenant_id, direction=-1)
    await log_action(
        db,
        user_id=user.id,
        action="ENCAISSEMENT_SOFT_DELETED",
        target_table="encaissements",
        target_id=str(encaissement.id),
        old_value=old_value,
        new_value={
            "is_deleted": encaissement.is_deleted,
            "deleted_at": encaissement.deleted_at.isoformat() if encaissement.deleted_at else None,
            "deleted_by": str(encaissement.deleted_by),
            "financial_active_impact": "0.00",
        },
        ip_address=get_request_ip(request),
    )
    await db.commit()
    await invalidate_report_summary_cache(tenant_id)
    await db.refresh(encaissement)
    return await _encaissement_response(db, encaissement)


@router.post("/{encaissement_id}/restore", response_model=EncaissementResponse)
async def restore_encaissement(
    encaissement_id: str,
    request: Request,
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
        ).with_for_update()
    )
    encaissement = result.scalar_one_or_none()
    if not encaissement:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encaissement non trouvé")

    old_value = {
        "is_deleted": encaissement.is_deleted,
        "deleted_at": encaissement.deleted_at.isoformat() if encaissement.deleted_at else None,
        "deleted_by": str(encaissement.deleted_by) if encaissement.deleted_by else None,
        "montant_paye": str(_clean_money(encaissement.montant_paye or 0)),
        "budget_poste_id": encaissement.budget_poste_id,
    }
    encaissement.is_deleted = False
    encaissement.deleted_at = None
    encaissement.deleted_by = None
    await _adjust_encaissement_budget_impact(db, encaissement=encaissement, tenant_id=tenant_id, direction=1)
    await log_action(
        db,
        user_id=user.id,
        action="ENCAISSEMENT_RESTORED",
        target_table="encaissements",
        target_id=str(encaissement.id),
        old_value=old_value,
        new_value={
            "is_deleted": encaissement.is_deleted,
            "deleted_at": None,
            "deleted_by": None,
            "financial_active_impact": str(_clean_money(encaissement.montant_paye or 0)),
        },
        ip_address=get_request_ip(request),
    )
    await db.commit()
    await invalidate_report_summary_cache(tenant_id)
    await db.refresh(encaissement)
    return await _encaissement_response(db, encaissement)


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pro forma de note de débit non trouvée")

    encaissement.is_deleted = True
    encaissement.deleted_at = datetime.now(timezone.utc)
    encaissement.deleted_by = user.id
    await db.commit()
    await db.refresh(encaissement)
    return await _encaissement_response(db, encaissement)


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
        ).with_for_update()
    )
    encaissement = result.scalar_one_or_none()
    if not encaissement:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encaissement non trouvé")
    if (encaissement.statut_operation or "ACTIVE").upper() == "ANNULEE":
        raise HTTPException(status_code=400, detail="Cet encaissement est déjà annulé")
    if (getattr(encaissement, "nature_mouvement", "") or "").upper() == "FONDS_DE_TIERS":
        await assert_fonds_tiers_origin_can_be_cancelled(
            db,
            organisation_id=tenant_id,
            encaissement_id=encaissement.id,
        )

    active_payments = (
        await db.execute(
            select(PaymentHistory)
            .where(
                PaymentHistory.encaissement_id == encaissement.id,
                PaymentHistory.organisation_id == tenant_id,
                PaymentHistory.statut == "ACTIF",
            )
            .order_by(PaymentHistory.created_at.asc())
        )
    ).scalars().all()
    payment_ids = [str(payment.id) for payment in active_payments]
    payment_ecriture_count = 0
    if payment_ids:
        payment_ecriture_count = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(ComptaEcriture)
                    .where(
                        ComptaEcriture.organisation_id == tenant_id,
                        ComptaEcriture.module_origine == "encaissements",
                        ComptaEcriture.type_origine == "payment_history",
                        ComptaEcriture.objet_origine_id.in_(payment_ids),
                    )
                )
            ).scalar_one()
            or 0
        )
    montant_paye = _clean_money(encaissement.montant_paye or 0)
    # Imputations portées par l'encaissement lui-même : elles viennent d'une
    # régularisation budgétaire, jamais d'un paiement. Elles doivent être
    # reprises que l'encaissement ait ou non des paiements actifs — sinon le
    # poste reste crédité d'un encaissement annulé.
    cancelled_persisted = await cancel_budget_imputations(
        db,
        organisation_id=tenant_id,
        encaissement_id=encaissement.id,
        user_id=user.id,
    )
    if active_payments:
        for payment in active_payments:
            await cancel_encaissement_payment(
                db,
                organisation_id=tenant_id,
                payment_id=payment.id,
                motif_annulation=payload.motif_annulation.strip(),
                user_id=user.id,
                ip_address=get_request_ip(request),
            )
        if payment_ecriture_count == 0:
            await annuler_ecriture_operation(
                db,
                organisation_id=tenant_id,
                module_origine="encaissements",
                type_origine="encaissement",
                objet_origine_id=str(encaissement.id),
                motif=payload.motif_annulation.strip() or f"Annulation de l'encaissement {encaissement.numero_recu}",
                user_id=user.id,
            )
    else:
        if montant_paye > 0 and encaissement.canal == "CAISSE":
            caisse = await _get_or_create_caisse(db, tenant_id)
            res = await db.execute(
                select(CaisseCentrale)
                .where(CaisseCentrale.id == caisse.id, CaisseCentrale.organisation_id == tenant_id)
                .with_for_update()
            )
            caisse = res.scalar_one()
            solde_courant = _clean_money(
                (caisse.solde_usd if encaissement.devise_perception == "USD" else caisse.solde_cdf) or 0
            )
            if montant_paye > solde_courant:
                raise HTTPException(
                    status_code=400,
                    detail="Solde caisse insuffisant pour neutraliser exactement cet encaissement.",
                )
            if encaissement.devise_perception == "USD":
                caisse.solde_usd = solde_courant - montant_paye
            else:
                caisse.solde_cdf = solde_courant - montant_paye
            caisse.derniere_maj = datetime.now(timezone.utc)
        elif montant_paye > 0 and encaissement.compte_bancaire_id:
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
            solde_courant = _clean_money(compte_bancaire.solde_actuel or 0)
            if montant_paye > solde_courant:
                raise HTTPException(
                    status_code=400,
                    detail="Solde bancaire insuffisant pour neutraliser exactement cet encaissement.",
                )
            compte_bancaire.solde_actuel = solde_courant - montant_paye
        if not cancelled_persisted and encaissement.budget_poste_id and montant_paye > 0:
            budget_res = await db.execute(
                select(BudgetPoste)
                .where(
                    BudgetPoste.id == encaissement.budget_poste_id,
                    BudgetPoste.organisation_id == tenant_id,
                )
                .with_for_update()
            )
            budget_poste = budget_res.scalar_one_or_none()
            if budget_poste is None:
                raise HTTPException(status_code=400, detail="Poste budgétaire introuvable pour annuler cet encaissement")
            montant_budget_execute = _clean_money(budget_poste.montant_paye or 0)
            if montant_paye > montant_budget_execute:
                raise HTTPException(
                    status_code=400,
                    detail="Exécution budgétaire insuffisante pour neutraliser exactement cet encaissement.",
                )
            budget_poste.montant_paye = montant_budget_execute - montant_paye
        await annuler_ecriture_operation(
            db,
            organisation_id=tenant_id,
            module_origine="encaissements",
            type_origine="encaissement",
            objet_origine_id=str(encaissement.id),
            motif=payload.motif_annulation.strip() or f"Annulation de l'encaissement {encaissement.numero_recu}",
            user_id=user.id,
        )
        encaissement.montant_paye = Decimal("0.00")
        encaissement.montant_percu = Decimal("0.00")
        encaissement.statut_paiement = "non_paye"

    previous_status = encaissement.statut_operation or "ACTIVE"
    encaissement.ancien_statut_operation = previous_status
    encaissement.statut_operation = "ANNULEE"
    encaissement.motif_annulation = payload.motif_annulation.strip()
    encaissement.annulee_le = datetime.now(timezone.utc)
    encaissement.annulee_par_id = user.id
    encaissement.annulation_ip = get_request_ip(request)
    if (getattr(encaissement, "nature_mouvement", "") or "BUDGETAIRE").upper() != "BUDGETAIRE":
        encaissement.hors_budget_status = "ANNULE"

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
            "montant_redebite": float(montant_paye),
        },
        ip_address=get_request_ip(request),
    )
    await db.commit()
    await invalidate_report_summary_cache(tenant_id)
    await db.refresh(encaissement)
    return await _encaissement_response(db, encaissement)
