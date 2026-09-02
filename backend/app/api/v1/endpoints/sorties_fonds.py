from __future__ import annotations

import uuid
import hashlib
import json
from datetime import datetime, timezone, timedelta
import logging
import os
import re
from typing import Any
import uuid as uuid_lib
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, HTTPException, Query, UploadFile, status, Request
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_current_tenant_id,
    get_current_tenant_uuid,
    has_permission,
)
from app.core.config import settings
from app.core.horodatage import resoudre_date_operation
from app.db.session import get_db
from app.models.budget import BudgetPoste
from app.models.ligne_requisition import LigneRequisition
from app.models.cloture_caisse import ClotureCaisse
from app.models.caisse_centrale import CaisseCentrale
from app.models.print_settings import PrintSettings
from app.models.ordre_decaissement import OrdreDecaissement
from app.models.requisition import Requisition
from app.models.retour_caisse import RetourCaisse
from app.models.sortie_fonds import SortieFonds
from app.models.banque import Banque
from app.models.compte_bancaire import CompteBancaire
from app.models.system_settings import SystemSettings
from app.models.organisation import Organisation
from app.models.user import User
from app.models.service import Service
from app.models.remboursement_transport import RemboursementTransport
from app.models.rbac import Permission, role_permissions
from app.modules.comptabilite.services.generation_service import (
    annuler_ecriture_operation,
    generer_ecriture_sortie_fonds,
    generer_ecriture_transfert_interne,
)
from app.modules.comptabilite.services.integration_mode import (
    STATUT_COMPTABILISEE,
    get_accounting_integration_mode,
    is_accounting_automatic,
    status_for_recorded_operation,
)
from app.schemas.requisition import RequisitionOut, RequisitionWithUserOut
from app.schemas.transfert import TransfertInterneCreate
# Payload d'affectation budgétaire : la même forme sert aux recettes
# (encaissements) et aux dépenses (sorties de fonds).
from app.schemas.payment import AffecterBudgetPayload
from app.schemas.sortie_fonds import (
    SortieFondsCreate,
    SortieFondsDraftCreate,
    SortieFondsOut,
    SortiesFondsListResponse,
    SortieFondsStatusUpdate,
    SortieFondsPaymentRejectPayload,
)
from app.services.document_sequences import generate_document_number
from app.services import transferts_delegues
from app.services.transferts_internes_service import (
    contrepasser_transfer,
    create_transfer,
    delegue_au_moteur,
)
from app.services.report_cache import invalidate_report_summary_cache
from app.services.mailer import send_sortie_notification
from app.services.email_config import resolve_smtp_config
from app.services.system_settings_service import get_system_settings
from app.services.audit_service import get_request_ip, log_action
from app.services.fonds_tiers import assert_fonds_tiers_refundable, get_fonds_tiers_locked, refresh_fonds_tiers_status, resolve_fonds_tiers_display_name
from app.services.regularisations_budgetaires import affecter_sortie_hors_budget
from app.services.mouvements_budgetaires import (
    cancel_budget_imputations,
    create_budget_imputation,
    hors_budget_initial_status,
    impact_for_nature,
    normalize_nature,
    sum_active_by_sortie,
)
from app.services.reglement import MODE_PAIEMENT_MIXTE, canal_pour_mode, normaliser_mode
from app.services.service_access import get_user_service_ids, has_module_menu_access
from app.services.requisition_service import record_status_history, reject_requisition_at_payment_logic
from app.services.notifications import (
    FUND_OUTFLOW,
    build_settings as build_whatsapp_settings,
    notify_whatsapp,
    resolve_outflow_recipients,
)

router = APIRouter()


async def _can_force_budget_overrun(db: AsyncSession, user: User, tenant_id: int) -> bool:
    res = await db.execute(
        select(PrintSettings).where(PrintSettings.organisation_id == tenant_id).limit(1)
    )
    settings = res.scalar_one_or_none()
    if settings is None:
        return False
    if not settings.budget_block_overrun:
        return True
    roles = {r.strip().lower() for r in (settings.budget_force_roles or "").split(",") if r.strip()}
    return bool(user.role) and user.role.lower() in roles
logger = logging.getLogger("onec_cpk_api.sorties_fonds")

REQUISITION_STATUTS_VALIDES = ("APPROUVEE", "EN_DECAISSEMENT")
MAX_ANNEXE_SIZE = 3 * 1024 * 1024
ANNEXE_ALLOWED_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/jpg"}
ANNEXE_ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png"}
PDF_ALLOWED_TYPES = {"application/pdf"}
PDF_ALLOWED_EXT = {".pdf"}
DEFAULT_UPLOAD_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "uploads")
)
UPLOAD_ROOT = os.path.abspath(settings.upload_dir) if settings.upload_dir else DEFAULT_UPLOAD_ROOT
CANAL_PAIEMENT = {"CAISSE", "BANQUE"}


def _idempotency_payload_hash(payload: SortieFondsCreate) -> str:
    data = payload.model_dump(mode="json", exclude={"idempotency_key"})
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _idempotency_advisory_key(tenant_id: int, key: str) -> int:
    digest = hashlib.sha256(f"sortie:{tenant_id}:{key}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=True)

#: `entity_type` porté par les lignes de `notification_logs` de ce module.
NOTIF_ENTITY_SORTIE = "sortie_fonds"

#: Types de sortie qui ne notifient PAS le Bureau. Ce sont des mouvements de
#: trésorerie internes, pas des dépenses : rien ne quitte l'organisation.
#:   versement_banque ......... caisse -> banque (cf. is_versement_banque)
#:   approvisionnement_caisse . banque -> caisse (cf. is_appro_caisse)
#:   regularisation_caisse .... correction d'écart de caisse, produite par
#:                              services/regularisation_caisse.py, jamais par
#:                              cet endpoint — filtrée par précaution, la valeur
#:                              étant acceptée telle quelle depuis le payload.
#: Les notifier ferait du canal WhatsApp un journal de trésorerie et noierait
#: les vraies dépenses.
TYPES_SORTIE_SANS_NOTIFICATION = frozenset(
    {"versement_banque", "approvisionnement_caisse", "regularisation_caisse"}
)

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


def _nom_utilisateur(user: User | None) -> str:
    if user is None:
        return ""
    nom = " ".join(filter(None, [getattr(user, "prenom", ""), getattr(user, "nom", "")])).strip()
    return nom or (getattr(user, "email", "") or "")


def _canal_lisible(mode: str | None, canal: str | None) -> str:
    """Canal réel d'où sort l'argent, déduit du MODE de paiement.

    La colonne `canal` ne connaît que CAISSE et BANQUE : elle range le mobile
    money en BANQUE (cf. `reglement.canal_pour_mode`, où tout ce qui n'est pas
    « cash » devient BANQUE). Annoncer « Banque » pour un paiement Mobile Money
    induirait le Bureau en erreur sur l'endroit d'où l'argent est parti. On
    répond donc à partir du mode, et on ne retombe sur la colonne que si le mode
    est inconnu.
    """
    key = (mode or "").strip().lower()
    if key == "cash":
        return "Caisse"
    if key == "mobile_money":
        return "Mobile money"
    if key in MODE_PAIEMENT_LABELS:
        return "Banque"
    return "Caisse" if (canal or "").upper() == "CAISSE" else "Banque"


async def _notify_sortie_fonds_whatsapp(
    db: AsyncSession,
    background_tasks,
    *,
    sortie: SortieFonds,
    tenant_id: int,
    auteur: User | None,
    validateur: User | None = None,
    solde_apres: Any = None,
    tranche: str = "",
) -> None:
    """Prévient le Bureau qu'une sortie de fonds a été enregistrée.

    À appeler **après** le `commit()` : à ce moment l'argent a réellement quitté
    la caisse ou le compte, et c'est précisément ce que le message annonce.

    Trois choix explicites :

    * **Aucune condition sur `sortie.statut`.** `SortieFondsCreate.statut` n'est
      pas validé et vaut « VALIDE » par défaut, mais un payload peut poser
      « BROUILLON » : la trésorerie est débitée quand même (cf. le décrément de
      `caisse.solde_*` / `compte.solde_actuel`, qui ne regarde pas le statut).
      Conditionner l'envoi au statut rendrait donc muettes des sorties qui
      débitent réellement.
    * **Les transferts internes ne notifient pas** (cf.
      TYPES_SORTIE_SANS_NOTIFICATION).
    * **`solde_apres` est reçu en argument**, capturé avant le `commit()` par
      l'appelant : le relire ici imposerait une requête de plus et exposerait au
      `MissingGreenlet` classique sur objet rafraîchi hors contexte.

    Ne lève jamais.
    """
    try:
        if (sortie.type_sortie or "").lower() in TYPES_SORTIE_SANS_NOTIFICATION:
            return

        ns = await get_system_settings(db, tenant_id)
        if ns is None:
            return
        org_name = (
            await db.execute(select(Organisation.nom).where(Organisation.id == tenant_id).limit(1))
        ).scalar_one_or_none() or ""
        settings_obj = build_whatsapp_settings(ns, org_name)
        if not settings_obj.accepts(FUND_OUTFLOW):
            # Canal fermé : on sort avant d'interroger le Bureau.
            return

        recipients = await resolve_outflow_recipients(
            db, tenant_id, fallback_numbers=getattr(ns, "whatsapp_agents", "")
        )
        if not recipients:
            logger.info("WhatsApp : aucun destinataire pour la sortie %s", sortie.id)
            return

        devise = sortie.devise or "USD"
        # `budget_poste_libelle` porte déjà « Réparti sur N postes » quand la
        # dépense est multi-postes : c'est cette mention qu'on veut voir passer,
        # pas une ligne vide qui laisserait croire à une dépense sans imputation.
        poste = sortie.budget_poste_libelle or ""
        if sortie.budget_poste_code and poste:
            poste = f"{sortie.budget_poste_code} — {poste}"
        # `rubrique_code` n'est jamais alimenté nulle part dans le dépôt : il
        # n'entre pas dans le message.

        await notify_whatsapp(
            db,
            background_tasks,
            organisation_id=tenant_id,
            event_type=FUND_OUTFLOW,
            entity_type=NOTIF_ENTITY_SORTIE,
            entity_id=str(sortie.id),
            recipients=recipients,
            variables={
                "reference": sortie.reference_numero or "",
                "date": (
                    sortie.date_paiement.strftime("%d/%m/%Y") if sortie.date_paiement else ""
                ),
                "beneficiaire": sortie.beneficiaire or "",
                "motif": sortie.motif or "",
                "montant": _fmt_montant(sortie.montant_paye),
                "devise": devise,
                "canal": _canal_lisible(sortie.mode_paiement, sortie.canal),
                "mode_paiement": _mode_paiement_label(sortie.mode_paiement),
                "poste_budgetaire": poste,
                "auteur": _nom_utilisateur(auteur),
                "validateur": _nom_utilisateur(validateur),
                "solde_apres": (
                    f"{_fmt_montant(solde_apres)} {devise}" if solde_apres is not None else ""
                ),
                # Le gabarit insère `{{tranche}}` sur sa propre ligne, sans
                # étiquette : la valeur doit donc porter son retour à la ligne.
                "tranche": tranche,
            },
            settings=settings_obj,
        )
    except Exception:
        logger.exception(
            "Échec de préparation de la notification WhatsApp (sortie de fonds %s)",
            getattr(sortie, "id", None),
        )


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


def _tenant_sortie_dir(tenant_uuid: str, year: int, month: int) -> str:
    return os.path.abspath(
        os.path.join(UPLOAD_ROOT, "tenants", str(tenant_uuid), "sorties-fonds", f"{year:04d}", f"{month:02d}")
    )


def _sortie_pdf_fs_path(file_path: str | None) -> str:
    if not file_path:
        return ""
    if file_path.startswith("/uploads/"):
        rel_path = file_path.replace("/uploads/", "", 1).lstrip("/")
        return os.path.abspath(os.path.join(UPLOAD_ROOT, rel_path))
    return os.path.abspath(os.path.join(UPLOAD_ROOT, "sorties-fonds", os.path.basename(file_path)))


def _sortie_annexe_fs_path(path_value: str | None) -> str:
    if not path_value:
        return ""
    if path_value.startswith("/uploads/"):
        rel_path = path_value.replace("/uploads/", "", 1).lstrip("/")
        return os.path.abspath(os.path.join(UPLOAD_ROOT, rel_path))
    return os.path.abspath(os.path.join(UPLOAD_ROOT, "sorties-fonds", "annexes", path_value))


def _safe_ref(value: str) -> str:
    if not value:
        return "SORTIE"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value)
    return safe.strip("._-") or "SORTIE"


async def _save_sortie_annexes(
    attachments: list[UploadFile],
    safe_ref: str,
    *,
    tenant_uuid: str,
) -> list[str]:
    filenames: list[str] = []
    for attachment in attachments:
        content_type = (attachment.content_type or "").lower()
        if content_type and content_type not in ANNEXE_ALLOWED_TYPES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Format de fichier non autorisé")
        original_name = attachment.filename or "annexe"
        ext = os.path.splitext(original_name)[1].lower()
        if ext and ext not in ANNEXE_ALLOWED_EXT:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Extension de fichier non autorisée")
        contents = await attachment.read()
        if len(contents) > MAX_ANNEXE_SIZE:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Fichier trop volumineux (max 3 Mo)")
        upload_dt = datetime.now(timezone.utc)
        target_dir = _tenant_sortie_dir(tenant_uuid, upload_dt.year, upload_dt.month)
        os.makedirs(target_dir, exist_ok=True)
        filename = f"{safe_ref}-annex-{uuid_lib.uuid4().hex}{ext or '.pdf'}"
        dest_path = os.path.join(target_dir, filename)
        with open(dest_path, "wb") as f:
            f.write(contents)
        filenames.append(
            f"/uploads/tenants/{tenant_uuid}/sorties-fonds/{upload_dt.year:04d}/{upload_dt.month:02d}/{filename}"
        )
    return filenames


def _user_info(user: User | None) -> dict[str, Any] | None:
    if not user:
        return None
    return {
        "id": str(user.id),
        "prenom": user.prenom,
        "nom": user.nom,
        "email": user.email,
    }


def _requisition_out(
    req: Requisition,
    *,
    validateur: User | None = None,
    approbateur: User | None = None,
    remboursement_transport: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = {
        "id": str(req.id),
        "numero_requisition": req.numero_requisition,
        "reference_numero": req.reference_numero,
        "objet": req.objet,
        "mode_paiement": req.mode_paiement,
        "type_requisition": req.type_requisition,
        "montant_total": req.montant_total or 0,
        "service_id": req.service_id,
        "compte_bancaire_id": req.compte_bancaire_id,
        "status": req.status,
        "statut": req.status,
        "created_by": str(req.created_by) if req.created_by else None,
        "validee_par": str(req.validee_par) if req.validee_par else None,
        "validee_le": req.validee_le,
        "approuvee_par": str(req.approuvee_par) if req.approuvee_par else None,
        "approuvee_le": req.approuvee_le,
        "payee_par": str(req.payee_par) if req.payee_par else None,
        "payee_le": req.payee_le,
        "motif_rejet": req.motif_rejet,
        "a_valoir": req.a_valoir,
        "decaissement_progressif": bool(getattr(req, "decaissement_progressif", False)),
        "instance_beneficiaire": req.instance_beneficiaire,
        "notes_a_valoir": req.notes_a_valoir,
        "req_titre_officiel_hist": req.req_titre_officiel_hist,
        "req_label_gauche_hist": req.req_label_gauche_hist,
        "req_nom_gauche_hist": req.req_nom_gauche_hist,
        "req_label_droite_hist": req.req_label_droite_hist,
        "req_nom_droite_hist": req.req_nom_droite_hist,
        "signataire_g_label": req.signataire_g_label,
        "signataire_g_nom": req.signataire_g_nom,
        "signataire_d_label": req.signataire_d_label,
        "signataire_d_nom": req.signataire_d_nom,
        "remboursement_transport": remboursement_transport,
        "created_at": req.created_at,
        "updated_at": req.updated_at,
    }
    if validateur:
        base["validateur"] = _user_info(validateur)
    if approbateur:
        base["approbateur"] = _user_info(approbateur)
    return base


def _est_sortie_hors_budget(sortie: SortieFonds | None) -> bool:
    """Vrai pour une dépense payée hors budget, donc encore à imputer."""
    if sortie is None:
        return False
    return (getattr(sortie, "nature_mouvement", None) or "BUDGETAIRE").upper() == "HORS_BUDGET_A_REGULARISER"


def _sortie_out(
    sortie: SortieFonds,
    requisition: Requisition | None = None,
    *,
    creator: User | None = None,
    canceller: User | None = None,
    programme_par: User | None = None,
    validateur: User | None = None,
    approbateur: User | None = None,
    remboursement_transport: dict[str, Any] | None = None,
    montant_affecte_budget: Decimal | None = None,
) -> SortieFondsOut:
    return SortieFondsOut(
        id=str(sortie.id),
        type_sortie=sortie.type_sortie,
        requisition_id=str(sortie.requisition_id) if sortie.requisition_id else None,
        rubrique_code=sortie.rubrique_code,
        budget_poste_id=sortie.budget_poste_id,
        budget_poste_code=sortie.budget_poste_code,
        budget_poste_libelle=sortie.budget_poste_libelle,
        service_id=sortie.service_id,
        montant_paye=sortie.montant_paye or 0,
        date_paiement=sortie.date_paiement,
        mode_paiement=sortie.mode_paiement,
        reference=sortie.reference,
        devise=sortie.devise,
        canal=sortie.canal,
        compte_bancaire_id=sortie.compte_bancaire_id,
        reference_numero=sortie.reference_numero,
        idempotency_key=sortie.idempotency_key,
        nature_mouvement=getattr(sortie, "nature_mouvement", None) or "BUDGETAIRE",
        impact_budgetaire=getattr(sortie, "impact_budgetaire", None),
        hors_budget_status=getattr(sortie, "hors_budget_status", None),
        fonds_tiers_operation_id=getattr(sortie, "fonds_tiers_operation_id", None),
        montant_affecte_budget=montant_affecte_budget if montant_affecte_budget is not None else Decimal("0"),
        pdf_path=sortie.pdf_path,
        statut=sortie.statut or "VALIDE",
        statut_comptabilisation=getattr(sortie, "statut_comptabilisation", "NON_COMPTABILISEE"),
        message_comptabilisation=getattr(sortie, "message_comptabilisation", None),
        motif_annulation=sortie.motif_annulation,
        annulee_le=sortie.annulee_le,
        annulee_par_id=str(sortie.annulee_par_id) if sortie.annulee_par_id else None,
        annulation_ip=sortie.annulation_ip,
        ancien_statut=sortie.ancien_statut,
        exchange_rate_snapshot=sortie.exchange_rate_snapshot,
        motif=sortie.motif,
        beneficiaire=sortie.beneficiaire,
        piece_justificative=sortie.piece_justificative,
        commentaire=sortie.commentaire,
        annexes=sortie.annexes,
        created_by=str(sortie.created_by) if sortie.created_by else None,
        created_by_user=_user_info(creator),
        programme_par_id=str(sortie.programme_par_id) if sortie.programme_par_id else None,
        programme_par_user=_user_info(programme_par),
        annulee_par_user=_user_info(canceller),
        created_at=sortie.created_at,
        is_reconciled=sortie.is_reconciled,
        reconciled_at=sortie.reconciled_at,
        reconciled_by_id=str(sortie.reconciled_by_id) if sortie.reconciled_by_id else None,
        bank_statement_ref=sortie.bank_statement_ref,
        requisition=_requisition_out(
            requisition,
            validateur=validateur,
            approbateur=approbateur,
            remboursement_transport=remboursement_transport,
        ) if requisition else None,
    )


def _remboursement_transport_payload(remboursement: RemboursementTransport | None) -> dict[str, Any] | None:
    if remboursement is None:
        return None
    return {
        "id": str(remboursement.id),
        "numero_remboursement": remboursement.numero_remboursement,
        "reference_numero": remboursement.reference_numero,
        "instance": remboursement.instance,
        "date_reunion": remboursement.date_reunion.isoformat() if remboursement.date_reunion else None,
        "lieu": remboursement.lieu,
    }


async def _resolve_service(service_id: int, db: AsyncSession) -> Service:
    res = await db.execute(select(Service).where(Service.id == service_id, Service.is_active.is_(True)))
    service = res.scalar_one_or_none()
    if service is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="service_id invalide")
    return service


def _parse_order(order: str | None):
    if not order:
        return SortieFonds.date_paiement.desc()
    parts = order.split(".")
    field = parts[0]
    direction = parts[1] if len(parts) > 1 else "asc"
    column_map = {
        "date_paiement": SortieFonds.date_paiement,
        "created_at": SortieFonds.created_at,
        "montant_paye": SortieFonds.montant_paye,
    }
    col = column_map.get(field)
    if col is None:
        return SortieFonds.date_paiement.desc().nulls_last()
    # Placement explicite des NULL. PostgreSQL les met en tête d'un tri
    # décroissant ; la fusion avec les transferts délégués, elle, traite une
    # date absente comme la plus petite valeur. Sans cet accord, une sortie sans
    # date de paiement changerait de place selon qu'un transfert existe ou non.
    return col.desc().nulls_last() if direction.lower() == "desc" else col.asc().nulls_first()


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


async def _get_last_cloture_date(db: AsyncSession) -> datetime | None:
    res = await db.execute(
        select(ClotureCaisse).order_by(ClotureCaisse.date_cloture.desc()).limit(1)
    )
    last = res.scalar_one_or_none()
    if not last or not last.date_cloture:
        return None
    last_dt = last.date_cloture
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=timezone.utc)
    return last_dt


@router.get("", response_model=list[SortieFondsOut] | SortiesFondsListResponse)
async def list_sorties_fonds(
    include: str | None = Query(default=None, description="Relations à inclure (requisition)"),
    date_debut: str | None = Query(default=None),
    date_fin: str | None = Query(default=None),
    type_sortie: str | None = Query(default=None),
    mode_paiement: str | None = Query(default=None),
    canal: str | None = Query(default=None),
    compte_bancaire_id: int | None = Query(default=None),
    statut: str | None = Query(default=None),
    requisition_id: str | None = Query(default=None),
    requisition_numero: str | None = Query(default=None),
    reference: str | None = Query(default=None),
    order: str | None = Query(default=None, description="Ex: date_paiement.desc"),
    limit: int = Query(default=100, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    include_summary: bool = Query(default=False),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[SortieFondsOut] | SortiesFondsListResponse:
    include_parts = {part.strip() for part in (include or "").split(",") if part.strip()}
    include_requisition = "requisition" in include_parts or bool(requisition_numero)
    conditions = [
        SortieFonds.organisation_id == tenant_id,
        or_(
            SortieFonds.requisition_id.is_(None),
            # Une sortie déjà exécutée doit rester visible même quand la réquisition
            # est soldée (PAYEE) : on ne masque que les réquisitions rejetées.
            Requisition.status.in_(("APPROUVEE", "EN_DECAISSEMENT", "PAYEE")),
        )
    ]
    # Un transfert interne n'a pas de service : un utilisateur restreint à ses
    # services n'en voit aucun, exactement comme il ne voit aujourd'hui aucune
    # sortie sans service.
    restreint_aux_services = False
    if not await has_module_menu_access(db, user, "menu_sorties_fonds"):
        restreint_aux_services = True
        service_ids = await get_user_service_ids(db, user)
        if not service_ids:
            return [] if not include_summary else SortiesFondsListResponse(
                items=[], total=0, total_montant_paye=Decimal("0"),
                total_depenses_reelles=Decimal("0"), total_transferts_internes=Decimal("0"),
                total_retours_caisse=Decimal("0"), total_depenses_nettes=Decimal("0"),
            )
        conditions.append(SortieFonds.service_id.in_(service_ids))
    can_view_cancelled = await _user_has_permission(db, user, "view_cancelled_financial_operations")

    start_dt = _parse_datetime(date_debut)
    end_dt = _parse_datetime(date_fin, end_of_day=True)
    if start_dt:
        conditions.append(SortieFonds.date_paiement >= start_dt)
    if end_dt:
        conditions.append(SortieFonds.date_paiement <= end_dt)

    if type_sortie:
        conditions.append(SortieFonds.type_sortie == type_sortie)
    if mode_paiement:
        conditions.append(SortieFonds.mode_paiement == mode_paiement)
    if canal:
        conditions.append(SortieFonds.canal == canal.upper())
    if compte_bancaire_id:
        conditions.append(SortieFonds.compte_bancaire_id == compte_bancaire_id)
    if statut:
        statut_value = statut.strip().upper()
        if statut_value == "ALL":
            if not can_view_cancelled:
                raise HTTPException(status_code=403, detail="Privilèges insuffisants (view_cancelled_financial_operations)")
        elif statut_value == "VALIDE":
            conditions.append(
                (SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE")
            )
        else:
            if statut_value == "ANNULEE" and not can_view_cancelled:
                raise HTTPException(status_code=403, detail="Privilèges insuffisants (view_cancelled_financial_operations)")
            conditions.append(SortieFonds.statut == statut_value)
    else:
        conditions.append((SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE"))
    if reference:
        conditions.append(SortieFonds.reference.ilike(f"%{reference}%"))
    if requisition_id:
        try:
            req_uid = uuid.UUID(requisition_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id UUID")
        conditions.append(SortieFonds.requisition_id == req_uid)

    if requisition_numero:
        conditions.append(Requisition.numero_requisition.ilike(f"%{requisition_numero}%"))
        conditions.append(Requisition.organisation_id == tenant_id)

    if include_requisition:
        query = select(SortieFonds, Requisition).outerjoin(
            Requisition, SortieFonds.requisition_id == Requisition.id
        )
    else:
        query = select(SortieFonds).outerjoin(Requisition, SortieFonds.requisition_id == Requisition.id)

    if conditions:
        query = query.where(*conditions)

    filtres_delegues = transferts_delegues.FiltresSorties(
        date_debut=start_dt,
        date_fin=end_dt,
        type_sortie=type_sortie,
        mode_paiement=mode_paiement,
        canal=canal,
        compte_bancaire_id=compte_bancaire_id,
        statut=statut,
        reference=reference,
        filtre_requisition=bool(requisition_id or requisition_numero),
        restreint_aux_services=restreint_aux_services,
    )
    # La source déléguée est lue d'abord. Tant qu'elle ne rend rien — c'est-à-dire
    # tant que le drapeau de bascule n'a rien écrit —, la requête historique
    # garde exactement sa forme d'aujourd'hui, offset et limite compris : la
    # lecture bilingue est inobservable jusqu'à la première ligne déléguée.
    items_delegues = await transferts_delegues.lister(
        db, tenant_id=tenant_id, filtres=filtres_delegues, limit=offset + limit
    )

    query = query.order_by(_parse_order(order))
    if items_delegues:
        # Fusionner deux sources impose de ramener les `offset + limit` premières
        # lignes de chacune : borner chaque source à sa propre page rendrait les
        # N premières de chacune, pas les N plus récentes de l'ensemble.
        query = query.limit(offset + limit)
    else:
        query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    rows = result.all() if include_requisition else result.scalars().all()
    
    users_map: dict[uuid.UUID, User] = {}
    if include_requisition:
        user_ids: set[uuid.UUID] = set()
        requisition_ids: set[uuid.UUID] = set()
        for row in rows:
            sortie = row[0]
            req = row[1]
            if sortie and sortie.created_by:
                user_ids.add(sortie.created_by)
            if sortie and sortie.annulee_par_id:
                user_ids.add(sortie.annulee_par_id)
            if sortie and sortie.programme_par_id:
                user_ids.add(sortie.programme_par_id)
            if req:
                requisition_ids.add(req.id)
                if req.validee_par: user_ids.add(req.validee_par)
                if req.approuvee_par: user_ids.add(req.approuvee_par)
    else:
        user_ids = {
            user_id
            for sortie in rows
            for user_id in (sortie.created_by, sortie.annulee_par_id, sortie.programme_par_id)
            if user_id
        }
        requisition_ids = set()
        
    if user_ids:
        u_res = await db.execute(select(User).where(User.id.in_(list(user_ids)), User.organisation_id == tenant_id))
        users_map = {u.id: u for u in u_res.scalars().all()}

    remboursements_map: dict[uuid.UUID, dict[str, Any]] = {}
    if requisition_ids:
        remb_res = await db.execute(
            select(RemboursementTransport).where(RemboursementTransport.requisition_id.in_(list(requisition_ids)))
        )
        remboursements_map = {
            remb.requisition_id: _remboursement_transport_payload(remb)
            for remb in remb_res.scalars().all()
            if remb.requisition_id
        }

    # Un seul agrégat pour toute la page : le reste à régulariser d'une dépense
    # hors budget se lit sur la ligne, sans une requête par ligne.
    sorties_page = [row[0] for row in rows] if include_requisition else list(rows)
    affectations = await sum_active_by_sortie(
        db,
        organisation_id=tenant_id,
        sortie_ids=[s.id for s in sorties_page if _est_sortie_hors_budget(s)],
    )
    if include_requisition:
        items = [
            _sortie_out(
                sortie, 
                req, 
                creator=users_map.get(sortie.created_by) if sortie and sortie.created_by else None,
                canceller=users_map.get(sortie.annulee_par_id) if sortie and sortie.annulee_par_id else None,
                programme_par=users_map.get(sortie.programme_par_id) if sortie and sortie.programme_par_id else None,
                validateur=users_map.get(req.validee_par) if req and req.validee_par else None,
                approbateur=users_map.get(req.approuvee_par) if req and req.approuvee_par else None,
                remboursement_transport=remboursements_map.get(req.id) if req else None,
                montant_affecte_budget=affectations.get(sortie.id) if sortie else None,
            ) 
            for sortie, req in rows
        ]
    else:
        items = [
            _sortie_out(
                sortie,
                creator=users_map.get(sortie.created_by) if sortie.created_by else None,
                canceller=users_map.get(sortie.annulee_par_id) if sortie.annulee_par_id else None,
                programme_par=users_map.get(sortie.programme_par_id) if sortie.programme_par_id else None,
                montant_affecte_budget=affectations.get(sortie.id),
            )
            for sortie in rows
        ]

    if items_delegues:
        cle_tri, decroissant = transferts_delegues.cle_de_tri(order)
        items = sorted(items + items_delegues, key=cle_tri, reverse=decroissant)[
            offset : offset + limit
        ]

    if not include_summary:
        return items

    count_query = select(func.count()).select_from(SortieFonds)
    count_query = count_query.outerjoin(Requisition, SortieFonds.requisition_id == Requisition.id)
    if conditions:
        count_query = count_query.where(*conditions)
    total_count = int((await db.execute(count_query)).scalar_one() or 0)

    # Condition de statut appliquée aux totaux (uniquement les opérations valides
    # sauf demande explicite d'un autre statut).
    if statut and statut.strip().upper() not in ("ALL", "VALIDE"):
        statut_cond = SortieFonds.statut == statut.strip().upper()
    else:
        statut_cond = (SortieFonds.statut.is_(None)) | (SortieFonds.statut == "VALIDE")

    # Transferts internes caisse <-> banque (versement, approvisionnement) : à
    # distinguer des vraies dépenses dans les totaux.
    transfert_types = ("versement_banque", "approvisionnement_caisse")

    def _sum_query(extra=None):
        q = select(func.coalesce(func.sum(func.coalesce(SortieFonds.montant_paye, 0)), 0)).select_from(
            SortieFonds
        ).outerjoin(Requisition, SortieFonds.requisition_id == Requisition.id)
        if conditions:
            q = q.where(*conditions)
        q = q.where(statut_cond)
        if extra is not None:
            q = q.where(extra)
        return q

    total_montant_paye = Decimal((await db.execute(_sum_query())).scalar_one() or 0)
    total_transferts_internes = Decimal((
        await db.execute(_sum_query(SortieFonds.type_sortie.in_(transfert_types)))
    ).scalar_one() or 0)
    total_depenses_reelles = Decimal((
        await db.execute(_sum_query(SortieFonds.type_sortie.notin_(transfert_types)))
    ).scalar_one() or 0)

    # Les transferts délégués s'ajoutent au total général et au sous-total des
    # transferts internes, jamais aux dépenses réelles : déplacer de l'argent
    # d'une poche à l'autre n'a jamais été une dépense, quel que soit le moteur
    # qui l'écrit. Le compte et la somme portent exactement sur les lignes que
    # `lister` rend — un total qu'aucune liste ne justifie est précisément le
    # défaut que cette bascule cherche à éviter.
    nombre_delegues, volume_delegue, net_delegue = await transferts_delegues.compter_et_sommer(
        db, tenant_id=tenant_id, filtres=filtres_delegues
    )
    total_count += nombre_delegues
    total_montant_paye += volume_delegue
    total_transferts_internes += volume_delegue

    # Net signé du volume, positif quand l'argent est allé de la caisse vers la
    # banque. Un versement contre-passé produit un aller ET un retour : le
    # volume vaut deux fois le montant, le net vaut zéro. C'est le net qui dit
    # que la trésorerie n'a pas bougé — le volume, lui, ne peut pas mentir sur
    # le nombre de mouvements, et filtrer les contre-passés afficherait l'inverse
    # sans son original, donc de l'argent venu de nulle part.
    total_versements = Decimal((
        await db.execute(_sum_query(SortieFonds.type_sortie == "versement_banque"))
    ).scalar_one() or 0)
    total_approvisionnements = total_transferts_internes - volume_delegue - total_versements
    total_transferts_internes_net = (
        total_versements - total_approvisionnements + net_delegue
    )

    # Retours en caisse (reliquats rendus) : ils VIENNENT EN DIMINUTION de la
    # dépense. On les expose à part plutôt que de les fondre dans les totaux, de
    # sorte que l'écran affiche brut / retours / net et se rapproche ligne à
    # ligne de l'export Excel (dont le total est net, cf. exports.py).
    # Même règle d'inclusion que l'export : un filtre sur le type de sortie ou
    # le mode de paiement ne s'applique pas aux retours, on les omet alors
    # plutôt que d'afficher un net incohérent avec la liste filtrée.
    retours_applicables = (
        (not statut or statut.strip().upper() in ("VALIDE", "ALL"))
        and not type_sortie
        and not mode_paiement
    )
    total_retours_caisse = Decimal("0")
    if retours_applicables:
        r_conditions = [
            RetourCaisse.organisation_id == tenant_id,
            RetourCaisse.statut == "VALIDE",
        ]
        if start_dt:
            r_conditions.append(RetourCaisse.date_retour >= start_dt)
        if end_dt:
            r_conditions.append(RetourCaisse.date_retour <= end_dt)
        if canal:
            r_conditions.append(RetourCaisse.canal == canal.upper())
        if compte_bancaire_id:
            r_conditions.append(RetourCaisse.compte_bancaire_id == compte_bancaire_id)
        r_query = select(func.coalesce(func.sum(RetourCaisse.montant), 0)).where(*r_conditions)
        total_retours_caisse = Decimal(
            (await db.execute(r_query)).scalar_one() or 0
        )

    return SortiesFondsListResponse(
        items=items,
        total=total_count,
        total_montant_paye=total_montant_paye,
        total_depenses_reelles=total_depenses_reelles,
        total_transferts_internes=total_transferts_internes,
        total_transferts_internes_net=total_transferts_internes_net,
        total_retours_caisse=total_retours_caisse,
        total_depenses_nettes=Decimal(total_depenses_reelles or 0) - total_retours_caisse,
    )


@router.get("/requisitions/{req_id}/solde")
async def get_requisition_solde(
    req_id: str,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Reste à payer d'une réquisition (classique ou à décaissement progressif).

    ``total_paye`` = somme des sorties VALIDES rattachées ; ``reste`` =
    ``montant_total − total_paye``. Permet au front d'afficher le solde et de
    proposer un complément de paiement tant que la réquisition n'est pas soldée.
    """
    try:
        req_uid = uuid.UUID(req_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="req_id invalide")
    res = await db.execute(
        select(Requisition).where(
            Requisition.id == req_uid,
            Requisition.organisation_id == tenant_id,
        )
    )
    req = res.scalar_one_or_none()
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Réquisition introuvable")
    total_paye = (
        await db.execute(
            select(func.coalesce(func.sum(SortieFonds.montant_paye), 0)).where(
                SortieFonds.requisition_id == req_uid,
                SortieFonds.organisation_id == tenant_id,
                SortieFonds.statut == "VALIDE",
            )
        )
    ).scalar_one() or 0
    total = Decimal(req.montant_total or 0)
    total_paye_dec = Decimal(str(total_paye))
    reste = total - total_paye_dec
    return {
        "requisition_id": str(req.id),
        "numero_requisition": req.numero_requisition,
        "statut": req.status,
        "devise": getattr(req, "devise", "USD"),
        "montant_total": float(total),
        "total_paye": float(total_paye_dec),
        "reste": float(reste if reste > 0 else Decimal("0")),
        "decaissement_progressif": bool(getattr(req, "decaissement_progressif", False)),
        "soldee": reste <= 0,
    }


async def _to_budget_currency(
    db: AsyncSession,
    tenant_id: int,
    montant: Decimal | float | None,
    devise: str | None,
    *,
    exchange_rate_snapshot: Decimal | float | None = None,
) -> Decimal:
    """Convertit un montant depuis sa devise vers la DEVISE DE BASE du budget
    (USD : les postes budgétaires n'ont pas de devise propre). Évite de mélanger
    du CDF avec des plafonds/cumuls exprimés en USD.

    Taux exprimés en « unités de devise pour 1 USD » (comme le frontend). Si le
    taux nécessaire est manquant, renvoie le montant tel quel (best-effort,
    comportement historique).
    """
    m = Decimal(montant or 0)
    d = (devise or "USD").upper()
    if d == "USD" or m == 0:
        return m
    if exchange_rate_snapshot is not None:
        try:
            snapshot_rate = Decimal(str(exchange_rate_snapshot or 0))
        except Exception:
            snapshot_rate = Decimal(0)
        if snapshot_rate > 0:
            return m / snapshot_rate
    res = await db.execute(
        select(PrintSettings).where(PrintSettings.organisation_id == tenant_id).limit(1)
    )
    ps = res.scalar_one_or_none()
    rate_raw = {
        "CDF": getattr(ps, "exchange_rate_cdf", 0),
        "EUR": getattr(ps, "exchange_rate_eur", 0),
        "XOF": getattr(ps, "exchange_rate_xof", 0),
    }.get(d, 0) if ps is not None else 0
    try:
        rate = Decimal(str(rate_raw or 0))
    except Exception:
        rate = Decimal(0)
    return (m / rate) if rate > 0 else m


async def _assert_budget_rate(db: AsyncSession, tenant_id: int, devise: str | None) -> None:
    """Bloque l'imputation budgétaire d'une sortie en devise étrangère si aucun
    taux de change n'est configuré (sinon la conversion vers l'USD serait fausse).
    """
    d = (devise or "USD").upper()
    if d == "USD":
        return
    res = await db.execute(
        select(PrintSettings).where(PrintSettings.organisation_id == tenant_id).limit(1)
    )
    ps = res.scalar_one_or_none()
    rate_raw = {
        "CDF": getattr(ps, "exchange_rate_cdf", 0),
        "EUR": getattr(ps, "exchange_rate_eur", 0),
        "XOF": getattr(ps, "exchange_rate_xof", 0),
    }.get(d, 0) if ps is not None else 0
    try:
        rate = float(rate_raw or 0)
    except (TypeError, ValueError):
        rate = 0
    if rate <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Taux de change requis pour imputer une sortie en {d} sur un poste "
                "budgétaire. Configurez-le dans les réglages avant de valider."
            ),
        )


@router.post("/drafts", response_model=SortieFondsOut, status_code=status.HTTP_201_CREATED)
async def create_sortie_fonds_draft(
    payload: SortieFondsDraftCreate,
    request: Request,
    user: User = Depends(has_permission("can_execute_payment")),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> SortieFondsOut:
    canal = (payload.canal or "CAISSE").upper()
    if canal not in CANAL_PAIEMENT:
        raise HTTPException(status_code=400, detail="canal invalide")
    devise = (payload.devise or "USD").upper()
    if devise not in {"USD", "CDF"}:
        raise HTTPException(status_code=400, detail="devise invalide")

    requisition_uid: uuid.UUID | None = None
    if payload.requisition_id:
        try:
            requisition_uid = payload.requisition_id
            if not isinstance(requisition_uid, uuid.UUID):
                requisition_uid = uuid.UUID(str(requisition_uid))
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id UUID")
        req_res = await db.execute(
            select(Requisition.id, Requisition.service_id).where(
                Requisition.id == requisition_uid,
                Requisition.organisation_id == tenant_id,
            )
        )
        req_row = req_res.first()
        if req_row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")
        if payload.service_id is not None and req_row.service_id is not None and int(payload.service_id) != int(req_row.service_id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Service différent de la réquisition")

    if payload.service_id is not None:
        await _resolve_service(payload.service_id, db)

    if payload.compte_bancaire_id is not None:
        res = await db.execute(
            select(CompteBancaire).where(
                CompteBancaire.id == payload.compte_bancaire_id,
                CompteBancaire.organisation_id == tenant_id,
            )
        )
        compte = res.scalar_one_or_none()
        if compte is None or compte.is_active is False:
            raise HTTPException(status_code=400, detail="compte_bancaire_id invalide")
        if (compte.devise or "").upper() != devise:
            raise HTTPException(status_code=400, detail="devise incompatible avec le compte bancaire")
        account_type = (compte.account_type or "BANK").upper()
        if canal == "BANQUE" and account_type != "BANK":
            raise HTTPException(status_code=400, detail="compte_bancaire_id invalide")

    date_paiement: datetime | None = None
    if payload.date_paiement:
        if isinstance(payload.date_paiement, datetime):
            date_paiement = payload.date_paiement
        else:
            parsed = _parse_datetime(str(payload.date_paiement))
            if parsed is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date_paiement")
            date_paiement = parsed
    # L'horloge du serveur fait foi : seul un super administrateur peut
    # enregistrer une sortie à une autre date que celle du jour.
    date_paiement = resoudre_date_operation(
        date_paiement, user=user, champ="date_paiement"
    )

    sortie = SortieFonds(
        type_sortie=(payload.type_sortie or "requisition"),
        organisation_id=tenant_id,
        requisition_id=requisition_uid,
        rubrique_code=payload.rubrique_code,
        budget_poste_id=payload.budget_poste_id,
        service_id=payload.service_id,
        montant_paye=payload.montant_paye or Decimal("0"),
        date_paiement=date_paiement,
        mode_paiement=payload.mode_paiement or "cash",
        reference=payload.reference,
        devise=devise,
        canal=canal,
        compte_bancaire_id=payload.compte_bancaire_id,
        reference_numero=None,
        statut="BROUILLON",
        motif=(payload.motif or "").strip(),
        beneficiaire=(payload.beneficiaire or "").strip(),
        piece_justificative=payload.piece_justificative,
        commentaire=payload.commentaire,
        created_by=user.id,
    )
    db.add(sortie)
    await db.flush()
    await log_action(
        db,
        user_id=user.id,
        action="SORTIE_DRAFT_CREATED",
        target_table="sorties_fonds",
        target_id=str(sortie.id),
        new_value={
            "statut": sortie.statut,
            "montant_paye": float(sortie.montant_paye or 0),
            "requisition_id": str(sortie.requisition_id) if sortie.requisition_id else None,
            "service_id": sortie.service_id,
        },
        ip_address=get_request_ip(request),
    )
    await db.commit()
    await db.refresh(sortie)
    return _sortie_out(sortie, creator=user)


async def _deleguer_transfert_interne(
    db: AsyncSession,
    *,
    compte_bancaire_id: int,
    vers_la_banque: bool,
    montant: Decimal,
    devise: str,
    date_operation: datetime,
    tenant_id: int,
    user: User,
    request: Request,
    idempotency_key: str | None,
    payload_hash: str | None,
) -> SortieFondsOut:
    """Écrit le mouvement dans `transferts_internes` et le rend comme une sortie.

    C'est la bascule d'écriture : le payload, les permissions et toutes les
    validations en amont restent celles de `POST /sorties-fonds` — seul le
    moteur qui écrit change. Le frontend ne voit pas la différence, sinon la
    référence (`TRF-` au lieu de `PAY-`, tranché en Phase 2) et le fait
    qu'annuler contre-passe.

    L'UUID est **tiré ici** puis porté par le transfert : c'est l'identité que
    la réponse annonce, celle sur laquelle le frontend attachera le bon
    imprimé. Un rejeu idempotent rend le transfert existant, donc l'UUID
    d'origine — jamais un nouveau, qui ferait attacher le bon à une opération
    qui n'existe pas.
    """
    transfert_payload = TransfertInterneCreate(
        source_type="CAISSE" if vers_la_banque else "BANQUE",
        source_id=None if vers_la_banque else compte_bancaire_id,
        destination_type="BANQUE" if vers_la_banque else "CAISSE",
        destination_id=compte_bancaire_id if vers_la_banque else None,
        montant=Decimal(str(montant)),
        devise=devise,
        date_transfert=date_operation,
    )
    transfert = await create_transfer(
        db,
        payload=transfert_payload,
        tenant_id=tenant_id,
        user=user,
        idempotency_key=idempotency_key,
        document_uuid=uuid.uuid4(),
        # L'empreinte est celle du payload du CLIENT, jamais celle du transfert
        # dérivé : ce dernier porte une date résolue côté serveur, différente à
        # chaque appel, qui ferait refuser tout rejeu comme « payload différent ».
        payload_hash=payload_hash,
        ip_address=get_request_ip(request),
    )
    if transfert.document_uuid is None:
        # Le rejeu est tombé sur un transfert saisi hors de cet écran : il n'a
        # pas d'identité documentaire, donc rien à quoi attacher un bon. Mieux
        # vaut le dire que rendre une réponse que la suite ne saura pas suivre.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cette Idempotency-Key a déjà été utilisée hors des sorties de fonds",
        )
    projection = await transferts_delegues.projeter_par_document_uuid(
        db, tenant_id=tenant_id, document_uuid=transfert.document_uuid
    )
    if projection is None:  # pragma: no cover - la ligne vient d'être écrite
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfert introuvable après écriture")
    return projection


@router.post("", response_model=SortieFondsOut, status_code=status.HTTP_201_CREATED)
async def create_sortie_fonds(
    payload: SortieFondsCreate,
    request: Request,
    # Requis par la notification WhatsApp de fin de fonction : la remise part en
    # tâche de fond, après que la réponse HTTP a été rendue.
    background_tasks: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: User = Depends(has_permission("can_execute_payment")),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> SortieFondsOut:
    # L'en-tête est la forme recommandée ; le champ du body reste accepté pour
    # les intégrations qui ne peuvent pas ajouter d'en-têtes personnalisés.
    header_key = idempotency_key if isinstance(idempotency_key, str) else None
    body_key = payload.idempotency_key if isinstance(payload.idempotency_key, str) else None
    if header_key and body_key and header_key.strip() != body_key.strip():
        raise HTTPException(status_code=400, detail="Idempotency-Key différent de payload.idempotency_key")
    effective_idempotency_key = (header_key or body_key or "").strip() or None
    if effective_idempotency_key is not None:
        if len(effective_idempotency_key) > 128:
            raise HTTPException(status_code=400, detail="Idempotency-Key trop longue (128 caractères maximum)")
        payload_hash = _idempotency_payload_hash(payload)
        # L'advisory lock est transactionnel : deux requêtes concurrentes pour
        # la même clé sont sérialisées avant toute lecture ou écriture métier.
        await db.execute(select(func.pg_advisory_xact_lock(
            _idempotency_advisory_key(tenant_id, effective_idempotency_key)
        )))
        existing_res = await db.execute(
            select(SortieFonds)
            .where(
                SortieFonds.organisation_id == tenant_id,
                SortieFonds.idempotency_key == effective_idempotency_key,
            )
            .with_for_update()
        )
        existing = existing_res.scalar_one_or_none()
        if existing is not None:
            if existing.idempotency_payload_hash != payload_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Cette Idempotency-Key a déjà été utilisée avec un payload différent",
                )
            return _sortie_out(existing, creator=user)
    else:
        payload_hash = None

    requisition_uid: uuid.UUID | None = None
    if payload.requisition_id:
        try:
            requisition_uid = payload.requisition_id
            if not isinstance(requisition_uid, uuid.UUID):
                requisition_uid = uuid.UUID(str(requisition_uid))
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id UUID")

    date_paiement: datetime | None = None
    if payload.date_paiement:
        if isinstance(payload.date_paiement, datetime):
            date_paiement = payload.date_paiement
        else:
            parsed = _parse_datetime(str(payload.date_paiement))
            if parsed is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date_paiement")
            date_paiement = parsed
    # Même règle qu'à l'enregistrement d'un encaissement : l'heure du serveur
    # s'impose, sauf pour un super administrateur qui régularise une saisie.
    date_paiement = resoudre_date_operation(
        date_paiement, user=user, champ="date_paiement"
    )

    canal = (payload.canal or "CAISSE").upper()
    if canal not in CANAL_PAIEMENT:
        raise HTTPException(status_code=400, detail="canal invalide")
    devise = (payload.devise or "USD").upper()
    if devise not in {"USD", "CDF"}:
        raise HTTPException(status_code=400, detail="devise invalide")
    # --- Versement à la banque : transfert interne caisse -> banque.
    # Ce n'est PAS une dépense : pas de service, pas de bénéficiaire externe,
    # pas d'imputation budgétaire. La caisse est débitée, la banque créditée.
    is_versement_banque = (payload.type_sortie or "").lower() == "versement_banque"
    # --- Approvisionnement de la caisse : transfert inverse banque -> caisse.
    # Retrait d'espèces du compte bancaire pour alimenter la caisse (petites
    # dépenses). Pas une dépense : pas de service ni d'imputation budgétaire.
    is_appro_caisse = (payload.type_sortie or "").lower() == "approvisionnement_caisse"
    is_transfert_interne = is_versement_banque or is_appro_caisse
    nature_mouvement = "TRANSFERT_INTERNE" if is_transfert_interne else normalize_nature(payload.nature_mouvement)
    impact_budgetaire = impact_for_nature(nature_mouvement)
    if getattr(payload, "impact_budgetaire", None) is not None and bool(payload.impact_budgetaire) != impact_budgetaire:
        raise HTTPException(status_code=400, detail="impact_budgetaire incompatible avec nature_mouvement")
    fonds_tiers_operation = None
    if is_transfert_interne and payload.nature_mouvement != "BUDGETAIRE" and payload.nature_mouvement != "TRANSFERT_INTERNE":
        raise HTTPException(status_code=400, detail="Nature incompatible avec un transfert interne")
    if not is_transfert_interne and nature_mouvement == "TRANSFERT_INTERNE":
        raise HTTPException(status_code=400, detail="TRANSFERT_INTERNE réservé aux types de transfert existants")
    if nature_mouvement in {"HORS_BUDGET_A_REGULARISER", "FONDS_DE_TIERS"}:
        if payload.requisition_id is not None or payload.ordre_decaissement_id is not None:
            raise HTTPException(status_code=400, detail="Un mouvement sans impact budgétaire ne peut pas être lié à une réquisition")
        requisition_uid = None
        payload.budget_poste_id = None
        payload.rubrique_code = None
    if nature_mouvement == "FONDS_DE_TIERS":
        if payload.fonds_tiers_operation_id is None:
            raise HTTPException(status_code=400, detail="fonds_tiers_operation_id requis")
        fonds_tiers_operation = await assert_fonds_tiers_refundable(
            db,
            organisation_id=tenant_id,
            operation_id=payload.fonds_tiers_operation_id,
            montant=payload.montant_paye,
            devise=devise,
        )
        # Le bénéficiaire du reversement est le tiers créancier, jamais la
        # personne qui vient chercher l'argent : la dette éteinte est celle du
        # tiers. Imposé ici et pas seulement dans le formulaire, qui peut être
        # contourné. (`beneficiaire_reel` ne portait que cette seconde lecture ;
        # plus rien ne l'écrit désormais.)
        payload.beneficiaire = (await resolve_fonds_tiers_display_name(db, fonds_tiers_operation))[0]
    elif payload.fonds_tiers_operation_id is not None:
        raise HTTPException(status_code=400, detail="fonds_tiers_operation_id réservé aux remboursements FONDS_DE_TIERS")
    if is_transfert_interne:
        if payload.requisition_id is not None or payload.ordre_decaissement_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Un transfert interne ne peut pas être rattaché à une réquisition ou un ordre de décaissement",
            )
        # Défense côté API : un transfert interne n'est pas une dépense. Même si
        # un client envoie ces champs, ils ne doivent ni numéroter par service ni
        # polluer le budget.
        requisition_uid = None
        payload.service_id = None
        payload.budget_poste_id = None
        payload.rubrique_code = None
        payload.mode_paiement = "cash"
    if is_appro_caisse:
        canal = "BANQUE"  # l'argent sort du compte bancaire
        if payload.compte_bancaire_id is None:
            raise HTTPException(
                status_code=400,
                detail="Compte bancaire source requis pour approvisionner la caisse",
            )
        if not (payload.beneficiaire or "").strip():
            payload.beneficiaire = "Caisse centrale"
    compte_bancaire = None
    compte_destination = None
    if is_versement_banque:
        canal = "CAISSE"  # l'argent sort physiquement de la caisse
        if payload.compte_bancaire_id is None:
            raise HTTPException(
                status_code=400,
                detail="Compte bancaire de destination requis pour un versement à la banque",
            )
        res = await db.execute(
            select(CompteBancaire)
            .where(
                CompteBancaire.id == payload.compte_bancaire_id,
                CompteBancaire.organisation_id == tenant_id,
            )
            .with_for_update()
        )
        compte_destination = res.scalar_one_or_none()
        if compte_destination is None or compte_destination.is_active is False:
            raise HTTPException(status_code=400, detail="Compte de destination invalide")
        if (compte_destination.account_type or "BANK").upper() != "BANK":
            raise HTTPException(
                status_code=400,
                detail="La destination d'un versement doit être un compte bancaire (pas une caisse)",
            )
        if (compte_destination.devise or "").upper() != devise:
            raise HTTPException(status_code=400, detail="Devise incompatible avec le compte de destination")
        if not (payload.beneficiaire or "").strip():
            # Le nom de la banque est relu par une requête plutôt que par la
            # relation : `compte_destination` vient d'un SELECT ... FOR UPDATE,
            # qui interdit la jointure externe d'un chargement empressé, et lire
            # `.banque` déclencherait un accès paresseux hors contexte async —
            # une erreur 500 sur un versement dont le bénéficiaire est laissé
            # vide, c'est-à-dire sur un payload parfaitement légitime.
            banque_nom = (
                await db.scalar(select(Banque.nom).where(Banque.id == compte_destination.banque_id))
                if compte_destination.banque_id
                else None
            )
            payload.beneficiaire = banque_nom or compte_destination.intitule or "Banque"
    elif payload.compte_bancaire_id is not None:
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
            raise HTTPException(status_code=400, detail="devise incompatible avec le compte bancaire")
        if canal == "BANQUE" and (compte_bancaire.account_type or "").upper() != "BANK":
            raise HTTPException(status_code=400, detail="compte_bancaire_id invalide")
        if canal == "CAISSE" and (compte_bancaire.account_type or "").upper() != "CASH":
            raise HTTPException(status_code=400, detail="compte_bancaire_id invalide")
    if not is_versement_banque and canal == "BANQUE" and payload.compte_bancaire_id is None:
        raise HTTPException(status_code=400, detail="compte_bancaire_id requis pour canal BANQUE")


    montant_paye = payload.montant_paye
    # Garde-fou : un montant nul ou négatif créditerait la trésorerie au lieu
    # de la débiter (défense en profondeur, en plus de la contrainte du schéma).
    if montant_paye is None or Decimal(montant_paye) <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le montant doit être strictement positif")
    service_id: int | None = None
    ordre: OrdreDecaissement | None = None
    # Répartition multi-postes portée par l'ordre de décaissement (le cas échéant).
    ordre_postes: list[tuple[int, Decimal]] = []
    multi_poste = False
    # L'imputation suit les lignes de l'ordre dès qu'il en porte (1 OU plusieurs
    # postes) : une tranche progressive définit elle-même son/ses poste(s).
    impute_via_ordre = False
    # Répartition retenue pour l'imputation : celle de l'ordre s'il y en a un, sinon
    # celle des lignes de la réquisition (réquisition multi-postes payée directement).
    # Liste de (budget_poste_id, montant dans la devise de la sortie).
    repartition_postes: list[tuple[int, Decimal]] = []
    req: Requisition | None = None

    # --- Sortie directe (sans réquisition) : la caisse ne fait qu'exécuter un
    # ordre programmé au préalable par un utilisateur disposant de
    # can_direct_disbursement (plafond 100 USD contrôlé à la programmation).
    if (payload.type_sortie or "").lower() == "sortie_directe":
        if payload.requisition_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Une sortie directe ne peut pas référencer une réquisition",
            )
        if payload.ordre_decaissement_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Sortie directe : la caisse exécute uniquement un ordre programmé "
                    "par un utilisateur habilité (can_direct_disbursement)"
                ),
            )
        ordre_res = await db.execute(
            select(OrdreDecaissement)
            .where(
                OrdreDecaissement.id == payload.ordre_decaissement_id,
                OrdreDecaissement.organisation_id == tenant_id,
                OrdreDecaissement.requisition_id.is_(None),
            )
            .with_for_update()
        )
        ordre = ordre_res.scalar_one_or_none()
        if ordre is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ordre de sortie directe introuvable",
            )
        if ordre.statut != "AUTORISE":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cet ordre de sortie directe a déjà été payé ou annulé",
            )
        # Verrouillage : montant, bénéficiaire et devise proviennent de l'ordre
        if payload.montant_paye is not None and Decimal(payload.montant_paye) != Decimal(ordre.montant or 0):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Montant différent de l'ordre de sortie directe autorisé",
            )
        payload.beneficiaire = ordre.beneficiaire
        devise = (ordre.devise or "USD").upper()
        if compte_bancaire is not None and (compte_bancaire.devise or "").upper() != devise:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Devise de l'ordre incompatible avec le compte sélectionné",
            )
        montant_paye = ordre.montant
        # Service et poste budgétaire définis à la programmation : ils sont
        # verrouillés côté caisse (comme pour une réquisition mono-poste).
        if ordre.service_id is not None:
            if payload.service_id is not None and int(payload.service_id) != int(ordre.service_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Service différent de la sortie directe programmée",
                )
            payload.service_id = ordre.service_id
        lignes_ordre = ordre.lignes or []
        postes_ordre = sorted({
            int(ligne["budget_poste_id"])
            for ligne in lignes_ordre
            if isinstance(ligne, dict) and ligne.get("budget_poste_id") is not None
        })
        if len(postes_ordre) == 1:
            if payload.budget_poste_id is not None and int(payload.budget_poste_id) != postes_ordre[0]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Poste budgétaire verrouillé par la sortie directe programmée",
                )
            payload.budget_poste_id = postes_ordre[0]
        ordre_postes = [
            (int(ligne["budget_poste_id"]), Decimal(str(ligne.get("montant", ligne.get("montant_total")) or 0)))
            for ligne in (ordre.lignes or [])
            if isinstance(ligne, dict) and ligne.get("budget_poste_id") is not None
        ]
        multi_poste = len({pid for pid, _ in ordre_postes}) > 1
        impute_via_ordre = len(ordre_postes) > 0
        repartition_postes = list(ordre_postes)
    if requisition_uid:
        req_res = await db.execute(
            select(Requisition)
            .where(
                Requisition.id == requisition_uid,
                Requisition.organisation_id == tenant_id,
            )
            .with_for_update()
        )
        req = req_res.scalar_one_or_none()
        if req is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")
        allowed_statuses = {"APPROUVEE", "EN_DECAISSEMENT"}
        if req.status not in allowed_statuses:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "La réquisition doit être validée techniquement avant la sortie de fonds "
                    "et ne doit pas être déjà payée"
                ),
            )
        # Réquisition classique déjà « en décaissement » : les compléments de
        # paiement (paiements partiels) sont autorisés. Le garde-fou de cumul
        # ci-dessous (calculé sous verrou FOR UPDATE) interdit tout dépassement
        # du montant total et donc tout double débit (cf. audit DB-01).

        # --- Réquisition à décaissement progressif : la sortie passe
        # obligatoirement par un ordre de décaissement autorisé par le demandeur.
        if bool(getattr(req, "decaissement_progressif", False)):
            if payload.ordre_decaissement_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "Réquisition à décaissement progressif : la sortie de fonds requiert "
                        "un ordre de décaissement autorisé par le demandeur"
                    ),
                )
            ordre_res = await db.execute(
                select(OrdreDecaissement)
                .where(
                    OrdreDecaissement.id == payload.ordre_decaissement_id,
                    OrdreDecaissement.organisation_id == tenant_id,
                )
                .with_for_update()
            )
            ordre = ordre_res.scalar_one_or_none()
            if ordre is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ordre de décaissement introuvable")
            if ordre.requisition_id != req.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="L'ordre de décaissement ne correspond pas à cette réquisition",
                )
            if ordre.statut != "AUTORISE":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cet ordre de décaissement a déjà été payé ou annulé",
                )
            # Verrouillage : montant, bénéficiaire et devise proviennent de l'ordre
            if payload.montant_paye is not None and Decimal(payload.montant_paye) != Decimal(ordre.montant or 0):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Montant différent de l'ordre de décaissement autorisé",
                )
            payload.beneficiaire = ordre.beneficiaire
            devise = (ordre.devise or "USD").upper()
            if compte_bancaire is not None and (compte_bancaire.devise or "").upper() != devise:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Devise de l'ordre incompatible avec le compte bancaire",
                )
            ordre_postes = [
                (int(ligne["budget_poste_id"]), Decimal(str(ligne.get("montant", ligne.get("montant_total")) or 0)))
                for ligne in (ordre.lignes or [])
                if isinstance(ligne, dict) and ligne.get("budget_poste_id") is not None
            ]
            multi_poste = len({pid for pid, _ in ordre_postes}) > 1
            impute_via_ordre = len(ordre_postes) > 0
            repartition_postes = list(ordre_postes)
        elif payload.ordre_decaissement_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ordre_decaissement_id fourni pour une réquisition sans décaissement progressif",
            )
        # Référence du règlement : l'ordre de décaissement quand il y en a un —
        # c'est lui qui porte la décision ferme du volet — sinon la réquisition
        # elle-même. Une réquisition à règlement mixte n'impose rien à ce
        # niveau : chacun de ses volets est arbitré par son propre ordre.
        reference_mode = ordre.mode_paiement if ordre is not None else req.mode_paiement
        if normaliser_mode(reference_mode) == MODE_PAIEMENT_MIXTE:
            reference_mode = None
        if reference_mode and payload.mode_paiement:
            if normaliser_mode(reference_mode) != normaliser_mode(payload.mode_paiement):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "Mode de paiement différent de l'ordre de décaissement autorisé"
                        if ordre is not None
                        else "Mode de paiement différent de la réquisition approuvée"
                    ),
                )
        if reference_mode:
            expected_canal = canal_pour_mode(reference_mode)
            if payload.canal and str(payload.canal).upper() != expected_canal:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "Canal de paiement différent de l'ordre de décaissement autorisé"
                        if ordre is not None
                        else "Canal de paiement différent de la réquisition approuvée"
                    ),
                )
        # Le compte d'où sort l'argent est verrouillé par l'ordre au même titre
        # que le montant et le bénéficiaire : la caisse exécute, elle ne choisit
        # pas la banque de départ.
        if ordre is not None and ordre.compte_bancaire_id is not None:
            if (
                payload.compte_bancaire_id is not None
                and payload.compte_bancaire_id != ordre.compte_bancaire_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Compte bancaire différent de l'ordre de décaissement autorisé",
                )
        # --- Réquisition classique : paiement partiel autorisé (complément).
        # Le montant payé ne peut pas dépasser le reste dû = montant total −
        # somme des sorties VALIDES déjà rattachées. Le cumul est lu sous verrou
        # (req FOR UPDATE), ce qui sérialise les paiements concurrents et empêche
        # tout dépassement / double débit (cf. audit DB-01).
        montant_demande = Decimal(req.montant_total or 0)
        if ordre is None:
            deja_paye_res = await db.execute(
                select(func.coalesce(func.sum(SortieFonds.montant_paye), 0)).where(
                    SortieFonds.requisition_id == req.id,
                    SortieFonds.organisation_id == tenant_id,
                    SortieFonds.statut == "VALIDE",
                )
            )
            deja_paye_req = Decimal(str(deja_paye_res.scalar_one() or 0))
            reste_req = Decimal(req.montant_total or 0) - deja_paye_req
            if reste_req <= 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Réquisition déjà soldée : aucun reste à payer.",
                )
            montant_demande = (
                Decimal(payload.montant_paye) if payload.montant_paye is not None else reste_req
            )
            if montant_demande <= 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Le montant doit être strictement positif",
                )
            if montant_demande > reste_req:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Montant supérieur au reste dû : total {req.montant_total}, "
                        f"déjà payé {deja_paye_req}, reste {reste_req}."
                    ),
                )
        if payload.service_id is not None and req.service_id is not None:
            if int(payload.service_id) != int(req.service_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Service différent de la réquisition approuvée",
                )
        montant_paye = ordre.montant if ordre is not None else montant_demande

        lignes_res = await db.execute(
            select(LigneRequisition.budget_poste_id, LigneRequisition.montant_total).where(
                LigneRequisition.requisition_id == requisition_uid
            )
        )
        lignes_req = [(int(pid), Decimal(str(montant or 0))) for pid, montant in lignes_res.all() if pid is not None]
        unique_lignes = sorted({pid for pid, _ in lignes_req})
        if not unique_lignes:
            if payload.budget_poste_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Réquisition sans rubrique budgétaire",
                )
            service_id = req.service_id
        elif impute_via_ordre:
            # Tranche de décaissement progressif : l'imputation est portée par les
            # lignes de l'ordre (1 OU plusieurs postes) — aucune désambiguïsation à
            # partir des rubriques de la réquisition.
            service_id = req.service_id
        elif len(unique_lignes) > 1:
            # --- Réquisition multi-postes payée sans ordre de décaissement.
            # Les postes sont définis en amont, dans les lignes de la réquisition :
            # la caisse ne les ressaisit pas. On répartit le montant payé AU PRORATA
            # du poids de chaque poste dans la réquisition, de sorte qu'un paiement
            # partiel entame chaque poste dans la même proportion et que le cumul des
            # paiements retombe exactement sur les montants d'origine.
            postes_req: dict[int, Decimal] = {}
            for pid, montant_ligne in lignes_req:
                postes_req[pid] = postes_req.get(pid, Decimal("0")) + montant_ligne
            total_lignes = sum(postes_req.values())
            if total_lignes <= 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Réquisition multi-postes sans montant réparti sur les rubriques",
                )
            # Les lignes et la sortie partagent la devise de la réquisition (le montant
            # payé est comparé au montant total sans conversion, cf. contrôle du reste dû).
            parts = [
                (pid, (montant_paye * montant / total_lignes).quantize(Decimal("0.01")))
                for pid, montant in sorted(postes_req.items())
            ]
            # Le reliquat d'arrondi (au plus quelques centimes) va au poste le plus
            # élevé : la somme des imputations vaut exactement le montant payé.
            ecart = montant_paye - sum(m for _, m in parts)
            if ecart != 0 and parts:
                imax = max(range(len(parts)), key=lambda i: parts[i][1])
                parts[imax] = (parts[imax][0], parts[imax][1] + ecart)
            repartition_postes = parts
            multi_poste = True
            if payload.budget_poste_id is not None:
                # Aucun poste unique ne peut représenter la sortie : on ignore une
                # éventuelle sélection résiduelle plutôt que de l'imputer à tort.
                payload.budget_poste_id = None
            service_id = req.service_id
        else:
            locked_budget_id = unique_lignes[0]
            if payload.budget_poste_id and int(payload.budget_poste_id) != locked_budget_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Rubrique verrouillée par la réquisition",
                )
            payload.budget_poste_id = locked_budget_id
            service_id = req.service_id
    elif payload.service_id is not None:
        await _resolve_service(payload.service_id, db)
        service_id = payload.service_id

    # Imputation budgétaire : liste (poste, montant converti en devise budget).
    # Un seul élément dans le cas classique, plusieurs pour un décaissement réparti.
    imputations: list[tuple[BudgetPoste, Decimal]] = []
    # Montant réellement décaissé pour chaque imputation, dans la devise de la
    # sortie. `imputations` porte la conversion vers la devise du budget : les
    # deux ne coïncident qu'en USD, et l'imputation persistée garde les deux.
    montants_mouvement: list[Decimal] = []
    if not impact_budgetaire:
        # Un transfert interne (caisse <-> banque) n'est pas une dépense :
        # aucune imputation budgétaire. Même règle pour hors budget/fonds tiers.
        budget_line = None
        montant_paye_budget = Decimal("0")
    elif repartition_postes:
        # Imputation répartie : chaque poste est débité selon la répartition retenue —
        # les lignes de l'ordre pour une tranche progressive, celles de la réquisition
        # (au prorata) pour une réquisition multi-postes. La somme vaut le montant payé.
        budget_line = None
        montant_paye_budget = Decimal("0")
        await _assert_budget_rate(db, tenant_id, devise)
        for pid, montant_ligne in repartition_postes:
            res_bp = await db.execute(
                select(BudgetPoste)
                .where(BudgetPoste.id == pid, BudgetPoste.is_deleted.is_(False))
                .with_for_update()
            )
            bl = res_bp.scalar_one_or_none()
            if bl is None or (bl.type or "").upper() != "DEPENSE":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Poste budgétaire invalide dans la répartition (id {pid})",
                )
            m_budget = await _to_budget_currency(db, tenant_id, montant_ligne, devise)
            if m_budget > 0 and (bl.montant_paye or 0) + m_budget > (bl.montant_prevu or 0):
                if not await _can_force_budget_overrun(db, user, tenant_id):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"Dépassement budgétaire (poste {bl.code}): plafond "
                            f"{bl.montant_prevu}, déjà payé {bl.montant_paye}, demandé {m_budget}"
                        ),
                    )
            imputations.append((bl, m_budget))
            montants_mouvement.append(montant_ligne)
        # Tranche ne visant qu'un seul poste : on le référence sur la sortie
        # (budget_poste_id/libellé) au lieu de « Réparti sur N postes ».
        if len({p.id for p, _ in imputations}) == 1:
            budget_line = imputations[0][0]
            payload.budget_poste_id = budget_line.id
    else:
        if payload.budget_poste_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="budget_poste_id requis")
        budget_res = await db.execute(
            select(BudgetPoste)
            .where(
                BudgetPoste.id == payload.budget_poste_id,
                BudgetPoste.is_deleted.is_(False),
            )
            .with_for_update()
        )
        budget_line = budget_res.scalar_one_or_none()
        if budget_line is None or (budget_line.type or "").upper() != "DEPENSE":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="budget_poste_id invalide (type DEPENSE requis)")
        if budget_line.active is False:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Rubrique budgétaire inactive")

        # Garde-fou : pas d'imputation budgétaire en devise étrangère sans taux.
        await _assert_budget_rate(db, tenant_id, devise)
        plafond = (budget_line.montant_prevu or 0)
        deja_paye = (budget_line.montant_paye or 0)
        # Montant converti dans la devise de base du budget (USD) : on ne compare et
        # n'additionne jamais des devises différentes sur un poste budgétaire.
        montant_paye_budget = await _to_budget_currency(db, tenant_id, montant_paye, devise)
        if montant_paye_budget > 0 and deja_paye + montant_paye_budget > plafond:
            can_force = await _can_force_budget_overrun(db, user, tenant_id)
            if not can_force:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Dépassement budgétaire: plafond {plafond}, déjà payé {deja_paye}, demandé {montant_paye_budget}",
                )
        imputations = [(budget_line, montant_paye_budget)]
        montants_mouvement = [montant_paye]

    # --- Bascule d'écriture : ce type, pour cette organisation, part au moteur
    # dédié. Placée ici, après toutes les validations de payload (compte actif,
    # de type BANK, devise concordante, montant strictement positif) et avant
    # tout verrou, toute numérotation et toute écriture : la délégation ne
    # relâche aucun contrôle et ne consomme pas un numéro `PAY-` pour rien.
    # Drapeau fermé, cette ligne ne fait rien.
    if is_transfert_interne and delegue_au_moteur(payload.type_sortie, tenant_id):
        return await _deleguer_transfert_interne(
            db,
            compte_bancaire_id=payload.compte_bancaire_id,
            vers_la_banque=is_versement_banque,
            montant=montant_paye,
            devise=devise,
            date_operation=date_paiement,
            tenant_id=tenant_id,
            user=user,
            request=request,
            idempotency_key=effective_idempotency_key,
            payload_hash=payload_hash,
        )

    solde_disponible = None
    if canal == "CAISSE":
        caisse = await _get_or_create_caisse(db, tenant_id)
        res = await db.execute(
            select(CaisseCentrale)
            .where(CaisseCentrale.id == caisse.id, CaisseCentrale.organisation_id == tenant_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        caisse = res.scalar_one()
        if not caisse.est_ouverte:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Caisse fermée : ouvrez la caisse avant d'enregistrer une sortie.",
            )
        solde_disponible = caisse.solde_usd if devise == "USD" else caisse.solde_cdf
        if montant_paye > solde_disponible:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Fonds insuffisants en caisse ({solde_disponible} {devise})",
            )
    else:
        res = await db.execute(
            select(CompteBancaire)
            .where(
                CompteBancaire.id == payload.compte_bancaire_id,
                CompteBancaire.organisation_id == tenant_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        compte_bancaire = res.scalar_one()
        solde_disponible = compte_bancaire.solde_actuel or 0
        if montant_paye > solde_disponible:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Fonds insuffisants sur le compte ({solde_disponible} {devise})",
            )

    # Get service_id for numbering
    service_id = payload.service_id
    if not service_id and payload.requisition_id:
        req_res = await db.execute(select(Requisition.service_id).where(Requisition.id == payload.requisition_id))
        service_id = req_res.scalar_one_or_none()

    reference_numero = await generate_document_number(db, "PAY", tenant_id, service_id=service_id)
    settings_res = await db.execute(
        select(PrintSettings).where(PrintSettings.organisation_id == tenant_id).limit(1)
    )
    print_settings = settings_res.scalar_one_or_none()
    exchange_rate_snapshot = None
    if print_settings is not None:
        try:
            if print_settings.exchange_rate_cdf:
                exchange_rate_snapshot = float(print_settings.exchange_rate_cdf or 0)
            else:
                exchange_rate_snapshot = float(print_settings.exchange_rate or 0)
        except (TypeError, ValueError):
            exchange_rate_snapshot = None
    # La création de la sortie ne doit PAS dépendre de l'existence de
    # PrintSettings : une organisation sans réglages d'impression doit pouvoir
    # enregistrer une sortie de fonds (le snapshot de taux reste optionnel).
    sortie = SortieFonds(
        type_sortie=payload.type_sortie,
        organisation_id=tenant_id,
        requisition_id=requisition_uid,
        rubrique_code=payload.rubrique_code,
        budget_poste_id=(None if multi_poste else payload.budget_poste_id),
        budget_poste_code=(None if multi_poste else (budget_line.code if budget_line else None)),
        budget_poste_libelle=(
            f"Réparti sur {len(imputations)} postes"
            if multi_poste
            else (budget_line.libelle if budget_line else None)
        ),
        service_id=service_id,
        montant_paye=montant_paye,
        date_paiement=date_paiement,
        mode_paiement=payload.mode_paiement,
        reference=payload.reference,
        devise=devise,
        canal=canal,
        compte_bancaire_id=payload.compte_bancaire_id,
        reference_numero=reference_numero,
        idempotency_key=effective_idempotency_key,
        idempotency_payload_hash=payload_hash,
        nature_mouvement=nature_mouvement,
        impact_budgetaire=impact_budgetaire,
        hors_budget_status=hors_budget_initial_status(nature_mouvement),
        fonds_tiers_operation_id=(fonds_tiers_operation.id if fonds_tiers_operation is not None else None),
        exchange_rate_snapshot=exchange_rate_snapshot,
        statut=payload.statut or "VALIDE",
        # Motif défini en amont sur l'ordre (ex. « première tranche ») : il fait foi
        # pour la sortie liée à un ordre de décaissement.
        motif=(ordre.motif if (ordre is not None and ordre.motif) else payload.motif),
        beneficiaire=payload.beneficiaire,
        piece_justificative=payload.piece_justificative,
        commentaire=payload.commentaire,
        created_by=user.id,
        # Programmeur (demandeur) : repris de l'ordre pour les sorties directes.
        programme_par_id=(ordre.autorise_par if ordre is not None else None),
    )
    db.add(sortie)
    await db.flush()  # garantit sortie.id, requis par la génération comptable et par le règlement d'un ordre
    if canal == "CAISSE":
        if devise == "USD":
            caisse.solde_usd = (caisse.solde_usd or 0) - montant_paye
        else:
            caisse.solde_cdf = (caisse.solde_cdf or 0) - montant_paye
        caisse.derniere_maj = datetime.now(timezone.utc)
    else:
        compte_bancaire.solde_actuel = (compte_bancaire.solde_actuel or 0) - montant_paye
    # Versement à la banque : créditer le compte bancaire de destination.
    if is_versement_banque and compte_destination is not None:
        compte_destination.solde_actuel = (compte_destination.solde_actuel or 0) + montant_paye
    # Approvisionnement de la caisse : créditer la caisse (banque déjà débitée).
    if is_appro_caisse:
        caisse_appro = await _get_or_create_caisse(db, tenant_id)
        res = await db.execute(
            select(CaisseCentrale)
            .where(CaisseCentrale.id == caisse_appro.id, CaisseCentrale.organisation_id == tenant_id)
            .with_for_update()
        )
        caisse_appro = res.scalar_one()
        if not caisse_appro.est_ouverte:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Caisse fermée : ouvrez la caisse avant de l'approvisionner.",
            )
        if devise == "USD":
            caisse_appro.solde_usd = (caisse_appro.solde_usd or 0) + montant_paye
        else:
            caisse_appro.solde_cdf = (caisse_appro.solde_cdf or 0) + montant_paye
        caisse_appro.derniere_maj = datetime.now(timezone.utc)
    for (poste_impute, montant_impute), montant_mouvement in zip(imputations, montants_mouvement, strict=True):
        await create_budget_imputation(
            db,
            organisation_id=tenant_id,
            sortie_fonds_id=sortie.id,
            budget_poste_id=poste_impute.id,
            sens="DEPENSE_PAYEE",
            montant_mouvement=montant_mouvement,
            devise_mouvement=devise,
            montant_budget=montant_impute,
            exchange_rate_snapshot=exchange_rate_snapshot,
            created_by=user.id,
        )
        poste_impute.montant_paye = (poste_impute.montant_paye or 0) + montant_impute

    # --- Génération automatique de l'écriture comptable (module Comptabilité,
    # opt-in) : silencieusement ignorée pour les organisations qui n'ont pas
    # activé le module, échec bloquant sinon (mapping manquant) — cf.
    # generation_service.py.
    integration_mode = await get_accounting_integration_mode(db, tenant_id)
    sortie.statut_comptabilisation = status_for_recorded_operation(integration_mode)
    sortie.message_comptabilisation = None
    if integration_mode == "manual":
        sortie.message_comptabilisation = "Écriture comptable à saisir manuellement."
    if integration_mode == "automatic":
        libelle_ecriture = sortie.motif or sortie.beneficiaire or f"Sortie de fonds {reference_numero}"
        try:
            if is_versement_banque or is_appro_caisse:
                await generer_ecriture_transfert_interne(
                    db,
                    organisation_id=tenant_id,
                    sortie_fonds_id=str(sortie.id),
                    date_operation=date_paiement.date(),
                    montant=montant_paye,
                    devise=devise,
                    compte_origine_bancaire_id=(payload.compte_bancaire_id if is_appro_caisse else None),
                    compte_destination_bancaire_id=(payload.compte_bancaire_id if is_versement_banque else None),
                    libelle=libelle_ecriture,
                    created_by=user.id,
                )
            elif impact_budgetaire:
                await generer_ecriture_sortie_fonds(
                    db,
                    organisation_id=tenant_id,
                    sortie_fonds_id=str(sortie.id),
                    date_operation=date_paiement.date(),
                    montant=montant_paye,
                    devise=devise,
                    canal=canal,
                    compte_bancaire_id=payload.compte_bancaire_id,
                    budget_poste_id=(None if multi_poste else payload.budget_poste_id),
                    libelle=libelle_ecriture,
                    created_by=user.id,
                    imputations=([(p.id, m) for p, m in imputations] if multi_poste else None),
                )
            if impact_budgetaire or is_versement_banque or is_appro_caisse:
                sortie.statut_comptabilisation = STATUT_COMPTABILISEE
            else:
                sortie.statut_comptabilisation = "A_COMPTABILISER_MANUELLEMENT"
                sortie.message_comptabilisation = "Mouvement sans impact budgétaire: écriture comptable technique à traiter."
        except HTTPException as exc:
            # Échec bloquant volontaire : la transaction entière est annulée.
            # Positionner STATUT_ERREUR_COMPTABLE serait perdu au rollback.
            raise HTTPException(
                status_code=exc.status_code,
                detail=(
                    "Impossible de générer l'écriture comptable automatique. "
                    f"{exc.detail} Paramètres > Comptabilité > Mode d'intégration comptable."
                ),
            ) from exc

    if req is not None and ordre is None:
        now_req = datetime.now(timezone.utc)
        old_req_status = req.status
        # Cumul des sorties VALIDES de la réquisition (la sortie courante est déjà
        # flushée, cf. db.flush() plus haut) : on ne solde (PAYEE) que lorsque le
        # total est atteint ; un paiement partiel laisse la réquisition
        # EN_DECAISSEMENT, prête à recevoir le(s) complément(s).
        total_paye_req = (
            await db.execute(
                select(func.coalesce(func.sum(SortieFonds.montant_paye), 0)).where(
                    SortieFonds.requisition_id == req.id,
                    SortieFonds.organisation_id == tenant_id,
                    SortieFonds.statut == "VALIDE",
                )
            )
        ).scalar_one() or 0
        if Decimal(str(total_paye_req)) >= Decimal(req.montant_total or 0):
            req.status = "PAYEE"
            req.payee_par = user.id
            req.payee_le = now_req
            comment_req = f"Réquisition soldée via la sortie de fonds {reference_numero}"
        else:
            req.status = "EN_DECAISSEMENT"
            comment_req = (
                f"Paiement partiel via la sortie de fonds {reference_numero} "
                f"(cumul {total_paye_req}/{req.montant_total})"
            )
        req.updated_at = now_req
        record_status_history(
            db=db,
            requisition=req,
            old_status=old_req_status,
            new_status=req.status,
            user=user,
            comment=comment_req,
        )

    # --- Règlement d'un ordre de décaissement (progressif ou sortie directe)
    if ordre is not None:
        await db.flush()  # garantit sortie.id
        now_od = datetime.now(timezone.utc)
        ordre.statut = "PAYE"
        ordre.paye_par = user.id
        ordre.paye_le = now_od
        ordre.sortie_fonds_id = sortie.id
        ordre.updated_at = now_od

    if ordre is not None and ordre.requisition_id is not None:
        total_paye_od = (
            await db.execute(
                select(func.coalesce(func.sum(OrdreDecaissement.montant), 0)).where(
                    OrdreDecaissement.requisition_id == req.id,
                    OrdreDecaissement.statut == "PAYE",
                )
            )
        ).scalar_one() or 0

        old_req_status = req.status
        if Decimal(total_paye_od) >= Decimal(req.montant_total or 0):
            req.status = "PAYEE"
            req.payee_par = req.payee_par or user.id
            req.payee_le = req.payee_le or now_od
        else:
            req.status = "EN_DECAISSEMENT"
        req.updated_at = now_od
        record_status_history(
            db=db,
            requisition=req,
            old_status=old_req_status,
            new_status=req.status,
            user=user,
            comment=f"Ordre de décaissement {ordre.numero_ordre} payé ({ordre.montant} {ordre.devise})",
        )

    await log_action(
        db,
        user_id=user.id,
        action="SORTIE_CREATED",
        target_table="sorties_fonds",
        target_id=str(sortie.id),
        new_value={
            "reference_numero": sortie.reference_numero,
            "montant_paye": float(sortie.montant_paye or 0),
            "statut": sortie.statut,
            "beneficiaire": sortie.beneficiaire,
            "nature_mouvement": sortie.nature_mouvement,
            "impact_budgetaire": sortie.impact_budgetaire,
            "fonds_tiers_operation_id": str(sortie.fonds_tiers_operation_id) if sortie.fonds_tiers_operation_id else None,
            "requisition_id": str(sortie.requisition_id) if sortie.requisition_id else None,
        },
        ip_address=get_request_ip(request),
    )
    if fonds_tiers_operation is not None:
        await refresh_fonds_tiers_status(db, organisation_id=tenant_id, operation=fonds_tiers_operation)

    # Solde après opération, capturé AVANT le commit. `solde_disponible` a été
    # lu sous verrou (FOR UPDATE) au moment du contrôle de provision, et
    # `montant_paye` vient d'en être retranché sur la caisse ou le compte. Le
    # relire après le commit obligerait à recharger l'objet de trésorerie —
    # requête inutile, et lecture différée hors contexte qui lèverait un
    # MissingGreenlet. Ici, ce ne sont plus que deux Decimal.
    solde_apres_operation = None
    if solde_disponible is not None:
        try:
            solde_apres_operation = Decimal(str(solde_disponible)) - Decimal(str(montant_paye))
        except (TypeError, ValueError, ArithmeticError):
            solde_apres_operation = None

    await db.commit()
    await invalidate_report_summary_cache(tenant_id)
    await db.refresh(sortie)

    requisition: Requisition | None = None
    creator: User | None = user
    validateur: User | None = None
    approbateur: User | None = None
    remboursement_transport: dict[str, Any] | None = None
    if sortie.requisition_id:
        req_res = await db.execute(
            select(Requisition).where(
                Requisition.id == sortie.requisition_id,
                Requisition.organisation_id == tenant_id,
            )
        )
        requisition = req_res.scalar_one_or_none()
        if requisition:
            u_ids = []
            if requisition.validee_par: u_ids.append(requisition.validee_par)
            if requisition.approuvee_par: u_ids.append(requisition.approuvee_par)
            if u_ids:
                u_res = await db.execute(select(User).where(User.id.in_(u_ids)))
                u_map = {u.id: u for u in u_res.scalars().all()}
                validateur = u_map.get(requisition.validee_par)
                approbateur = u_map.get(requisition.approuvee_par)
            remb_res = await db.execute(
                select(RemboursementTransport).where(RemboursementTransport.requisition_id == requisition.id)
            )
            remboursement_transport = _remboursement_transport_payload(remb_res.scalar_one_or_none())

    # Sortie de fonds : le Bureau est prévenu ici, et seulement ici — c'est le
    # moment où l'argent a réellement quitté la trésorerie. `requisition`,
    # `validateur` et `approbateur` sont déjà chargés juste au-dessus : aucune
    # requête n'est ajoutée pour les besoins du message. `tranche` reste vide,
    # faute d'une donnée fiable sur le nombre total de tranches (voir
    # RAPPORT-hooks.md).
    await _notify_sortie_fonds_whatsapp(
        db,
        background_tasks,
        sortie=sortie,
        tenant_id=tenant_id,
        auteur=creator,
        validateur=validateur,
        solde_apres=solde_apres_operation,
    )

    return _sortie_out(
        sortie,
        requisition,
        creator=creator,
        validateur=validateur,
        approbateur=approbateur,
        remboursement_transport=remboursement_transport,
    )


@router.post("/requisitions/{requisition_id}/reject", response_model=RequisitionOut)
async def reject_requisition_at_payment(
    requisition_id: str,
    payload: SortieFondsPaymentRejectPayload,
    request: Request,
    user: User = Depends(has_permission("can_execute_payment")),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> RequisitionOut:
    try:
        requisition_uid = uuid.UUID(requisition_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id UUID")

    req = await reject_requisition_at_payment_logic(
        db=db,
        requisition_id=requisition_uid,
        user=user,
        tenant_id=tenant_id,
        motif_rejet=payload.motif_rejet,
        request=request,
    )
    return _requisition_out(req)


@router.post("/{sortie_id}/pdf")
async def upload_sortie_pdf(
    sortie_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    notify: bool = True,
    attachments: list[UploadFile] | None = File(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    tenant_uuid: str = Depends(get_current_tenant_uuid),
) -> dict[str, Any]:
    try:
        sid = uuid.UUID(sortie_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid sortie_id")

    res = await db.execute(
        select(SortieFonds).where(SortieFonds.id == sid, SortieFonds.organisation_id == tenant_id)
    )
    sortie = res.scalar_one_or_none()
    # Un transfert délégué au moteur dédié n'est plus une `SortieFonds` : il est
    # adressé par le même UUID, porté cette fois par `document_uuid`. Sans ce
    # rattrapage, le bon que le caissier vient d'imprimer ne s'attacherait plus à
    # rien — et son justificatif de dépôt bancaire non plus.
    transfert = (
        None
        if sortie is not None
        else await transferts_delegues.par_document_uuid(
            db, tenant_id=tenant_id, document_uuid=sid
        )
    )
    operation = sortie if sortie is not None else transfert
    if operation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sortie not found")

    content_type = (file.content_type or "").lower()
    if content_type not in PDF_ALLOWED_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Format de fichier non autorisé")

    original_name = file.filename or "sortie.pdf"
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in PDF_ALLOWED_EXT:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Extension de fichier non autorisée")

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Fichier vide")

    ref_base = (
        (sortie.reference_numero or sortie.reference)
        if sortie is not None
        else transfert.reference
    ) or f"SORTIE-{sid}"
    safe_ref = _safe_ref(ref_base)
    filename = f"{safe_ref}-bon.pdf"
    upload_dt = datetime.now(timezone.utc)
    target_dir = _tenant_sortie_dir(tenant_uuid, upload_dt.year, upload_dt.month)
    os.makedirs(target_dir, exist_ok=True)
    dest_path = os.path.join(target_dir, filename)
    with open(dest_path, "wb") as f:
        f.write(contents)

    operation.pdf_path = f"/uploads/tenants/{tenant_uuid}/sorties-fonds/{upload_dt.year:04d}/{upload_dt.month:02d}/{filename}"
    await db.commit()

    attachment_paths: list[str] = []
    attachment_fs_paths: list[str] = []
    if attachments:
        attachment_paths = await _save_sortie_annexes(attachments, safe_ref, tenant_uuid=tenant_uuid)
        current = list(operation.annexes or [])
        for path in attachment_paths:
            if path not in current:
                current.append(path)
        operation.annexes = current
        await db.commit()
        attachment_fs_paths = [_sortie_annexe_fs_path(name) for name in attachment_paths]

    # La notification est maintenue pour un transfert délégué : le chemin
    # historique l'envoie aujourd'hui à l'attachement du bon, sans regarder le
    # type de sortie (contrairement au message WhatsApp de la création, lui
    # filtré par TYPES_SORTIE_SANS_NOTIFICATION). La supprimer ici ferait taire
    # une alerte que le trésorier reçoit déjà — ce serait une régression, pas
    # une équivalence.
    if notify:
        try:
            ns = await get_system_settings(db, tenant_id)
            smtp_cfg = resolve_smtp_config(ns)
            if smtp_cfg and ns and ns.email_tresorier:
                    org_res = await db.execute(
                        select(Organisation.nom).where(Organisation.id == tenant_id).limit(1)
                    )
                    org_name = org_res.scalar_one_or_none()
                    caissier_name = " ".join(filter(None, [user.prenom, user.nom])) or user.email or "Systeme"
                    createur_id = sortie.created_by if sortie is not None else transfert.execute_par
                    if createur_id and createur_id != user.id:
                        creator_res = await db.execute(select(User).where(User.id == createur_id))
                        creator = creator_res.scalar_one_or_none()
                        if creator:
                            caissier_name = (
                                " ".join(filter(None, [creator.prenom, creator.nom])) or creator.email or caissier_name
                            )

                    # Un transfert interne n'a jamais de réquisition : l'API le
                    # refuse à la création, dans les deux moteurs.
                    requisition_num = None
                    if sortie is not None and sortie.requisition_id:
                        req_res = await db.execute(
                            select(Requisition).where(
                                Requisition.id == sortie.requisition_id,
                                Requisition.organisation_id == tenant_id,
                            )
                        )
                        req = req_res.scalar_one_or_none()
                        if req:
                            requisition_num = req.numero_requisition or req.reference_numero

                    official_pdf_path = _sortie_pdf_fs_path(operation.pdf_path)
                    if sortie is not None:
                        num_transaction = sortie.reference_numero or sortie.reference or str(sortie.id)
                        montant_notifie = float(sortie.montant_paye or 0)
                        beneficiaire_notifie = sortie.beneficiaire
                    else:
                        num_transaction = transfert.reference or str(sid)
                        montant_notifie = float(transfert.montant or 0)
                        # Le bénéficiaire d'un mouvement interne est la poche qui
                        # reçoit : c'est la seule réponse vraie à « où est allé
                        # l'argent », et celle que porte déjà la ligne d'écran.
                        beneficiaire_notifie = await transferts_delegues.libelle_poche_destination(
                            db, transfert=transfert
                        )
                    background_tasks.add_task(
                        send_sortie_notification,
                        smtp_host=smtp_cfg.host,
                        smtp_port=smtp_cfg.port,
                        smtp_user=smtp_cfg.user,
                        smtp_password=smtp_cfg.password,
                        sender=smtp_cfg.sender,
                        tresorier_email=ns.email_tresorier,
                        cc_emails=ns.emails_bureau_sortie_cc,
                        num_transaction=num_transaction,
                        num_bon_requisition=requisition_num,
                        montant=montant_notifie,
                        beneficiaire=beneficiaire_notifie,
                        caissier_nom=caissier_name,
                        brand_name="ONEC",
                        organisation_name=org_name,
                        official_pdf_path=official_pdf_path,
                        attachment_paths=attachment_fs_paths,
                    )
        except Exception:
            logger.exception("Failed to schedule sortie notification after PDF upload")

    return {"ok": True, "pdf_path": filename}


async def _annuler_transfert_delegue(
    db: AsyncSession,
    *,
    transfert,
    payload: SortieFondsStatusUpdate,
    user: User,
    tenant_id: int,
    request: Request,
) -> SortieFondsOut:
    """Annuler un transfert délégué, c'est le contre-passer.

    Le moteur dédié ne réécrit jamais le passé : au lieu de retirer l'opération
    de sa période — qui peut être clôturée, signée et imprimée —, il lui adjoint
    un transfert inverse daté du jour. L'original reste lisible, à son montant
    et à sa date, avec le statut CONTREPASSE et le motif de la correction.

    Deux écarts assumés avec le chemin historique :

    * **pas de fenêtre de 30 minutes.** Elle protège une période passée d'être
      réécrite ; une contre-passation n'écrit que dans le présent, il n'y a donc
      rien à protéger. La refuser au-delà de 30 minutes laisserait une erreur
      sans correction possible.
    * **le motif est obligatoire.** La correction laisse deux lignes dans les
      livres : sans motif écrit, plus personne ne peut dire pourquoi il y en a
      deux.
    """
    statut = (payload.statut or "").strip().upper()
    if statut != "ANNULEE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Statut invalide (ANNULEE uniquement)",
        )
    motif = (payload.motif_annulation or "").strip()
    if len(motif) < 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Motif requis (3 caractères minimum) pour contre-passer un transfert",
        )
    await contrepasser_transfer(
        db,
        transfer_id=transfert.id,
        tenant_id=tenant_id,
        user=user,
        motif=motif,
        ip_address=get_request_ip(request),
    )
    # La réponse décrit l'opération sur laquelle l'écran vient d'agir : l'original,
    # désormais CONTREPASSE. La ligne inverse n'y figure pas — c'est une opération
    # à part entière, qui apparaît d'elle-même dans la liste.
    projection = await transferts_delegues.projeter_par_document_uuid(
        db, tenant_id=tenant_id, document_uuid=transfert.document_uuid
    )
    if projection is None:  # pragma: no cover - la ligne vient d'être relue
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sortie not found")
    return projection


#: La garde est la permission `cancel_sortie_fonds`, contrôlée dans le corps de
#: la fonction — et elle seule.
#:
#: Il y avait ici un `require_roles(["admin", "tresorerie", "comptabilite"])`.
#: Ces deux derniers codes n'existent pas : les rôles réels sont `tresorier` et
#: `comptable`. La liste ne laissait donc passer que `admin`, et le contrôle de
#: permission juste derrière n'était jamais atteint par personne d'autre — une
#: permission dédiée rendue inopérante par une liste de rôles mal orthographiée.
#: Nommer le droit une seule fois, au bon endroit, vaut mieux que le dire deux
#: fois dont une faux.
@router.post("/{sortie_id}/affecter-budget", dependencies=[Depends(has_permission("budget"))])
async def affecter_sortie_budget(
    sortie_id: str,
    payload: AffecterBudgetPayload,
    request: Request,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Impute a posteriori une sortie payée hors budget sur des postes de dépense.

    La trésorerie a déjà bougé au paiement : cette décision ne touche que le
    budget, et laisse une trace (`regularisations_budgetaires`) de qui a décidé
    quoi, avec quelle justification.
    """
    try:
        sortie_uid = uuid.UUID(sortie_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="sortie_id invalide")
    regularisation = await affecter_sortie_hors_budget(
        db,
        organisation_id=tenant_id,
        sortie_fonds_id=sortie_uid,
        lignes=[(ligne.budget_poste_id, ligne.montant) for ligne in payload.lignes],
        justification=payload.justification,
        reference=payload.reference,
        idempotency_key=payload.idempotency_key,
        user_id=user.id,
        autoriser_depassement=await _can_force_budget_overrun(db, user, tenant_id),
    )
    await log_action(
        db,
        user_id=user.id,
        action="SORTIE_HORS_BUDGET_AFFECTEE",
        target_table="regularisations_budgetaires",
        target_id=str(regularisation.id),
        new_value={
            "sortie_fonds_id": sortie_id,
            "montant": str(regularisation.montant_mouvement),
            "reference": regularisation.reference,
        },
        ip_address=get_request_ip(request),
    )
    await db.commit()
    await invalidate_report_summary_cache(tenant_id)
    return {"id": str(regularisation.id), "status": "ok"}


@router.patch(
    "/{sortie_id}/statut",
    response_model=SortieFondsOut,
)
async def update_sortie_statut(
    sortie_id: str,
    payload: SortieFondsStatusUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> SortieFondsOut:
    if not await _user_has_permission(db, user, "cancel_sortie_fonds"):
        raise HTTPException(status_code=403, detail="Privilèges insuffisants (cancel_sortie_fonds)")
    try:
        sortie_uid = uuid.UUID(sortie_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid sortie_id UUID")

    res = await db.execute(
        select(SortieFonds).where(SortieFonds.id == sortie_uid, SortieFonds.organisation_id == tenant_id)
    )
    sortie = res.scalar_one_or_none()
    if sortie is None:
        # Un transfert délégué au moteur dédié porte le même UUID, dans
        # `document_uuid`. L'écran l'annule par cette route comme n'importe
        # quelle autre ligne : c'est le backend qui sait que « annuler » veut
        # dire « contre-passer » de ce côté-là.
        transfert = await transferts_delegues.par_document_uuid(
            db, tenant_id=tenant_id, document_uuid=sortie_uid
        )
        if transfert is not None:
            return await _annuler_transfert_delegue(
                db,
                transfert=transfert,
                payload=payload,
                user=user,
                tenant_id=tenant_id,
                request=request,
            )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sortie not found")

    previous_statut = (sortie.statut or "VALIDE").strip().upper()
    statut = (payload.statut or "").strip().upper()
    allowed = {"ANNULEE"}
    if statut not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Statut invalide (ANNULEE uniquement)",
        )

    now = datetime.now(timezone.utc)
    if statut == "ANNULEE":
        reference_time = sortie.created_at or sortie.date_paiement
        if reference_time is not None:
            if reference_time.tzinfo is None:
                reference_time = reference_time.replace(tzinfo=timezone.utc)
            if now - reference_time > timedelta(minutes=30):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Annulation impossible après 30 minutes",
                )
        if previous_statut == "ANNULEE" and sortie.annulee_le:
            annulee_le = sortie.annulee_le
            if annulee_le.tzinfo is None:
                annulee_le = annulee_le.replace(tzinfo=timezone.utc)
            if now - annulee_le > timedelta(minutes=5):
                incoming_motif = (payload.motif_annulation or "").strip()
                existing_motif = (sortie.motif_annulation or "").strip()
                if incoming_motif and incoming_motif != existing_motif:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Motif d'annulation non modifiable après 5 minutes",
                    )

    # Une annulation de transfert doit pouvoir contre-passer les deux jambes.
    # Vérifier la destination avant toute modification évite une caisse recréditée
    # avec une banque tronquée, ou l'inverse.
    if previous_statut == "VALIDE" and statut == "ANNULEE":
        transfer_type = (sortie.type_sortie or "").lower()
        destination_account_id = None
        destination_label = None
        if transfer_type == "versement_banque" and sortie.compte_bancaire_id is not None:
            destination_account_id = sortie.compte_bancaire_id
            destination_label = "du compte bancaire destination"
        # Approvisionnement : la destination est la caisse, qui devra être
        # re-débitée plus bas. Même contrôle préalable, sinon la banque serait
        # recréditée avant de découvrir que la caisse ne peut pas rendre.
        if transfer_type == "approvisionnement_caisse":
            caisse_dest = await _get_or_create_caisse(db, tenant_id)
            caisse_res = await db.execute(
                select(CaisseCentrale)
                .where(CaisseCentrale.id == caisse_dest.id, CaisseCentrale.organisation_id == tenant_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            caisse_dest = caisse_res.scalar_one()
            montant_transfert = Decimal(str(sortie.montant_paye or 0))
            solde_caisse = Decimal(str(
                (caisse_dest.solde_usd if sortie.devise == "USD" else caisse_dest.solde_cdf) or 0
            ))
            if solde_caisse < montant_transfert:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Annulation refusée : le solde de caisse est insuffisant "
                        f"pour contre-passer {montant_transfert} {sortie.devise}. "
                        "Une opération corrective autorisée est nécessaire."
                    ),
                )
        if destination_account_id is not None:
            destination_res = await db.execute(
                select(CompteBancaire)
                .where(
                    CompteBancaire.id == destination_account_id,
                    CompteBancaire.organisation_id == tenant_id,
                )
                .with_for_update()
            )
            destination = destination_res.scalar_one_or_none()
            if destination is None:
                raise HTTPException(status_code=400, detail="Compte de destination introuvable pour annuler ce transfert")
            montant_transfert = Decimal(str(sortie.montant_paye or 0))
            if Decimal(str(destination.solde_actuel or 0)) < montant_transfert:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Annulation refusée : le solde {destination_label} est insuffisant "
                        f"pour contre-passer {montant_transfert} {sortie.devise}. "
                        "Une opération corrective autorisée est nécessaire."
                    ),
                )

    cancelled_persisted_budget = False
    if previous_statut == "VALIDE" and statut == "ANNULEE":
        cancelled_persisted_budget = await cancel_budget_imputations(
            db,
            organisation_id=tenant_id,
            sortie_fonds_id=sortie.id,
            user_id=user.id,
        )

    # Sans imputation persistée on retombe sur la reprise historique par
    # `budget_poste_id` : une sortie multi-postes antérieure au journal
    # d'imputations n'est toujours pas reprise, comme avant. Refuser
    # l'annulation dans ce cas bloquerait des corrections légitimes sur tout
    # l'existant ; c'est le backfill, pas l'annulation, qui doit combler ce trou.
    if not cancelled_persisted_budget and sortie.budget_poste_id:
        budget_res = await db.execute(select(BudgetPoste).where(BudgetPoste.id == sortie.budget_poste_id))
        budget_line = budget_res.scalar_one_or_none()
        if budget_line:
            was_valid = previous_statut == "VALIDE"
            will_valid = statut == "VALIDE"
            if was_valid and not will_valid:
                montant_budget = await _to_budget_currency(
                    db,
                    tenant_id,
                    sortie.montant_paye,
                    sortie.devise,
                    exchange_rate_snapshot=sortie.exchange_rate_snapshot,
                )
                budget_line.montant_paye = max(0, (budget_line.montant_paye or 0) - montant_budget)

    if previous_statut == "VALIDE" and statut == "ANNULEE":
        if sortie.canal == "CAISSE":
            caisse = await _get_or_create_caisse(db, tenant_id)
            res = await db.execute(
                select(CaisseCentrale)
                .where(CaisseCentrale.id == caisse.id, CaisseCentrale.organisation_id == tenant_id)
                .with_for_update()
            )
            caisse = res.scalar_one()
            if sortie.devise == "USD":
                caisse.solde_usd = (caisse.solde_usd or 0) + (sortie.montant_paye or 0)
            else:
                caisse.solde_cdf = (caisse.solde_cdf or 0) + (sortie.montant_paye or 0)
            caisse.derniere_maj = now
        elif sortie.compte_bancaire_id is not None:
            res = await db.execute(
                select(CompteBancaire)
                .where(
                    CompteBancaire.id == sortie.compte_bancaire_id,
                    CompteBancaire.organisation_id == tenant_id,
                )
                .with_for_update()
            )
            compte_bancaire = res.scalar_one_or_none()
            if compte_bancaire is None:
                raise HTTPException(status_code=400, detail="Compte de décaissement introuvable pour annuler cette sortie")
            compte_bancaire.solde_actuel = (compte_bancaire.solde_actuel or 0) + (sortie.montant_paye or 0)
        # Annulation d'un versement caisse -> banque : re-débiter le compte
        # bancaire de destination (la caisse a déjà été re-créditée ci-dessus).
        if (
            (sortie.type_sortie or "").lower() == "versement_banque"
            and sortie.canal == "CAISSE"
            and sortie.compte_bancaire_id is not None
        ):
            res = await db.execute(
                select(CompteBancaire)
                .where(
                    CompteBancaire.id == sortie.compte_bancaire_id,
                    CompteBancaire.organisation_id == tenant_id,
                )
                .with_for_update()
            )
            compte_dest = res.scalar_one_or_none()
            if compte_dest is not None:
                montant = sortie.montant_paye or 0
                solde_courant = compte_dest.solde_actuel or 0
                if montant > solde_courant:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            "Annulation refusée : le solde bancaire destination est insuffisant "
                            "pour contre-passer ce versement."
                        ),
                    )
                compte_dest.solde_actuel = solde_courant - montant
        # Annulation d'un approvisionnement banque -> caisse : re-débiter la
        # caisse (le compte bancaire source a déjà été re-crédité ci-dessus).
        if (sortie.type_sortie or "").lower() == "approvisionnement_caisse":
            caisse_appro = await _get_or_create_caisse(db, tenant_id)
            res = await db.execute(
                select(CaisseCentrale)
                .where(CaisseCentrale.id == caisse_appro.id, CaisseCentrale.organisation_id == tenant_id)
                .with_for_update()
            )
            caisse_appro = res.scalar_one()
            montant = sortie.montant_paye or 0
            solde_courant = (caisse_appro.solde_usd if sortie.devise == "USD" else caisse_appro.solde_cdf) or 0
            # Symétrique du versement ci-dessus : tronquer à 0 détruisait la
            # différence sans laisser de trace exploitable, et le solde affiché
            # cessait d'être la somme de ses mouvements. Refuser laisse le choix
            # à l'utilisateur d'une opération corrective identifiable.
            if montant > solde_courant:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Annulation refusée : le solde de caisse est insuffisant "
                        f"pour contre-passer {montant} {sortie.devise}. "
                        "Une opération corrective autorisée est nécessaire."
                    ),
                )
            if sortie.devise == "USD":
                caisse_appro.solde_usd = solde_courant - montant
            else:
                caisse_appro.solde_cdf = solde_courant - montant
            caisse_appro.derniere_maj = now

    # --- Annulation d'une sortie liée à un ordre de décaissement :
    # l'ordre redevient AUTORISE (l'autorisation du demandeur reste valable)
    # et le statut de la réquisition est recalculé.
    if previous_statut == "VALIDE" and statut == "ANNULEE":
        ordre_res = await db.execute(
            select(OrdreDecaissement)
            .where(
                OrdreDecaissement.sortie_fonds_id == sortie.id,
                OrdreDecaissement.organisation_id == tenant_id,
                OrdreDecaissement.statut == "PAYE",
            )
            .with_for_update()
        )
        ordre_lie = ordre_res.scalar_one_or_none()
        if ordre_lie is not None:
            ordre_lie.statut = "AUTORISE"
            ordre_lie.paye_par = None
            ordre_lie.paye_le = None
            ordre_lie.sortie_fonds_id = None
            ordre_lie.updated_at = now

            req_od_res = await db.execute(
                select(Requisition)
                .where(
                    Requisition.id == ordre_lie.requisition_id,
                    Requisition.organisation_id == tenant_id,
                )
                .with_for_update()
            )
            req_od = req_od_res.scalar_one_or_none()
            if req_od is not None and bool(getattr(req_od, "decaissement_progressif", False)):
                reste_paye = (
                    await db.execute(
                        select(func.coalesce(func.sum(OrdreDecaissement.montant), 0)).where(
                            OrdreDecaissement.requisition_id == req_od.id,
                            OrdreDecaissement.statut == "PAYE",
                        )
                    )
                ).scalar_one() or 0
                old_req_status = req_od.status
                if Decimal(reste_paye) >= Decimal(req_od.montant_total or 0):
                    new_req_status = "PAYEE"
                elif Decimal(reste_paye) > 0:
                    new_req_status = "EN_DECAISSEMENT"
                else:
                    new_req_status = "APPROUVEE"
                    req_od.payee_par = None
                    req_od.payee_le = None
                if new_req_status != old_req_status:
                    req_od.status = new_req_status
                    req_od.updated_at = now
                    record_status_history(
                        db=db,
                        requisition=req_od,
                        old_status=old_req_status,
                        new_status=new_req_status,
                        user=user,
                        comment=f"Annulation de la sortie liée à l'ordre {ordre_lie.numero_ordre}",
                    )

    # --- Annulation d'une sortie CLASSIQUE (sans ordre) rattachée à une
    # réquisition : recalcul du statut d'après le cumul restant des sorties
    # VALIDES, en excluant la sortie en cours d'annulation (encore VALIDE en
    # base à ce stade). Miroir du bloc progressif ci-dessus, pour que les
    # compléments de paiement se dénouent proprement.
    if (
        previous_statut == "VALIDE"
        and statut == "ANNULEE"
        and sortie.requisition_id is not None
    ):
        req_cls_res = await db.execute(
            select(Requisition)
            .where(
                Requisition.id == sortie.requisition_id,
                Requisition.organisation_id == tenant_id,
            )
            .with_for_update()
        )
        req_cls = req_cls_res.scalar_one_or_none()
        if req_cls is not None and not bool(getattr(req_cls, "decaissement_progressif", False)):
            reste_paye_cls = (
                await db.execute(
                    select(func.coalesce(func.sum(SortieFonds.montant_paye), 0)).where(
                        SortieFonds.requisition_id == req_cls.id,
                        SortieFonds.organisation_id == tenant_id,
                        SortieFonds.statut == "VALIDE",
                        SortieFonds.id != sortie.id,
                    )
                )
            ).scalar_one() or 0
            old_req_status = req_cls.status
            if Decimal(str(reste_paye_cls)) >= Decimal(req_cls.montant_total or 0):
                new_req_status = "PAYEE"
            elif Decimal(str(reste_paye_cls)) > 0:
                new_req_status = "EN_DECAISSEMENT"
            else:
                new_req_status = "APPROUVEE"
                req_cls.payee_par = None
                req_cls.payee_le = None
            if new_req_status != old_req_status:
                req_cls.status = new_req_status
                req_cls.updated_at = now
                record_status_history(
                    db=db,
                    requisition=req_cls,
                    old_status=old_req_status,
                    new_status=new_req_status,
                    user=user,
                    comment=f"Annulation d'un paiement (sortie {sortie.reference_numero})",
                )

    # --- Annulation de l'écriture comptable générée à la création (module
    # Comptabilité, opt-in) : brouillon → ANNULEE, écriture validée →
    # contre-passation datée du jour. Sans effet si l'organisation n'a pas
    # activé le module, ou si la sortie est antérieure à son activation
    # (aucune écriture d'origine : la fonction retourne None).
    # Les deux types d'origine sont tentés car une sortie enregistre soit une
    # dépense, soit un transfert interne (versement / approvisionnement).
    if previous_statut == "VALIDE" and statut == "ANNULEE" and await is_accounting_automatic(db, tenant_id):
        motif_compta = (
            (payload.motif_annulation or "").strip()
            or f"Annulation de la sortie de fonds {sortie.reference_numero}"
        )
        for type_origine in ("sortie_fonds", "transfert_interne"):
            await annuler_ecriture_operation(
                db,
                organisation_id=tenant_id,
                module_origine="sorties_fonds",
                type_origine=type_origine,
                objet_origine_id=str(sortie.id),
                motif=motif_compta,
                user_id=user.id,
                date_annulation=now.date(),
            )

    sortie.statut = statut
    if statut == "ANNULEE":
        sortie.motif_annulation = (payload.motif_annulation or "").strip() or None
        if sortie.annulee_le is None:
            sortie.annulee_le = now
        sortie.annulee_par_id = user.id
        sortie.annulation_ip = get_request_ip(request)
        sortie.ancien_statut = previous_statut
    if (
        previous_statut == "VALIDE"
        and statut == "ANNULEE"
        and (getattr(sortie, "nature_mouvement", "") or "BUDGETAIRE").upper() != "BUDGETAIRE"
    ):
        sortie.hors_budget_status = "ANNULE"
    if previous_statut == "VALIDE" and statut == "ANNULEE" and sortie.fonds_tiers_operation_id is not None:
        fonds_tiers_operation = await get_fonds_tiers_locked(
            db,
            organisation_id=tenant_id,
            operation_id=sortie.fonds_tiers_operation_id,
        )
        await refresh_fonds_tiers_status(db, organisation_id=tenant_id, operation=fonds_tiers_operation)
    await log_action(
        db,
        user_id=user.id,
        action="SORTIE_CANCELLED",
        target_table="sorties_fonds",
        target_id=str(sortie.id),
        old_value={"statut": previous_statut},
        new_value={
            "statut": sortie.statut,
            "motif_annulation": sortie.motif_annulation,
            "annulee_par_id": str(sortie.annulee_par_id) if sortie.annulee_par_id else None,
        },
        ip_address=get_request_ip(request),
    )
    await db.commit()
    await invalidate_report_summary_cache(tenant_id)
    await db.refresh(sortie)
    
    requisition: Requisition | None = None
    validateur: User | None = None
    approbateur: User | None = None
    if sortie.requisition_id:
        req_res = await db.execute(
            select(Requisition).where(
                Requisition.id == sortie.requisition_id,
                Requisition.organisation_id == tenant_id,
            )
        )
        requisition = req_res.scalar_one_or_none()
        if requisition:
            u_ids = []
            if requisition.validee_par: u_ids.append(requisition.validee_par)
            if requisition.approuvee_par: u_ids.append(requisition.approuvee_par)
            if u_ids:
                u_res = await db.execute(select(User).where(User.id.in_(u_ids)))
                u_map = {u.id: u for u in u_res.scalars().all()}
                validateur = u_map.get(requisition.validee_par)
                approbateur = u_map.get(requisition.approuvee_par)

    return _sortie_out(sortie, requisition, validateur=validateur, approbateur=approbateur)
