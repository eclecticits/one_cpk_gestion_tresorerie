from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.remboursement_transport import ParticipantTransport
from app.models.user import User
from app.schemas.remboursement_transport import ParticipantTransportCreate, ParticipantTransportResponse

router = APIRouter()


@router.get("", response_model=list[ParticipantTransportResponse])
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


@router.post("", response_model=list[ParticipantTransportResponse], status_code=status.HTTP_201_CREATED)
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
