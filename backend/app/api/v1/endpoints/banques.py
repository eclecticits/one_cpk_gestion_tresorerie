from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, has_permission, get_current_tenant_id
from app.db.session import get_db
from app.models.banque import Banque
from app.models.compte_bancaire import CompteBancaire
from app.models.encaissement import Encaissement
from app.models.sortie_fonds import SortieFonds
from app.models.user import User
from app.schemas.banque import (
    BanqueCreate,
    BanqueOut,
    BanqueUpdate,
    CompteBancaireCreate,
    CompteBancaireOut,
    CompteBancaireUpdate,
)

router = APIRouter()


@router.get("/banques", response_model=list[BanqueOut])
async def list_banques(
    active: bool | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[BanqueOut]:
    stmt = select(Banque)
    if active is not None:
        stmt = stmt.where(Banque.is_active.is_(active))
    stmt = stmt.order_by(func.lower(Banque.nom).asc())
    res = await db.execute(stmt)
    return [BanqueOut.model_validate(b) for b in res.scalars().all()]


@router.post("/banques", response_model=BanqueOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(has_permission("can_edit_settings"))])
async def create_banque(
    payload: BanqueCreate,
    db: AsyncSession = Depends(get_db),
) -> BanqueOut:
    nom = payload.nom.strip()
    if not nom:
        raise HTTPException(status_code=400, detail="nom requis")
    res = await db.execute(select(Banque).where(func.lower(Banque.nom) == nom.lower()))
    if res.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="nom banque déjà utilisé")

    banque = Banque(nom=nom, code=(payload.code or "").strip() or None, is_active=payload.is_active)
    db.add(banque)
    await db.commit()
    await db.refresh(banque)
    return BanqueOut.model_validate(banque)


@router.patch("/banques/{banque_id}", response_model=BanqueOut, dependencies=[Depends(has_permission("can_edit_settings"))])
async def update_banque(
    banque_id: int,
    payload: BanqueUpdate,
    db: AsyncSession = Depends(get_db),
) -> BanqueOut:
    res = await db.execute(select(Banque).where(Banque.id == banque_id))
    banque = res.scalar_one_or_none()
    if banque is None:
        raise HTTPException(status_code=404, detail="Banque introuvable")

    data = payload.model_dump(exclude_unset=True)
    if "nom" in data and data["nom"] is not None:
        nom = data["nom"].strip()
        if not nom:
            raise HTTPException(status_code=400, detail="nom requis")
        res_dupe = await db.execute(select(Banque).where(func.lower(Banque.nom) == nom.lower(), Banque.id != banque.id))
        if res_dupe.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail="nom banque déjà utilisé")
        banque.nom = nom
    if "code" in data:
        banque.code = (data["code"] or "").strip() or None
    if "is_active" in data:
        banque.is_active = bool(data["is_active"])

    await db.commit()
    await db.refresh(banque)
    return BanqueOut.model_validate(banque)


@router.delete("/banques/{banque_id}", dependencies=[Depends(has_permission("can_edit_settings"))])
async def delete_banque(
    banque_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    res = await db.execute(select(Banque).where(Banque.id == banque_id))
    banque = res.scalar_one_or_none()
    if banque is None:
        raise HTTPException(status_code=404, detail="Banque introuvable")

    comptes_res = await db.execute(
        select(CompteBancaire.id).where(CompteBancaire.banque_id == banque_id).limit(1)
    )
    if comptes_res.first() is not None:
        raise HTTPException(status_code=400, detail="Suppression impossible: comptes bancaires existants")

    banque.is_active = False
    await db.commit()
    return {"ok": True, "status": "deactivated"}


@router.get("/comptes-bancaires", response_model=list[CompteBancaireOut])
async def list_comptes_bancaires(
    active: bool | None = Query(default=None),
    banque_id: int | None = Query(default=None),
    devise: str | None = Query(default=None),
    account_type: str | None = Query(default=None),
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CompteBancaireOut]:
    stmt = select(CompteBancaire).options(selectinload(CompteBancaire.banque))
    stmt = stmt.where(CompteBancaire.organisation_id == tenant_id)
    if active is not None:
        stmt = stmt.where(CompteBancaire.is_active.is_(active))
    if banque_id is not None:
        stmt = stmt.where(CompteBancaire.banque_id == banque_id)
    if devise:
        stmt = stmt.where(CompteBancaire.devise == devise.upper())
    if account_type:
        stmt = stmt.where(CompteBancaire.account_type == account_type.upper())
    stmt = stmt.order_by(CompteBancaire.intitule.asc())
    res = await db.execute(stmt)
    return [CompteBancaireOut.model_validate(c) for c in res.scalars().all()]


@router.post(
    "/comptes-bancaires",
    response_model=CompteBancaireOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_permission("can_edit_settings"))],
)
async def create_compte_bancaire(
    payload: CompteBancaireCreate,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> CompteBancaireOut:
    if (payload.account_type or "BANK").upper() != "BANK":
        raise HTTPException(status_code=400, detail="account_type invalide")

    res = await db.execute(select(Banque).where(Banque.id == payload.banque_id))
    if res.scalar_one_or_none() is None:
        raise HTTPException(status_code=400, detail="banque_id invalide")

    devise = (payload.devise or "USD").upper()
    if devise not in {"USD", "CDF"}:
        raise HTTPException(status_code=400, detail="devise invalide")

    numero = payload.numero_compte.strip()
    if not numero:
        raise HTTPException(status_code=400, detail="numero_compte requis")
    dupe = await db.execute(
        select(CompteBancaire).where(
            CompteBancaire.numero_compte == numero,
            CompteBancaire.organisation_id == tenant_id,
        )
    )
    if dupe.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="numero_compte déjà utilisé")

    solde_initial = payload.solde_initial
    compte = CompteBancaire(
        organisation_id=tenant_id,
        banque_id=payload.banque_id,
        intitule=payload.intitule.strip(),
        numero_compte=numero,
        devise=devise,
        solde_initial=solde_initial,
        solde_actuel=payload.solde_actuel or solde_initial,
        is_active=payload.is_active,
        account_type="BANK",
    )
    db.add(compte)
    await db.commit()
    await db.refresh(compte)
    res_compte = await db.execute(
        select(CompteBancaire).options(selectinload(CompteBancaire.banque)).where(CompteBancaire.id == compte.id)
    )
    return CompteBancaireOut.model_validate(res_compte.scalar_one())


@router.patch(
    "/comptes-bancaires/{compte_id}",
    response_model=CompteBancaireOut,
    dependencies=[Depends(has_permission("can_edit_settings"))],
)
async def update_compte_bancaire(
    compte_id: int,
    payload: CompteBancaireUpdate,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> CompteBancaireOut:
    res = await db.execute(
        select(CompteBancaire).where(
            CompteBancaire.id == compte_id,
            CompteBancaire.organisation_id == tenant_id,
        )
    )
    compte = res.scalar_one_or_none()
    if compte is None:
        raise HTTPException(status_code=404, detail="Compte bancaire introuvable")
    if (compte.account_type or "").upper() == "CASH":
        raise HTTPException(status_code=400, detail="Suppression impossible: compte caisse")

    data = payload.model_dump(exclude_unset=True)
    if "banque_id" in data and data["banque_id"] is not None:
        if compte.account_type == "CASH":
            raise HTTPException(status_code=400, detail="banque_id interdit pour compte CASH")
        res_banque = await db.execute(select(Banque).where(Banque.id == data["banque_id"]))
        if res_banque.scalar_one_or_none() is None:
            raise HTTPException(status_code=400, detail="banque_id invalide")
        compte.banque_id = data["banque_id"]
    if "intitule" in data and data["intitule"] is not None:
        compte.intitule = data["intitule"].strip()
    if "numero_compte" in data and data["numero_compte"] is not None:
        numero = data["numero_compte"].strip()
        if not numero:
            raise HTTPException(status_code=400, detail="numero_compte requis")
        dupe = await db.execute(
            select(CompteBancaire).where(
                CompteBancaire.numero_compte == numero,
                CompteBancaire.id != compte.id,
                CompteBancaire.organisation_id == tenant_id,
            )
        )
        if dupe.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail="numero_compte déjà utilisé")
        compte.numero_compte = numero
    if "devise" in data and data["devise"] is not None:
        devise = (data["devise"] or "").upper()
        if devise not in {"USD", "CDF"}:
            raise HTTPException(status_code=400, detail="devise invalide")
        compte.devise = devise
    if "solde_initial" in data and data["solde_initial"] is not None:
        compte.solde_initial = data["solde_initial"]
    if "solde_actuel" in data and data["solde_actuel"] is not None:
        compte.solde_actuel = data["solde_actuel"]
    if "is_active" in data:
        compte.is_active = bool(data["is_active"])
    if "account_type" in data and data["account_type"] is not None:
        if data["account_type"].upper() != compte.account_type:
            raise HTTPException(status_code=400, detail="account_type immuable")

    await db.commit()
    res_compte = await db.execute(
        select(CompteBancaire).options(selectinload(CompteBancaire.banque)).where(CompteBancaire.id == compte.id)
    )
    return CompteBancaireOut.model_validate(res_compte.scalar_one())


@router.delete(
    "/comptes-bancaires/{compte_id}",
    dependencies=[Depends(has_permission("can_edit_settings"))],
)
async def delete_compte_bancaire(
    compte_id: int,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    res = await db.execute(
        select(CompteBancaire).where(
            CompteBancaire.id == compte_id,
            CompteBancaire.organisation_id == tenant_id,
        )
    )
    compte = res.scalar_one_or_none()
    if compte is None:
        raise HTTPException(status_code=404, detail="Compte bancaire introuvable")

    enc_res = await db.execute(
        select(Encaissement.id).where(Encaissement.compte_bancaire_id == compte_id).limit(1)
    )
    if enc_res.first() is not None:
        raise HTTPException(status_code=400, detail="Suppression impossible: encaissements liés")

    sor_res = await db.execute(
        select(SortieFonds.id).where(SortieFonds.compte_bancaire_id == compte_id).limit(1)
    )
    if sor_res.first() is not None:
        raise HTTPException(status_code=400, detail="Suppression impossible: sorties liées")

    compte.is_active = False
    await db.commit()
    return {"ok": True, "status": "deactivated"}
