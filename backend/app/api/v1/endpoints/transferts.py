from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, has_permission
from app.db.session import get_db
from app.models.transfert_interne import TransfertInterne
from app.models.user import User
from app.schemas.transfert import (
    TransfertContrepassationCreate,
    TransfertInterneCreate,
    TransfertInterneOut,
)
from app.services.audit_service import get_request_ip
from app.services.transferts_internes_service import contrepasser_transfer, create_transfer

router = APIRouter()


def _transfer_to_out(t: TransfertInterne) -> TransfertInterneOut:
    return TransfertInterneOut(
        id=t.id, source_type=t.source_type, source_id=t.source_id,
        destination_type=t.destination_type, destination_id=t.destination_id,
        montant=t.montant, devise=t.devise, reference=t.reference,
        date_transfert=t.date_transfert, execute_par=str(t.execute_par) if t.execute_par else None,
        statut=t.statut, idempotency_key=t.idempotency_key,
        contrepasse_le=t.contrepasse_le,
        contrepasse_par=str(t.contrepasse_par) if t.contrepasse_par else None,
        motif_contrepassation=t.motif_contrepassation,
        transfert_origine_id=t.transfert_origine_id,
    )


@router.get("", response_model=list[TransfertInterneOut])
async def list_transferts(
    limit: int = Query(default=50, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[TransfertInterneOut]:
    _ = user
    # Aucun filtre de statut : un transfert contre-passé reste visible, à côté
    # de la ligne inverse qui le corrige. C'est la trace historique attendue.
    result = await db.execute(
        select(TransfertInterne)
        .where(TransfertInterne.organisation_id == tenant_id)
        .order_by(TransfertInterne.date_transfert.desc())
        .offset(offset).limit(limit)
    )
    return [_transfer_to_out(item) for item in result.scalars().all()]


@router.post("", response_model=TransfertInterneOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(has_permission("sorties_fonds"))])
async def create_transfert(
    payload: TransfertInterneCreate,
    # `Request` nu, jamais `Request | None` : FastAPI ne reconnaît l'objet
    # requête que sur l'annotation exacte. Rendue optionnelle, elle devient un
    # champ de body et l'enregistrement de la route échoue — le module entier
    # cesse alors d'être importable, donc l'application de démarrer.
    request: Request,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> TransfertInterneOut:
    # Les appels HTTP reçoivent une chaîne ou None ; les tests directs peuvent
    # transmettre l'objet par défaut de FastAPI avant résolution des dépendances.
    header_key = idempotency_key if isinstance(idempotency_key, str) else None
    transfer = await create_transfer(
        db, payload=payload, tenant_id=tenant_id, user=user,
        idempotency_key=header_key, ip_address=get_request_ip(request),
    )
    return _transfer_to_out(transfer)


@router.post(
    "/{transfer_id}/contrepassation",
    response_model=TransfertInterneOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_permission("sorties_fonds"))],
)
async def contrepasser_transfert(
    transfer_id: int,
    payload: TransfertContrepassationCreate,
    request: Request,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> TransfertInterneOut:
    """Corrige un transfert par un transfert inverse daté du jour.

    Renvoie **201 avec la ligne inverse** : la correction est une opération
    financière à part entière, pas la mise à jour de l'original.
    """
    inverse = await contrepasser_transfer(
        db, transfer_id=transfer_id, tenant_id=tenant_id, user=user,
        motif=payload.motif, ip_address=get_request_ip(request),
    )
    return _transfer_to_out(inverse)
