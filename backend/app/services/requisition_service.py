from __future__ import annotations

import uuid
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status, Request, BackgroundTasks
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.requisition import Requisition
from app.models.requisition_status_history import RequisitionStatusHistory
from app.models.sortie_fonds import SortieFonds
from app.models.user import User
from app.models.service import Service
from app.models.ligne_requisition import LigneRequisition
from app.models.commission_member import CommissionMember
from app.models.compte_bancaire import CompteBancaire
from app.schemas.requisition import RequisitionUpdate, RequisitionCreate, RequisitionExamenPayload
from app.services.reglement import (
    MODE_PAIEMENT_MIXTE,
    calculer_volets,
    est_reglement_multi_volets,
    normaliser_mode,
    resoudre_compte_bancaire,
    resume_mode_paiement,
)
from app.services.service_access import can_view_all_services, get_user_service_ids
from app.services.document_sequences import generate_document_number
from app.services.budget_engagement import (
    resynchroniser_engagement_requisition,
    resynchroniser_engagement_requisitions,
)
from app.services.ligne_requisition_service import (
    build_ligne_requisition,
    can_force_budget_overrun,
)
from app.services.forecasting import compute_cash_forecast
from app.models.system_settings import SystemSettings
from app.models.organisation import Organisation
from app.models.organisation_settings import OrganisationSettings
from app.models.print_settings import PrintSettings
from app.services import workflow_config as wf
from app.services.mailer import send_requisition_workflow_email
from app.services.whatsapp import normalize_whatsapp_numbers, send_whatsapp_message
from app.services.audit_service import log_action, get_request_ip
from app.services.historical_snapshots import (
    FINAL_REQUISITION_STATUSES,
    ensure_requisition_editable,
    ensure_requisition_historical_snapshot,
)
from app.services.fonds_tiers import validate_fonds_tiers_identity

async def _should_snapshot(status_value: str | None) -> bool:
    if not status_value:
        return False
    return status_value.upper() in {"AUTORISEE", "APPROUVEE", "PAYEE", "SIGNEE"}

async def apply_snapshot_if_needed(req: Requisition, db: AsyncSession, tenant_id: int) -> None:
    if req.historical_snapshot_status == "complete":
        return
    if (req.status or "").upper() in {"AUTORISEE", "APPROUVEE", "PAYEE", "SIGNEE", "EN_DECAISSEMENT"}:
        # Snapshot écrit en un seul flush (cf. trigger d'immuabilité).
        with db.sync_session.no_autoflush:
            await ensure_requisition_historical_snapshot(db, req, tenant_id=tenant_id)
        return
    res = await db.execute(
        select(PrintSettings).where(PrintSettings.organisation_id == tenant_id).limit(1)
    )
    settings = res.scalar_one_or_none()
    if not settings:
        return
    req.req_titre_officiel_hist = settings.req_titre_officiel or None
    req.req_label_gauche_hist = settings.req_label_gauche or None
    req.req_nom_gauche_hist = settings.req_nom_gauche or None
    req.req_label_droite_hist = settings.req_label_droite or None
    req.req_nom_droite_hist = settings.req_nom_droite or None
    req.signataire_g_label = settings.req_label_gauche or None
    req.signataire_g_nom = settings.req_nom_gauche or None
    req.signataire_d_label = settings.req_label_droite or None
    req.signataire_d_nom = settings.req_nom_droite or None

    if req.type_requisition == "remboursement_transport":
        from app.models.remboursement_transport import RemboursementTransport
        rt_res = await db.execute(
            select(RemboursementTransport).where(RemboursementTransport.requisition_id == req.id)
        )
        remboursement = rt_res.scalar_one_or_none()
        if remboursement and not (
            remboursement.trans_label_gauche_hist
            or remboursement.trans_label_droite_hist
            or remboursement.trans_titre_officiel_hist
        ):
            remboursement.trans_titre_officiel_hist = settings.trans_titre_officiel or None
            remboursement.trans_label_gauche_hist = settings.trans_label_gauche or None
            remboursement.trans_nom_gauche_hist = settings.trans_nom_gauche or None
            remboursement.trans_label_droite_hist = settings.trans_label_droite or None
            remboursement.trans_nom_droite_hist = settings.trans_nom_droite or None
            remboursement.signataire_g_label = settings.trans_label_gauche or None
            remboursement.signataire_g_nom = settings.trans_nom_gauche or None
            remboursement.signataire_d_label = settings.trans_label_droite or None
            remboursement.signataire_d_nom = settings.trans_nom_droite or None

async def soft_delete_requisition_logic(
    *,
    db: AsyncSession,
    requisition_id: uuid.UUID,
    user: User,
    tenant_id: int,
) -> Requisition:
    res = await db.execute(
        select(Requisition)
        .where(Requisition.id == requisition_id, Requisition.organisation_id == tenant_id)
        .with_for_update()
    )
    req = res.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")

    req.is_deleted = True
    req.updated_at = _utcnow()
    
    await log_action(
        db,
        user_id=user.id,
        action="REQUISITION_DELETED",
        target_table="requisitions",
        target_id=str(req.id),
        ip_address=None,
    )
    
    await db.commit()
    await db.refresh(req)
    return req

async def restore_requisition_logic(
    *,
    db: AsyncSession,
    requisition_id: uuid.UUID,
    user: User,
    tenant_id: int,
) -> Requisition:
    res = await db.execute(
        select(Requisition)
        .where(Requisition.id == requisition_id, Requisition.organisation_id == tenant_id)
        .with_for_update()
    )
    req = res.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")

    req.is_deleted = False
    req.updated_at = _utcnow()
    
    await log_action(
        db,
        user_id=user.id,
        action="REQUISITION_RESTORED",
        target_table="requisitions",
        target_id=str(req.id),
        ip_address=None,
    )
    
    await db.commit()
    await db.refresh(req)
    return req

logger = logging.getLogger("onec_cpk_api.services.requisitions")

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def count_requisition_lines(db: AsyncSession, requisition_id: uuid.UUID) -> int:
    res = await db.execute(
        select(func.count(LigneRequisition.id)).where(LigneRequisition.requisition_id == requisition_id)
    )
    return int(res.scalar_one() or 0)


def _log_submit_examen_rejection(
    req: Requisition,
    *,
    line_count: int,
    reason: str,
) -> None:
    logger.warning(
        "submit-examen rejected requisition_id=%s numero_requisition=%s status=%s examen_status=%s "
        "dossier_id=%s service_id=%s signed_by_id=%s signed_at=%s nombre_lignes=%s reason=%s",
        req.id,
        req.numero_requisition,
        req.status,
        req.examen_status,
        req.dossier_id,
        req.service_id,
        req.signed_by_id,
        req.signed_at,
        line_count,
        reason,
    )

def _status_from_payload(payload: RequisitionCreate | RequisitionUpdate) -> str | None:
    if payload.status:
        return payload.status
    if payload.statut:
        return payload.statut
    return None


def _coerce_uuid(value: uuid.UUID | str, field_name: str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid {field_name}")

def record_status_history(
    *,
    db: AsyncSession,
    requisition: Requisition,
    old_status: str | None,
    new_status: str | None,
    user: User | None,
    comment: str | None = None,
) -> None:
    if not new_status or old_status == new_status:
        return
    db.add(
        RequisitionStatusHistory(
            organisation_id=requisition.organisation_id,
            requisition_id=requisition.id,
            old_status=old_status,
            new_status=new_status,
            comment=comment,
            changed_by=user.id if user else None,
            changed_at=_utcnow(),
        )
    )

async def check_cash_watchdog(
    *,
    db: AsyncSession,
    user: User | None,
    request: Request | None,
    requisition_id: str,
) -> None:
    try:
        forecast = await compute_cash_forecast(
            db=db,
            lookback_days=30,
            horizon_days=30,
            reserve_threshold=1000.0,
            tenant_id=getattr(user, "organisation_id", None),
        )
        if forecast.stress_projection <= forecast.reserve_threshold:
            await log_action(
                db,
                user_id=user.id if user else None,
                action="CASH_STRESS_ALERT",
                target_table="requisitions",
                target_id=requisition_id,
                new_value={
                    "stress_projection": forecast.stress_projection,
                    "reserve_threshold": forecast.reserve_threshold,
                    "pending_total": forecast.pending_total,
                },
                ip_address=get_request_ip(request) if request else None,
            )
            await db.commit()
    except Exception:
        logger.exception("Cash watchdog check failed")

def requisition_nature(req: Requisition) -> str:
    # Repli sur BUDGETAIRE : les réquisitions antérieures à l'introduction du
    # champ n'ont pas d'autre nature possible.
    return (getattr(req, "nature_requisition", None) or "BUDGETAIRE").upper()


def requisition_exige_des_lignes(req: Requisition) -> bool:
    # Une réquisition budgétaire est portée par ses lignes : ce sont elles qui
    # désignent les postes et fondent le montant. Hors budget et fonds de tiers
    # n'imputent rien à la création — leur montant est autorisé en bloc, et
    # exiger des lignes rendrait leur circuit de validation infranchissable.
    return requisition_nature(req) == "BUDGETAIRE"


async def require_requisition_lines(db: AsyncSession, req: Requisition) -> None:
    if not requisition_exige_des_lignes(req):
        # Le montant autorisé remplace la somme des lignes comme garde-fou :
        # sans lui la réquisition n'autorise rien, et la sortie de fonds n'a
        # aucun plafond à opposer à la caisse.
        if Decimal(req.montant_total or 0) <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Montant autorisé requis pour une réquisition sans ligne budgétaire",
            )
        return
    line_count = await count_requisition_lines(db, req.id)
    if line_count <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Aucune ligne de réquisition")

async def resolve_service(service_id: int, db: AsyncSession) -> Service:
    res = await db.execute(select(Service).where(Service.id == service_id, Service.is_active.is_(True)))
    s = res.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service non trouvé")
    return s


async def resolve_requisition_compte_bancaire(
    compte_bancaire_id: int | None,
    *,
    mode_paiement: str,
    tenant_id: int,
    db: AsyncSession,
) -> int | None:
    # La règle vit dans `services.reglement`, partagée avec les lignes et les
    # ordres de décaissement : un règlement bancaire, où qu'il soit défini,
    # désigne toujours un compte actif du tenant, de type BANK.
    if (mode_paiement or "").lower() == MODE_PAIEMENT_MIXTE:
        # Réquisition à règlement mixte : le compte n'est pas porté au niveau de
        # la pièce mais par chacune de ses lignes.
        return None
    return await resoudre_compte_bancaire(
        compte_bancaire_id,
        mode_paiement=mode_paiement,
        tenant_id=tenant_id,
        db=db,
    )

async def _propager_mode_aux_lignes(
    db: AsyncSession,
    req: Requisition,
    *,
    mode_precedent: str | None,
    mode_cible: str,
    compte_cible: int | None,
) -> None:
    """Aligne sur `mode_cible` les lignes qui suivaient encore `mode_precedent`.

    Une ligne à laquelle on a donné un mode propre — différent de celui de la
    pièce — représente un choix explicite du demandeur : elle est laissée
    intacte. Seules les lignes qui n'avaient jamais divergé suivent.
    """
    ancien = normaliser_mode(mode_precedent)
    res = await db.execute(
        select(LigneRequisition).where(LigneRequisition.requisition_id == req.id)
    )
    for ligne in res.scalars().all():
        if ancien and normaliser_mode(ligne.mode_paiement) != ancien:
            continue
        ligne.mode_paiement = mode_cible
        ligne.compte_bancaire_id = compte_cible


async def appliquer_reglement_requisition(
    db: AsyncSession,
    req: Requisition,
) -> list:
    """Recale la réquisition sur le règlement réellement porté par ses lignes.

    `mode_paiement` et `compte_bancaire_id` de la réquisition ne sont pas des
    saisies mais un résumé : ils sont recalculés à chaque fois que les lignes
    bougent. Cela garantit qu'aucune pièce n'affiche un mode que ses lignes
    contredisent.

    Invariant métier posé ici : dès que le règlement se scinde en plusieurs
    volets, la réquisition passe obligatoirement en décaissement progressif. La
    caisse ne peut pas solder en un seul paiement ce qui sort de deux endroits
    différents ; chaque volet devra être autorisé puis payé séparément.

    Renvoie les volets calculés, pour éviter à l'appelant de les recalculer.
    """
    res = await db.execute(
        select(LigneRequisition)
        .where(LigneRequisition.requisition_id == req.id)
        .order_by(LigneRequisition.id.asc())
    )
    lignes = res.scalars().all()
    if not lignes:
        return []

    volets = calculer_volets(lignes, mode_defaut=req.mode_paiement or "cash")
    req.mode_paiement = resume_mode_paiement(volets, defaut=req.mode_paiement or "cash")
    req.compte_bancaire_id = volets[0].compte_bancaire_id if len(volets) == 1 else None
    if est_reglement_multi_volets(volets):
        req.decaissement_progressif = True
    return volets


async def _pivot_amount(
    db: AsyncSession,
    tenant_id: int,
    montant: float,
    from_currency: str = "USD",
) -> float:
    """Convertit `montant` depuis SA devise (`from_currency`, explicite sur la
    réquisition) vers la DEVISE PIVOT du tenant (default_currency des réglages
    d'impression) — la devise de référence dans laquelle le seuil de la 2e
    validation est saisi.

    Les taux sont exprimés en « unités de devise pour 1 USD » (comme le frontend
    où toUsd divise par le taux). Conversion via l'USD comme base. Si un taux
    nécessaire est manquant (0), on renvoie le montant tel quel (best-effort).
    """
    res = await db.execute(
        select(PrintSettings).where(PrintSettings.organisation_id == tenant_id).limit(1)
    )
    ps = res.scalar_one_or_none()
    pivot = ((ps.default_currency if ps else None) or "USD").upper()
    src = (from_currency or "USD").upper()
    if src == pivot:
        return montant

    rates: dict[str, float] = {"USD": 1.0}
    if ps is not None:
        rates["CDF"] = float(ps.exchange_rate_cdf or 0)
        rates["EUR"] = float(ps.exchange_rate_eur or 0)
        rates["XOF"] = float(ps.exchange_rate_xof or 0)

    src_rate = rates.get(src, 0.0)
    pivot_rate = rates.get(pivot, 0.0)
    if src_rate <= 0 or pivot_rate <= 0:
        return montant  # taux manquant : best-effort (cf. garde-fou taux=0)

    usd = montant if src == "USD" else montant / src_rate
    return usd if pivot == "USD" else usd * pivot_rate


async def _can_use_any_service(db: AsyncSession, user: User) -> bool:
    """Un service quelconque peut-il être porté sur la réquisition ?

    Même règle que le reste de l'application (dossiers, lignes, listes) : les
    administrateurs et les profils à visibilité globale (SG, comptabilité…) ne
    sont pas limités à leurs services d'affectation. Le formulaire leur propose
    déjà tous les services : restreindre ici produirait un 403 sur un choix que
    l'interface présente comme valide.
    """
    if (user.role or "").lower() in {"admin", "super_admin"}:
        return True
    return await can_view_all_services(db, user)


async def _load_workflow_config(db: AsyncSession, tenant_id: int) -> dict:
    """Charge le circuit de validation configuré pour l'organisation (ou le
    circuit complet par défaut)."""
    res = await db.execute(
        select(OrganisationSettings.workflow_config).where(
            OrganisationSettings.organisation_id == tenant_id
        ).limit(1)
    )
    raw = res.scalar_one_or_none()
    return wf.normalize_config(raw)


def _stamp_skipped_steps(req: Requisition, snapshot: dict, *, user_id, amount: float) -> None:
    """Estampille comme complétées les étapes désactivées, pour que les
    contrôles en aval (signature requise, examen requis) restent cohérents."""
    if not wf.step_enabled(snapshot, "signature_service", amount):
        if not req.signed_by_id:
            req.signed_by_id = user_id
        if not req.signed_at:
            req.signed_at = _utcnow()
    if not wf.step_enabled(snapshot, "examen", amount):
        req.examen_status = "EXAMINE"


async def create_requisition_logic(
    *,
    db: AsyncSession,
    payload: RequisitionCreate,
    user: User,
    tenant_id: int,
    request: Request | None = None,
) -> Requisition:
    created_by = None
    if payload.created_by:
        if isinstance(payload.created_by, uuid.UUID):
            created_by = payload.created_by
        else:
            try:
                created_by = uuid.UUID(payload.created_by)
            except ValueError:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid created_by")

    numero_requisition = payload.numero_requisition or await generate_document_number(
        db, "REQ", tenant_id, service_id=payload.service_id
    )
    service_id = None
    if not await _can_use_any_service(db, user):
        service_ids = await get_user_service_ids(db, user)
        if not service_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Utilisateur sans service assigné.")
        if payload.service_id is None:
            if len(service_ids) == 1:
                service_id = service_ids[0]
            else:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="service_id requis")
        else:
            if payload.service_id not in service_ids:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Service non autorisé pour cet utilisateur")
            service_id = payload.service_id
    else:
        if payload.service_id is not None:
            service_id = payload.service_id
    
    if service_id is not None:
        await resolve_service(service_id, db)
    if service_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="service_id requis")
    compte_bancaire_id = await resolve_requisition_compte_bancaire(
        payload.compte_bancaire_id,
        mode_paiement=payload.mode_paiement,
        tenant_id=tenant_id,
        db=db,
    )
    tiers_organisation_id = payload.tiers_organisation_id
    tiers_nom_libre = payload.tiers_nom_libre
    if payload.nature_requisition == "FONDS_DE_TIERS":
        tiers_organisation_id, tiers_nom_libre = await validate_fonds_tiers_identity(
            db,
            organisation_id=tenant_id,
            tiers_organisation_id=payload.tiers_organisation_id,
            tiers_nom_libre=payload.tiers_nom_libre,
        )

    # Circuit de validation en vigueur : on fige une photo sur la réquisition et
    # on la place directement à la première étape active (les étapes désactivées
    # sont sautées).
    snapshot = await _load_workflow_config(db, tenant_id)
    req_devise = (getattr(payload, "devise", None) or "USD").upper()
    # Montant converti depuis la devise de la réquisition vers la devise pivot
    # (référence) pour comparer au seuil éventuel.
    amount = await _pivot_amount(db, tenant_id, float(payload.montant_total or 0), req_devise)
    status_value = wf.first_active_waiting(snapshot, amount)

    req = Requisition(
        numero_requisition=numero_requisition,
        organisation_id=tenant_id,
        objet=payload.objet,
        mode_paiement=payload.mode_paiement,
        type_requisition=payload.type_requisition,
        nature_requisition=payload.nature_requisition,
        montant_total=payload.montant_total,
        # Date métier : celle saisie, sinon l'instant courant. created_at reste
        # l'horodatage technique et n'est jamais écrasé.
        date_requisition=getattr(payload, "date_requisition", None) or datetime.now(timezone.utc),
        devise=req_devise,
        service_id=service_id,
        compte_bancaire_id=compte_bancaire_id,
        status=status_value,
        examen_status="NON_EXAMINE",
        workflow_snapshot=snapshot,
        created_by=created_by,
        a_valoir=bool(payload.a_valoir),
        decaissement_progressif=bool(payload.decaissement_progressif),
        beneficiaire=payload.beneficiaire,
        instance_beneficiaire=payload.instance_beneficiaire,
        tiers_organisation_id=tiers_organisation_id,
        tiers_nom_libre=tiers_nom_libre,
        notes_a_valoir=payload.notes_a_valoir,
        reference_numero=numero_requisition,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    _stamp_skipped_steps(req, snapshot, user_id=created_by or user.id, amount=amount)
    db.add(req)

    # Les lignes sont écrites dans la même transaction que la réquisition : si
    # l'une d'elles est refusée (rubrique non autorisée, dépassement…), rien
    # n'est enregistré — pas de réquisition orpheline sans ligne, et le numéro
    # de séquence n'est pas consommé.
    if payload.lignes:
        await db.flush()
        force_overrun = await can_force_budget_overrun(db, user)
        # La réquisition naît en brouillon : elle n'engage encore rien (cf.
        # budget_engagement). Le cumul local sert uniquement au contrôle de
        # disponibilité entre les lignes du même envoi.
        engagements_en_cours: dict[int, Decimal] = {}
        for item in payload.lignes:
            db.add(
                await build_ligne_requisition(
                    db=db,
                    requisition=req,
                    item=item,
                    tenant_id=tenant_id,
                    force_overrun=force_overrun,
                    engagements_en_cours=engagements_en_cours,
                )
            )
        # Les lignes viennent d'être écrites : le mode porté par la réquisition
        # n'est plus qu'un résumé, on le recale (et on bascule en décaissement
        # progressif si le règlement se scinde).
        await db.flush()
        await appliquer_reglement_requisition(db, req)
        # Circuit sans étape d'examen : la réquisition naît déjà EXAMINE
        # (_stamp_skipped_steps) et engage donc son budget immédiatement.
        await resynchroniser_engagement_requisition(db, req)

    await db.commit()
    await db.refresh(req)

    if request:
        await check_cash_watchdog(db=db, user=user, request=request, requisition_id=str(req.id))

    return req

async def validate_requisition_logic(
    *,
    db: AsyncSession,
    requisition_id: uuid.UUID,
    user: User,
    tenant_id: int,
    request: Request | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> Requisition:
    res = await db.execute(
        select(Requisition).where(Requisition.id == requisition_id, Requisition.organisation_id == tenant_id)
    )
    req = res.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")

    status_value = (req.status or "").upper()
    if status_value in {"AUTORISEE", "APPROUVEE", "PAYEE"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Requisition déjà finalisée")
    if status_value not in {"EN_ATTENTE", "EN_ATTENTE_COMMISSION"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Réquisition non en attente")
    
    if req.service_id is not None:
        signer_res = await db.execute(
            select(CommissionMember.id).where(
                CommissionMember.service_id == req.service_id,
                CommissionMember.is_signer.is_(True),
            ).limit(1)
        )
        has_signers = signer_res.scalar_one_or_none() is not None
        if has_signers and status_value != "EN_ATTENTE":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Validation technique bloquée : la commission doit signer avant validation.",
            )
            
    if req.status in {"AUTORISEE"} and req.validee_par:
        if req.validee_par != user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Réquisition déjà autorisée par un autre utilisateur")
    
    old_status = req.status
    # Montant en devise pivot (référence) pour l'évaluation du seuil de la 2e validation.
    amount = await _pivot_amount(db, tenant_id, float(req.montant_total or 0), getattr(req, "devise", None) or "USD")
    req.validee_par = req.validee_par or user.id
    req.validee_le = req.validee_le or _utcnow()
    # Si la 2e validation (visa) est inactive pour ce dossier, la 1re validation
    # finalise directement (APPROUVEE). Sinon on passe en AUTORISEE (attente visa).
    req.status = wf.first_active_waiting(req.workflow_snapshot, amount, after_step="validation_1")
    if req.status == "APPROUVEE":
        req.approuvee_par = req.approuvee_par or user.id
        req.approuvee_le = req.approuvee_le or _utcnow()
        # Statut + snapshot dans un seul UPDATE (cf. trigger d'immuabilité).
        with db.sync_session.no_autoflush:
            await ensure_requisition_historical_snapshot(db, req, tenant_id=tenant_id)
    record_status_history(
        db=db,
        requisition=req,
        old_status=old_status,
        new_status=req.status,
        user=user,
    )
    req.updated_at = _utcnow()

    await log_action(
        db,
        user_id=user.id,
        action="REQUISITION_TECH_VALIDATED",
        target_table="requisitions",
        target_id=str(req.id),
        old_value={"status": old_status},
        new_value={"status": req.status},
        ip_address=get_request_ip(request) if request else None,
    )
    
    await db.commit()
    await db.refresh(req)
    
    if request:
        await check_cash_watchdog(db=db, user=user, request=request, requisition_id=str(req.id))
    
    # Notifications logic moved here or triggered from endpoint?
    # Keeping it simple for now and letting endpoint handle notifications if it uses background_tasks
    return req


async def update_requisition_logic(
    *,
    db: AsyncSession,
    requisition_id: uuid.UUID,
    payload: RequisitionUpdate,
    user: User,
    tenant_id: int,
    request: Request | None = None,
) -> Requisition:
    res = await db.execute(
        select(Requisition)
        .where(Requisition.id == requisition_id, Requisition.organisation_id == tenant_id)
        .with_for_update()
    )
    req = res.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")

    logger.info("Update requisition start id=%s", requisition_id)
    logger.info("Payload=%s", payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload)
    logger.info("Before justificatif processing")
    payload_values = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else {}
    sensitive_fields = {
        "objet",
        "mode_paiement",
        "type_requisition",
        "nature_requisition",
        "montant_total",
        "service_id",
        "compte_bancaire_id",
        "status",
        "statut",
        "created_by",
        "validee_par",
        "validee_le",
        "approuvee_par",
        "approuvee_le",
        "signed_by_id",
        "signed_at",
        "payee_par",
        "payee_le",
        "a_valoir",
        "decaissement_progressif",
        "beneficiaire",
        "instance_beneficiaire",
        "tiers_organisation_id",
        "tiers_nom_libre",
        "notes_a_valoir",
    }
    attempted_sensitive_fields = {field for field in payload_values if field in sensitive_fields}
    if attempted_sensitive_fields:
        ensure_requisition_editable(req, attempted_fields=attempted_sensitive_fields)
    await require_requisition_lines(db, req)
    # L'examen conditionne le PASSAGE en validation, pas la correction d'une
    # pièce qui l'attend encore. Une réquisition non examinée reste modifiable
    # tant qu'elle n'est pas validée : c'est justement pendant cette phase
    # qu'on la corrige, et l'exiger plus tôt enfermait le rédacteur dans une
    # pièce qu'il ne pouvait ni faire avancer ni amender.
    # L'examen n'est par ailleurs exigé que s'il fait partie du circuit figé
    # sur la réquisition : sinon toute mise à jour échouerait sur une étape
    # désactivée.
    target_status = (_status_from_payload(payload) or "").upper()
    if target_status in FINAL_REQUISITION_STATUSES:
        if wf.step_enabled(req.workflow_snapshot, "examen", float(req.montant_total or 0)):
            if (req.examen_status or "").upper() != "EXAMINE":
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Examen requis avant validation")

    logger.info("Before payment processing")
    # Update fields
    if payload.objet is not None:
        req.objet = payload.objet
    mode_paiement_initial = req.mode_paiement
    if payload.mode_paiement is not None:
        req.mode_paiement = payload.mode_paiement
    if payload.type_requisition is not None:
        req.type_requisition = payload.type_requisition
    target_nature = payload.nature_requisition or req.nature_requisition or "BUDGETAIRE"
    # Les deux identités du tiers sont exclusives : en désigner une efface
    # l'autre. Sans cela, basculer un tiers du référentiel vers un tiers libre
    # est impossible — l'ancien identifiant survit au payload, les deux
    # cohabitent, et la règle d'exclusivité rejette la mise à jour.
    # `payload_values` (exclude_unset) distingue « champ absent » de « champ
    # remis à null », que le test `is not None` confondait.
    tiers_org_fourni = "tiers_organisation_id" in payload_values
    tiers_nom_fourni = "tiers_nom_libre" in payload_values
    if tiers_org_fourni and payload.tiers_organisation_id is not None:
        target_tiers_organisation_id = payload.tiers_organisation_id
        target_tiers_nom_libre = None
    elif tiers_nom_fourni and payload.tiers_nom_libre is not None:
        target_tiers_organisation_id = None
        target_tiers_nom_libre = payload.tiers_nom_libre
    else:
        target_tiers_organisation_id = (
            payload.tiers_organisation_id if tiers_org_fourni else req.tiers_organisation_id
        )
        target_tiers_nom_libre = (
            payload.tiers_nom_libre if tiers_nom_fourni else req.tiers_nom_libre
        )
    if target_nature == "FONDS_DE_TIERS":
        target_tiers_organisation_id, target_tiers_nom_libre = await validate_fonds_tiers_identity(
            db,
            organisation_id=tenant_id,
            tiers_organisation_id=target_tiers_organisation_id,
            tiers_nom_libre=target_tiers_nom_libre,
        )
    else:
        target_tiers_organisation_id = None
        target_tiers_nom_libre = None

    req.nature_requisition = target_nature
    req.tiers_organisation_id = target_tiers_organisation_id
    req.tiers_nom_libre = target_tiers_nom_libre
    if payload.montant_total is not None:
        req.montant_total = payload.montant_total
    
    if payload.service_id is not None:
        if not await _can_use_any_service(db, user):
            service_ids = await get_user_service_ids(db, user)
            if payload.service_id not in service_ids:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Service non autorisé pour cet utilisateur")
        await resolve_service(payload.service_id, db)
        req.service_id = payload.service_id
    if payload.beneficiaire is not None:
        req.beneficiaire = payload.beneficiaire
    if payload.mode_paiement is not None or payload.compte_bancaire_id is not None:
        req.compte_bancaire_id = await resolve_requisition_compte_bancaire(
            payload.compte_bancaire_id if payload.compte_bancaire_id is not None else req.compte_bancaire_id,
            mode_paiement=payload.mode_paiement or req.mode_paiement,
            tenant_id=tenant_id,
            db=db,
        )
        # Changer le mode au niveau de la pièce le répercute sur les lignes qui
        # suivaient l'ancien : sans cela, la réquisition afficherait un mode que
        # ses propres lignes contrediraient. Les lignes ayant reçu un mode
        # explicite différent ne sont pas touchées.
        if payload.mode_paiement is not None and payload.mode_paiement != MODE_PAIEMENT_MIXTE:
            await _propager_mode_aux_lignes(
                db,
                req,
                mode_precedent=mode_paiement_initial,
                mode_cible=payload.mode_paiement,
                compte_cible=req.compte_bancaire_id,
            )

    old_status = req.status
    status_value = _status_from_payload(payload)
    if status_value is not None:
        logger.info("Before status update")
        normalized_status = status_value.upper()
        if req.type_requisition == "remboursement_transport":
            current_status = (req.status or "").upper()
            validateur_id = str(payload.validee_par or req.validee_par or "") or None
            approbateur_id = str(payload.approuvee_par or req.approuvee_par or "") or None
            if normalized_status in {"APPROUVEE", "PAYEE"} and current_status not in {"AUTORISEE", "APPROUVEE", "PAYEE"}:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Remboursement transport doit être autorisé avant le visa ou le paiement",
                )
            if normalized_status == "AUTORISEE" and not validateur_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Autorisation (1/2) requise avant le visa du remboursement transport",
                )
            if validateur_id and approbateur_id and validateur_id == approbateur_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Une autre personne doit viser le remboursement transport",
                )
        req.status = status_value

    for attr in ("validee_par", "approuvee_par", "signed_by_id", "payee_par", "created_by"):
        value = getattr(payload, attr)
        if value is not None:
            setattr(req, attr, _coerce_uuid(value, attr))

    for attr in ("validee_le", "approuvee_le", "signed_at", "payee_le"):
        value = getattr(payload, attr)
        if value is not None:
            setattr(req, attr, value)

    if payload.motif_rejet is not None:
        req.motif_rejet = payload.motif_rejet
    if payload.a_valoir is not None:
        req.a_valoir = payload.a_valoir
    if payload.decaissement_progressif is not None:
        current_status_dp = (req.status or "").upper()
        if bool(payload.decaissement_progressif) != bool(req.decaissement_progressif) and current_status_dp in {
            "APPROUVEE",
            "EN_DECAISSEMENT",
            "PAYEE",
        }:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Option décaissement progressif verrouillée après approbation",
            )
        req.decaissement_progressif = bool(payload.decaissement_progressif)
    if payload.instance_beneficiaire is not None:
        req.instance_beneficiaire = payload.instance_beneficiaire
    if payload.notes_a_valoir is not None:
        req.notes_a_valoir = payload.notes_a_valoir

    if status_value is not None:
        record_status_history(
            db=db,
            requisition=req,
            old_status=old_status,
            new_status=req.status,
            user=user,
            comment=payload.motif_rejet if payload.motif_rejet is not None else None,
        )

    # Dernier mot aux lignes : quoi qu'ait envoyé l'appelant, le mode porté par
    # la pièce est le résumé de son règlement réel.
    await db.flush()
    await appliquer_reglement_requisition(db, req)

    req.updated_at = payload.updated_at or _utcnow()
    req.row_version = (req.row_version or 0) + 1

    await db.commit()
    await db.refresh(req)

    if request:
        await check_cash_watchdog(db=db, user=user, request=request, requisition_id=str(req.id))

    return req


async def sign_commission_requisition_logic(
    *,
    db: AsyncSession,
    requisition_id: uuid.UUID,
    user: User,
    tenant_id: int,
) -> Requisition:
    res = await db.execute(
        select(Requisition)
        .where(Requisition.id == requisition_id, Requisition.organisation_id == tenant_id)
        .with_for_update()
    )
    req = res.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")

    # Allow admin to sign regardless of membership
    is_admin = (user.role or "").lower() == "admin"
    
    if not is_admin:
        # Check if user is a signer for this service
        signer_res = await db.execute(
            select(CommissionMember.id).where(
                CommissionMember.service_id == req.service_id,
                CommissionMember.user_id == user.id,
                CommissionMember.is_signer.is_(True),
            )
        )
        if signer_res.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Seuls les signataires de cette commission peuvent approuver cette dépense.",
            )

    status_value = (req.status or "").upper()
    if status_value != "BROUILLON":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La réquisition doit être en mode brouillon pour être signée par le service.")
    
    await require_requisition_lines(db, req)

    old_status = req.status
    amount = float(req.montant_total or 0)
    req.signed_by_id = user.id
    req.signed_at = _utcnow()
    # Avancer directement à la prochaine étape active (l'examen est sauté s'il
    # est désactivé dans le circuit de la réquisition).
    req.status = wf.first_active_waiting(req.workflow_snapshot, amount, after_step="signature_service")
    examen_saute = not wf.step_enabled(req.workflow_snapshot, "examen", amount)
    if examen_saute:
        req.examen_status = "EXAMINE"
    req.updated_at = _utcnow()
    if examen_saute:
        # L'examen étant sauté, la signature du service vaut fait générateur de
        # l'engagement.
        await resynchroniser_engagement_requisition(db, req)

    record_status_history(
        db=db,
        requisition=req,
        old_status=old_status,
        new_status=req.status,
        user=user,
    )

    await db.commit()
    await db.refresh(req)
    return req

async def vise_requisition_logic(
    *,
    db: AsyncSession,
    requisition_id: uuid.UUID,
    user: User,
    tenant_id: int,
    request: Request | None = None,
) -> Requisition:
    res = await db.execute(
        select(Requisition)
        .where(Requisition.id == requisition_id, Requisition.organisation_id == tenant_id)
        .with_for_update()
    )
    req = res.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")

    if req.status not in {"AUTORISEE"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Réquisition non autorisée")
    if req.validee_par and req.validee_par == user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Une autre personne doit viser cette réquisition",
        )

    old_status = req.status
    req.status = "APPROUVEE"
    record_status_history(
        db=db,
        requisition=req,
        old_status=old_status,
        new_status=req.status,
        user=user,
    )
    req.approuvee_par = user.id
    req.approuvee_le = _utcnow()
    req.updated_at = _utcnow()
    # Le changement de statut (-> APPROUVEE) et l'écriture du snapshot historique
    # doivent partir dans le MÊME UPDATE. Sans cela, l'autoflush interne de
    # ensure_requisition_historical_snapshot persiste d'abord APPROUVEE, puis tente
    # d'écrire le snapshot alors que OLD.status est déjà finalisé — ce que le trigger
    # trg_requisitions_immutable_after_final rejette.
    with db.sync_session.no_autoflush:
        await ensure_requisition_historical_snapshot(db, req, tenant_id=tenant_id)

    await log_action(
        db,
        user_id=user.id,
        action="REQUISITION_FINAL_APPROVED",
        target_table="requisitions",
        target_id=str(req.id),
        old_value={"status": old_status},
        new_value={"status": req.status},
        ip_address=get_request_ip(request) if request else None,
    )
    
    await db.commit()
    await db.refresh(req)
    
    if request:
        await check_cash_watchdog(db=db, user=user, request=request, requisition_id=str(req.id))
    
    return req

async def reject_requisition_logic(
    *,
    db: AsyncSession,
    requisition_id: uuid.UUID,
    user: User,
    tenant_id: int,
    request: Request | None = None,
) -> Requisition:
    res = await db.execute(
        select(Requisition).where(Requisition.id == requisition_id, Requisition.organisation_id == tenant_id)
    )
    req = res.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")

    old_status = req.status
    req.status = "REJETEE"
    record_status_history(
        db=db,
        requisition=req,
        old_status=old_status,
        new_status=req.status,
        user=user,
    )
    req.updated_at = _utcnow()
    
    await log_action(
        db,
        user_id=user.id,
        action="REQUISITION_REJECTED",
        target_table="requisitions",
        target_id=str(req.id),
        old_value={"status": old_status},
        new_value={"status": req.status},
        ip_address=get_request_ip(request) if request else None,
    )
    
    await db.commit()
    await db.refresh(req)
    return req


async def reject_requisition_at_payment_logic(
    *,
    db: AsyncSession,
    requisition_id: uuid.UUID,
    user: User,
    tenant_id: int,
    motif_rejet: str,
    request: Request | None = None,
) -> Requisition:
    res = await db.execute(
        select(Requisition).where(
            Requisition.id == requisition_id,
            Requisition.organisation_id == tenant_id,
            Requisition.is_deleted.is_(False),
        )
    )
    req = res.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")

    motif = (motif_rejet or "").strip()
    if not motif:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Motif de rejet requis")

    status_value = (req.status or "").upper()
    if status_value != "APPROUVEE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seules les réquisitions approuvées en attente de paiement peuvent être rejetées à la sortie de fonds",
        )
    if req.payee_par or req.payee_le:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cette réquisition est déjà marquée comme payée",
        )
    # Décaissement progressif : on distingue l'annulation d'un OD (tranche) du rejet
    # de la réquisition entière. Le rejet global n'est pas autorisé en caisse ; le
    # demandeur annule tranche par tranche via le Plan de décaissement.
    if bool(getattr(req, "decaissement_progressif", False)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Réquisition à décaissement progressif : le rejet global n'est pas "
                "autorisé à la sortie de fonds. L'annulation se fait tranche par tranche "
                "(ordre de décaissement) par le demandeur."
            ),
        )

    # Seule une sortie réellement engagée (VALIDE) bloque le rejet. Un brouillon
    # n'est qu'une saisie préparatoire sans mouvement de caisse : il ne doit pas
    # verrouiller le dossier, mais il est annulé avec la réquisition pour qu'aucun
    # projet de paiement ne subsiste sur un dossier rejeté.
    linked_sorties = list(
        (
            await db.execute(
                select(SortieFonds).where(
                    SortieFonds.organisation_id == tenant_id,
                    SortieFonds.requisition_id == req.id,
                    (SortieFonds.statut.is_(None)) | (func.upper(SortieFonds.statut) != "ANNULEE"),
                )
            )
        )
        .scalars()
        .all()
    )
    draft_sorties = [s for s in linked_sorties if (s.statut or "").strip().upper() == "BROUILLON"]
    if len(linked_sorties) > len(draft_sorties):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Une sortie de fonds existe déjà pour cette réquisition",
        )

    old_status = req.status
    now = _utcnow()
    req.status = "REJETEE"
    req.motif_rejet = motif
    req.payee_par = None
    req.payee_le = None
    req.updated_at = now

    for draft in draft_sorties:
        draft.ancien_statut = draft.statut
        draft.statut = "ANNULEE"
        draft.motif_annulation = f"Réquisition rejetée à la sortie de fonds : {motif}"
        draft.annulee_le = now
        draft.annulee_par_id = user.id

    record_status_history(
        db=db,
        requisition=req,
        old_status=old_status,
        new_status=req.status,
        user=user,
        comment=motif,
    )

    await log_action(
        db,
        user_id=user.id,
        action="REQUISITION_REJECTED_AT_PAYMENT",
        target_table="requisitions",
        target_id=str(req.id),
        old_value={"status": old_status},
        new_value={
            "status": req.status,
            "motif_rejet": req.motif_rejet,
            "brouillons_annules": [str(d.id) for d in draft_sorties],
        },
        ip_address=get_request_ip(request) if request else None,
    )

    await db.commit()
    await db.refresh(req)
    return req


async def submit_requisition_examen_logic(
    *,
    db: AsyncSession,
    requisition_id: uuid.UUID,
    tenant_id: int,
) -> Requisition:
    res = await db.execute(
        select(Requisition).where(
            Requisition.id == requisition_id,
            Requisition.organisation_id == tenant_id,
            Requisition.is_deleted.is_(False),
        )
    )
    req = res.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")
    line_count = await count_requisition_lines(db, req.id)
    if req.dossier_id:
        _log_submit_examen_rejection(
            req,
            line_count=line_count,
            reason="requisition_already_attached_to_dossier",
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Réquisition déjà rattachée à un dossier")
    examen_status = (req.examen_status or "").upper()
    if examen_status not in {"NON_EXAMINE", "REJETE"}:
        _log_submit_examen_rejection(
            req,
            line_count=line_count,
            reason="invalid_examen_status_for_submission",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La réquisition n'est pas dans un état permettant une soumission à l'examen.",
        )
    status_value = (req.status or "").upper()
    if status_value != "SIGNEE_SERVICE":
        _log_submit_examen_rejection(
            req,
            line_count=line_count,
            reason="invalid_status_for_submission",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La réquisition doit être au statut SIGNEE_SERVICE avant d'être soumise à l'examen.",
        )
    if not req.signed_by_id:
        _log_submit_examen_rejection(
            req,
            line_count=line_count,
            reason="missing_signed_by_id",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La réquisition doit être signée par le service/commission compétent avant d'être soumise à l'examen."
        )
    if not req.signed_at:
        _log_submit_examen_rejection(
            req,
            line_count=line_count,
            reason="missing_signed_at",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La date de signature du service est requise avant la soumission à l'examen.",
        )
    if requisition_exige_des_lignes(req):
        if line_count <= 0:
            _log_submit_examen_rejection(
                req,
                line_count=line_count,
                reason="missing_requisition_lines",
            )
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Aucune ligne de réquisition")
    elif Decimal(req.montant_total or 0) <= 0:
        _log_submit_examen_rejection(
            req,
            line_count=line_count,
            reason="missing_montant_autorise",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Montant autorisé requis pour une réquisition sans ligne budgétaire",
        )

    req.status = "EN_ATTENTE"
    req.examen_status = "EN_EXAMEN"
    req.examen_commentaire = None
    req.examen_par = None
    req.examen_le = None
    req.updated_at = _utcnow()
    # Fait générateur : c'est ici que le budget est gelé.
    await resynchroniser_engagement_requisition(db, req)
    logger.info(
        "submit-examen accepted requisition_id=%s numero_requisition=%s status=%s examen_status=%s "
        "dossier_id=%s service_id=%s signed_by_id=%s signed_at=%s nombre_lignes=%s",
        req.id,
        req.numero_requisition,
        req.status,
        req.examen_status,
        req.dossier_id,
        req.service_id,
        req.signed_by_id,
        req.signed_at,
        line_count,
    )
    await db.commit()
    await db.refresh(req)
    return req


async def validate_requisition_examen_logic(
    *,
    db: AsyncSession,
    requisition_id: uuid.UUID,
    payload: RequisitionExamenPayload,
    user: User,
    tenant_id: int,
) -> Requisition:
    res = await db.execute(
        select(Requisition).where(
            Requisition.id == requisition_id,
            Requisition.organisation_id == tenant_id,
            Requisition.is_deleted.is_(False),
        )
    )
    req = res.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")
    
    await require_requisition_lines(db, req)
    if (req.examen_status or "").upper() != "EN_EXAMEN":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La réquisition doit être en examen")
    if req.dossier_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Réquisition rattachée à un dossier")

    req.examen_status = "EXAMINE"
    req.examen_commentaire = payload.commentaire
    req.examen_par = user.id
    req.examen_le = _utcnow()
    req.updated_at = _utcnow()
    await db.commit()
    await db.refresh(req)
    return req

async def reject_requisition_examen_logic(
    *,
    db: AsyncSession,
    requisition_id: uuid.UUID,
    payload: RequisitionExamenPayload,
    user: User,
    tenant_id: int,
) -> Requisition:
    res = await db.execute(
        select(Requisition).where(
            Requisition.id == requisition_id,
            Requisition.organisation_id == tenant_id,
            Requisition.is_deleted.is_(False),
        )
    )
    req = res.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisition not found")
    
    await require_requisition_lines(db, req)
    if (req.examen_status or "").upper() != "EN_EXAMEN":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La réquisition doit être en examen")

    dossier_id = req.dossier_id
    req.dossier_id = None
    req.status = "BROUILLON"
    req.examen_status = "REJETE"
    req.examen_commentaire = payload.commentaire
    req.examen_par = user.id
    req.examen_le = _utcnow()
    req.updated_at = _utcnow()

    if dossier_id:
        req_res = await db.execute(
            select(Requisition).where(
                Requisition.dossier_id == dossier_id,
                Requisition.organisation_id == tenant_id,
            )
        )
        remaining = req_res.scalars().all()
        if len(remaining) == 1:
            lone = remaining[0]
            lone.dossier_id = None
            lone.status = "BROUILLON"
            lone.examen_status = "NON_EXAMINE"
            lone.examen_commentaire = None
            lone.examen_par = None
            lone.examen_le = None
            lone.updated_at = _utcnow()

    # « Annuler » une demande, c'est la rejeter : le crédit retourne au poste,
    # pour la réquisition rejetée comme pour la soeur renvoyée en brouillon.
    await resynchroniser_engagement_requisitions(db, [req, *remaining] if dossier_id else [req])

    await db.commit()
    await db.refresh(req)
    return req
