from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.requisition import Requisition
from app.models.remboursement_transport import ParticipantTransport, RemboursementTransport
from app.models.user import User
from app.schemas.remboursement_transport import (
    ParticipantTransportCreate,
    ParticipantTransportResponse,
    RemboursementTransportCreate,
    RemboursementTransportResponse,
)
from app.services.document_sequences import generate_document_number

router = APIRouter()


def _user_info(user: User | None) -> dict[str, str | None] | None:
    if not user:
        return None
    return {
        "id": str(user.id),
        "prenom": user.prenom,
        "nom": user.nom,
        "email": user.email,
    }


def _requisition_payload(req: Requisition, users_map: dict[uuid.UUID, User]) -> dict[str, object]:
    return {
        "id": str(req.id),
        "numero_requisition": req.numero_requisition,
        "reference_numero": req.reference_numero,
        "objet": req.objet,
        "mode_paiement": req.mode_paiement,
        "type_requisition": req.type_requisition,
        "montant_total": req.montant_total or 0,
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
        "created_at": req.created_at,
        "updated_at": req.updated_at,
        "demandeur": _user_info(users_map.get(req.created_by)) if req.created_by else None,
        "validateur": _user_info(users_map.get(req.validee_par)) if req.validee_par else None,
        "approbateur": _user_info(users_map.get(req.approuvee_par)) if req.approuvee_par else None,
        "caissier": _user_info(users_map.get(req.payee_par)) if req.payee_par else None,
    }


@router.get("", response_model=list[RemboursementTransportResponse])
async def list_remboursements_transport(
    include: str | None = Query(default=None),
    requisition_id: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[RemboursementTransportResponse]:
    query = select(RemboursementTransport).order_by(RemboursementTransport.created_at.desc()).offset(offset).limit(limit)
    if requisition_id:
        try:
            rid = uuid.UUID(requisition_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")
        query = query.where(RemboursementTransport.requisition_id == rid)

    res = await db.execute(query)
    remboursements = res.scalars().all()

    include_parts = {p.strip() for p in include.split(",")} if include else set()
    participants_map: dict[str, list[ParticipantTransportResponse]] = {}
    if "participants" in include_parts:
        ids = [r.id for r in remboursements]
        if ids:
            p_res = await db.execute(select(ParticipantTransport).where(ParticipantTransport.remboursement_id.in_(ids)))
            participants = p_res.scalars().all()
            for p in participants:
                participants_map.setdefault(str(p.remboursement_id), []).append(
                    ParticipantTransportResponse(
                        id=str(p.id),
                        remboursement_id=str(p.remboursement_id),
                        nom=p.nom,
                        titre_fonction=p.titre_fonction,
                        montant=p.montant,
                        type_participant=p.type_participant,
                        expert_comptable_id=str(p.expert_comptable_id) if p.expert_comptable_id else None,
                        created_at=p.created_at,
                    )
                )

    requisitions_map: dict[uuid.UUID, Requisition] = {}
    users_map: dict[uuid.UUID, User] = {}
    if "requisition" in include_parts:
        req_ids = [r.requisition_id for r in remboursements if r.requisition_id]
        if req_ids:
            req_res = await db.execute(select(Requisition).where(Requisition.id.in_(req_ids)))
            requisitions = req_res.scalars().all()
            requisitions_map = {r.id: r for r in requisitions}

            user_ids: set[uuid.UUID] = set()
            for r in requisitions:
                if r.created_by:
                    user_ids.add(r.created_by)
                if r.validee_par:
                    user_ids.add(r.validee_par)
                if r.approuvee_par:
                    user_ids.add(r.approuvee_par)
                if r.payee_par:
                    user_ids.add(r.payee_par)
            if user_ids:
                users_res = await db.execute(select(User).where(User.id.in_(list(user_ids))))
                users_map = {u.id: u for u in users_res.scalars().all()}

    responses: list[RemboursementTransportResponse] = []
    for r in remboursements:
        requisition_payload = None
        if "requisition" in include_parts and r.requisition_id:
            req = requisitions_map.get(r.requisition_id)
            if req:
                requisition_payload = _requisition_payload(req, users_map)
        responses.append(
            RemboursementTransportResponse(
                id=str(r.id),
                numero_remboursement=r.numero_remboursement,
                reference_numero=r.reference_numero,
                instance=r.instance,
                type_reunion=r.type_reunion,
                nature_reunion=r.nature_reunion,
                nature_travail=r.nature_travail or [],
                lieu=r.lieu,
                date_reunion=r.date_reunion,
                heure_debut=r.heure_debut,
                heure_fin=r.heure_fin,
                montant_total=r.montant_total or Decimal(0),
                requisition_id=str(r.requisition_id) if r.requisition_id else None,
                created_at=r.created_at,
                created_by=str(r.created_by) if r.created_by else None,
                trans_titre_officiel_hist=r.trans_titre_officiel_hist,
                trans_label_gauche_hist=r.trans_label_gauche_hist,
                trans_nom_gauche_hist=r.trans_nom_gauche_hist,
                trans_label_droite_hist=r.trans_label_droite_hist,
                trans_nom_droite_hist=r.trans_nom_droite_hist,
                signataire_g_label=r.signataire_g_label,
                signataire_g_nom=r.signataire_g_nom,
                signataire_d_label=r.signataire_d_label,
                signataire_d_nom=r.signataire_d_nom,
                participants=participants_map.get(str(r.id)),
                requisition=requisition_payload,
            )
        )

    return responses


@router.post("", response_model=RemboursementTransportResponse, status_code=status.HTTP_201_CREATED)
async def create_remboursement_transport(
    payload: RemboursementTransportCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RemboursementTransportResponse:
    requisition_id = None
    if payload.requisition_id:
        try:
            requisition_id = uuid.UUID(payload.requisition_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid requisition_id")

    created_by = None
    if payload.created_by:
        try:
            created_by = uuid.UUID(payload.created_by)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid created_by")

    numero_remboursement = await generate_document_number(db, "REM")
    r = RemboursementTransport(
        numero_remboursement=numero_remboursement,
        reference_numero=numero_remboursement,
        instance=payload.instance,
        type_reunion=payload.type_reunion,
        nature_reunion=payload.nature_reunion,
        nature_travail=payload.nature_travail,
        lieu=payload.lieu,
        date_reunion=payload.date_reunion,
        heure_debut=payload.heure_debut,
        heure_fin=payload.heure_fin,
        montant_total=payload.montant_total or Decimal(0),
        requisition_id=requisition_id,
        created_by=created_by or user.id,
    )
    db.add(r)
    await db.commit()
    await db.refresh(r)

    return RemboursementTransportResponse(
        id=str(r.id),
        numero_remboursement=r.numero_remboursement,
        instance=r.instance,
        type_reunion=r.type_reunion,
        nature_reunion=r.nature_reunion,
        nature_travail=r.nature_travail or [],
        lieu=r.lieu,
        date_reunion=r.date_reunion,
        heure_debut=r.heure_debut,
        heure_fin=r.heure_fin,
        montant_total=r.montant_total or Decimal(0),
        requisition_id=str(r.requisition_id) if r.requisition_id else None,
        created_at=r.created_at,
        created_by=str(r.created_by) if r.created_by else None,
        reference_numero=r.reference_numero,
        trans_titre_officiel_hist=r.trans_titre_officiel_hist,
        trans_label_gauche_hist=r.trans_label_gauche_hist,
        trans_nom_gauche_hist=r.trans_nom_gauche_hist,
        trans_label_droite_hist=r.trans_label_droite_hist,
        trans_nom_droite_hist=r.trans_nom_droite_hist,
        signataire_g_label=r.signataire_g_label,
        signataire_g_nom=r.signataire_g_nom,
        signataire_d_label=r.signataire_d_label,
        signataire_d_nom=r.signataire_d_nom,
        participants=None,
    )


@router.get("/participants", response_model=list[ParticipantTransportResponse])
async def list_participants_transport(
    remboursement_id: str | None = Query(default=None),
    limit: int = Query(default=200, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ParticipantTransportResponse]:
    query = select(ParticipantTransport).offset(offset).limit(limit)
    if remboursement_id:
        try:
            rid = uuid.UUID(remboursement_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid remboursement_id")
        query = query.where(ParticipantTransport.remboursement_id == rid)

    res = await db.execute(query)
    participants = res.scalars().all()
    return [
        ParticipantTransportResponse(
            id=str(p.id),
            remboursement_id=str(p.remboursement_id),
            nom=p.nom,
            titre_fonction=p.titre_fonction,
            montant=p.montant,
            type_participant=p.type_participant,
            expert_comptable_id=str(p.expert_comptable_id) if p.expert_comptable_id else None,
            created_at=p.created_at,
        )
        for p in participants
    ]


@router.post("/participants", response_model=list[ParticipantTransportResponse])
async def create_participants_transport(
    payload: list[ParticipantTransportCreate],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ParticipantTransportResponse]:
    created: list[ParticipantTransport] = []
    for item in payload:
        try:
            rid = uuid.UUID(item.remboursement_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid remboursement_id")

        expert_id = None
        if item.expert_comptable_id:
            try:
                expert_id = uuid.UUID(item.expert_comptable_id)
            except ValueError:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid expert_comptable_id")

        p = ParticipantTransport(
            remboursement_id=rid,
            nom=item.nom,
            titre_fonction=item.titre_fonction,
            montant=item.montant or Decimal(0),
            type_participant=item.type_participant,
            expert_comptable_id=expert_id,
        )
        db.add(p)
        created.append(p)

    await db.commit()
    for p in created:
        await db.refresh(p)

    return [
        ParticipantTransportResponse(
            id=str(p.id),
            remboursement_id=str(p.remboursement_id),
            nom=p.nom,
            titre_fonction=p.titre_fonction,
            montant=p.montant,
            type_participant=p.type_participant,
            expert_comptable_id=str(p.expert_comptable_id) if p.expert_comptable_id else None,
            created_at=p.created_at,
        )
        for p in created
    ]
