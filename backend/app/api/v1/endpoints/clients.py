from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user
from app.db.session import get_db
from app.models.client import Client
from app.models.encaissement import Encaissement
from app.models.user import User
from app.schemas.client import ClientCreate, ClientOut, ClientUpdate

router = APIRouter()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _out(client: Client, *, nb: int | None = None, dernier: datetime | None = None) -> ClientOut:
    return ClientOut(
        id=client.id,
        nom=client.nom,
        type_client=client.type_client,
        email=client.email,
        telephone=client.telephone,
        sexe=client.sexe,
        adresse=client.adresse,
        notes=client.notes,
        active=client.active,
        nb_encaissements=nb,
        dernier_encaissement=dernier,
        created_at=client.created_at,
    )


@router.get("", response_model=list[ClientOut])
async def list_clients(
    search: str | None = Query(default=None, description="Recherche par nom, email ou téléphone"),
    active: bool | None = Query(
        default=None,
        description="true = actifs uniquement, false = bloqués uniquement, absent = tous",
    ),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[ClientOut]:
    _ = user
    query = select(Client).where(Client.organisation_id == tenant_id)
    if active is not None:
        query = query.where(Client.active.is_(active))
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.where(
            or_(
                Client.nom.ilike(term),
                Client.email.ilike(term),
                Client.telephone.ilike(term),
            )
        )
        # Les noms qui COMMENCENT par le terme d'abord, puis les autres.
        prefix = f"{search.strip()}%"
        query = query.order_by(
            Client.nom.ilike(prefix).desc(),
            func.lower(Client.nom).asc(),
        )
    else:
        query = query.order_by(func.lower(Client.nom).asc())
    res = await db.execute(query.limit(limit).offset(offset))
    clients = list(res.scalars().all())
    if not clients:
        return []

    # Historique : nombre d'encaissements et date du dernier, par client.
    ids = [c.id for c in clients]
    stats_res = await db.execute(
        select(
            Encaissement.client_id,
            func.count(Encaissement.id),
            func.max(Encaissement.date_encaissement),
        )
        .where(Encaissement.client_id.in_(ids))
        .group_by(Encaissement.client_id)
    )
    stats = {row[0]: (row[1], row[2]) for row in stats_res.all()}
    return [
        _out(c, nb=stats.get(c.id, (0, None))[0], dernier=stats.get(c.id, (0, None))[1])
        for c in clients
    ]


@router.post("", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
async def create_client(
    payload: ClientCreate,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ClientOut:
    nom = (payload.nom or "").strip()
    if len(nom) < 2:
        raise HTTPException(status_code=400, detail="Nom du client trop court")
    existing_res = await db.execute(
        select(Client).where(
            Client.organisation_id == tenant_id,
            func.lower(Client.nom) == nom.lower(),
        )
    )
    existing = existing_res.scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Un client nommé « {existing.nom} » existe déjà. Sélectionnez-le dans la liste.",
        )
    client = Client(
        organisation_id=tenant_id,
        nom=nom,
        type_client=payload.type_client,
        email=(payload.email or "").strip() or None,
        telephone=(payload.telephone or "").strip() or None,
        # Déjà ramené à 'M', 'F' ou None par le validateur du schéma.
        sexe=payload.sexe,
        adresse=payload.adresse,
        notes=payload.notes,
        active=True,
        created_by=user.id,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    db.add(client)
    await db.commit()
    await db.refresh(client)
    return _out(client)


@router.put("/{client_id}", response_model=ClientOut)
async def update_client(
    client_id: str,
    payload: ClientUpdate,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ClientOut:
    _ = user
    try:
        cid = uuid.UUID(client_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="client_id invalide")
    res = await db.execute(
        select(Client).where(Client.id == cid, Client.organisation_id == tenant_id)
    )
    client = res.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client introuvable")

    if payload.nom is not None and payload.nom.strip():
        nouveau_nom = payload.nom.strip()
        if nouveau_nom.lower() != (client.nom or "").lower():
            dup_res = await db.execute(
                select(Client.id).where(
                    Client.organisation_id == tenant_id,
                    func.lower(Client.nom) == nouveau_nom.lower(),
                    Client.id != client.id,
                )
            )
            if dup_res.scalar_one_or_none() is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Un autre client porte déjà ce nom.",
                )
        client.nom = nouveau_nom
    if payload.type_client is not None:
        client.type_client = payload.type_client
    if payload.email is not None:
        client.email = payload.email.strip() or None
    if payload.telephone is not None:
        client.telephone = payload.telephone.strip() or None
    if payload.sexe is not None:
        client.sexe = payload.sexe
    if payload.adresse is not None:
        client.adresse = payload.adresse
    if payload.notes is not None:
        client.notes = payload.notes
    if payload.active is not None:
        client.active = payload.active
    client.updated_at = _utcnow()
    await db.commit()
    await db.refresh(client)
    return _out(client)


@router.delete("/{client_id}")
async def delete_client(
    client_id: str,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    _ = user
    try:
        cid = uuid.UUID(client_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="client_id invalide")
    res = await db.execute(
        select(Client).where(Client.id == cid, Client.organisation_id == tenant_id)
    )
    client = res.scalar_one_or_none()
    if client is None:
        raise HTTPException(status_code=404, detail="Client introuvable")

    # Intégrité : un client rattaché à des encaissements ne peut pas être supprimé
    # (l'historique financier doit rester traçable). On oriente vers le blocage.
    count_res = await db.execute(
        select(func.count(Encaissement.id)).where(Encaissement.client_id == cid)
    )
    nb = int(count_res.scalar_one() or 0)
    if nb > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Ce client est lié à {nb} encaissement(s) : suppression impossible. "
                "Bloquez-le plutôt : il disparaît des suggestions tout en conservant l'historique."
            ),
        )

    await db.delete(client)
    await db.commit()
    return {"ok": True}
