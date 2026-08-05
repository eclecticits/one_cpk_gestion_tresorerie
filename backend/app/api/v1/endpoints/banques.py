from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, has_permission, get_current_tenant_id
from app.db.session import get_db
from app.models.banque import Banque
from app.models.compte_bancaire import CompteBancaire
from app.models.encaissement import Encaissement
from app.models.sortie_fonds import SortieFonds
from app.models.user import User
from app.services.audit_service import log_action
from app.schemas.banque import (
    BanqueCreate,
    BanqueOut,
    BanqueUpdate,
    CompteBancaireCreate,
    CompteBancaireOut,
    CompteBancaireUpdate,
)

router = APIRouter()


SENSITIVE_BANK_FIELDS = {"numero_compte", "rib", "identifiant_client"}


def _mask_bank_value(value: object) -> object:
    if value is None:
        return None
    text = str(value)
    if len(text) <= 4:
        return "*" * len(text)
    return f"{'*' * max(len(text) - 4, 4)}{text[-4:]}"


def _audit_snapshot(compte: CompteBancaire) -> dict[str, object]:
    data: dict[str, object] = {
        "organisation_id": compte.organisation_id,
        "banque_id": compte.banque_id,
        "intitule": compte.intitule,
        "numero_compte": compte.numero_compte,
        "rib": compte.rib,
        "identifiant_client": compte.identifiant_client,
        "code_swift_bic": compte.code_swift_bic,
        "compte_comptable_associe": compte.compte_comptable_associe,
        "journal_comptable_associe": compte.journal_comptable_associe,
        "date_ouverture": compte.date_ouverture.isoformat() if compte.date_ouverture else None,
        "devise": compte.devise,
        "solde_initial": str(compte.solde_initial),
        "solde_actuel": str(compte.solde_actuel),
        "is_active": compte.is_active,
        "is_principal": compte.is_principal,
        "agence_bancaire": compte.agence_bancaire,
        "observations": compte.observations,
        "account_type": compte.account_type,
    }
    for field in SENSITIVE_BANK_FIELDS:
        data[field] = _mask_bank_value(data[field])
    return data


def _changed_values(old: dict[str, object], new: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    keys = sorted({*old.keys(), *new.keys()})
    old_changed: dict[str, object] = {}
    new_changed: dict[str, object] = {}
    for key in keys:
        if old.get(key) != new.get(key):
            old_changed[key] = old.get(key)
            new_changed[key] = new.get(key)
    return old_changed, new_changed


async def _ensure_banque_exists(db: AsyncSession, *, banque_id: int | None, tenant_id: int) -> Banque:
    if banque_id is None:
        raise HTTPException(status_code=400, detail="banque_id requis")
    res = await db.execute(
        select(Banque).where(
            Banque.id == banque_id,
            Banque.organisation_id == tenant_id,
        )
    )
    banque = res.scalar_one_or_none()
    if banque is None:
        raise HTTPException(status_code=400, detail="banque_id invalide")
    return banque


async def _ensure_account_unique(
    db: AsyncSession,
    *,
    tenant_id: int,
    banque_id: int,
    devise: str,
    numero_compte: str,
    exclude_id: int | None = None,
) -> None:
    stmt = select(CompteBancaire.id).where(
        CompteBancaire.organisation_id == tenant_id,
        CompteBancaire.banque_id == banque_id,
        CompteBancaire.devise == devise,
        CompteBancaire.numero_compte == numero_compte,
        CompteBancaire.account_type == "BANK",
    )
    if exclude_id is not None:
        stmt = stmt.where(CompteBancaire.id != exclude_id)
    dupe = await db.execute(stmt.limit(1))
    if dupe.first() is not None:
        raise HTTPException(status_code=409, detail="numero_compte déjà utilisé pour cette banque et cette devise")


async def _ensure_rib_unique(
    db: AsyncSession,
    *,
    tenant_id: int,
    rib: str | None,
    exclude_id: int | None = None,
) -> None:
    if not rib:
        return
    stmt = select(CompteBancaire.id).where(
        CompteBancaire.organisation_id == tenant_id,
        CompteBancaire.rib == rib,
        CompteBancaire.account_type == "BANK",
    )
    if exclude_id is not None:
        stmt = stmt.where(CompteBancaire.id != exclude_id)
    dupe = await db.execute(stmt.limit(1))
    if dupe.first() is not None:
        raise HTTPException(status_code=409, detail="rib déjà utilisé")


async def _set_unique_principal(
    db: AsyncSession,
    *,
    tenant_id: int,
    compte_id: int,
    devise: str,
) -> list[tuple[int, dict[str, object], dict[str, object]]]:
    res = await db.execute(
        select(CompteBancaire).where(
            CompteBancaire.organisation_id == tenant_id,
            CompteBancaire.devise == devise,
            CompteBancaire.account_type == "BANK",
            CompteBancaire.id != compte_id,
            CompteBancaire.is_principal.is_(True),
        )
    )
    principals = res.scalars().all()
    changes: list[tuple[int, dict[str, object], dict[str, object]]] = []
    for principal in principals:
        old_snapshot = _audit_snapshot(principal)
        new_snapshot = {**old_snapshot, "is_principal": False}
        changes.append((principal.id, old_snapshot, new_snapshot))
    await db.execute(
        update(CompteBancaire)
        .where(
            CompteBancaire.organisation_id == tenant_id,
            CompteBancaire.devise == devise,
            CompteBancaire.account_type == "BANK",
            CompteBancaire.id != compte_id,
            CompteBancaire.is_principal.is_(True),
        )
        .values(is_principal=False)
    )
    return changes


@router.get("/banques", response_model=list[BanqueOut])
async def list_banques(
    active: bool | None = Query(default=None),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[BanqueOut]:
    stmt = select(Banque).where(Banque.organisation_id == tenant_id)
    if active is not None:
        stmt = stmt.where(Banque.is_active.is_(active))
    stmt = stmt.order_by(func.lower(Banque.nom).asc())
    res = await db.execute(stmt)
    return [BanqueOut.model_validate(b) for b in res.scalars().all()]


@router.post("/banques", response_model=BanqueOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(has_permission("can_edit_settings"))])
async def create_banque(
    payload: BanqueCreate,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> BanqueOut:
    nom = payload.nom.strip()
    if not nom:
        raise HTTPException(status_code=400, detail="nom requis")
    res = await db.execute(
        select(Banque).where(
            func.lower(Banque.nom) == nom.lower(),
            Banque.organisation_id == tenant_id,
        )
    )
    if res.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="nom banque déjà utilisé")

    banque = Banque(
        organisation_id=tenant_id,
        nom=nom,
        code=(payload.code or "").strip() or None,
        is_active=payload.is_active,
    )
    db.add(banque)
    await db.commit()
    await db.refresh(banque)
    return BanqueOut.model_validate(banque)


@router.patch("/banques/{banque_id}", response_model=BanqueOut, dependencies=[Depends(has_permission("can_edit_settings"))])
async def update_banque(
    banque_id: int,
    payload: BanqueUpdate,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> BanqueOut:
    res = await db.execute(select(Banque).where(Banque.id == banque_id, Banque.organisation_id == tenant_id))
    banque = res.scalar_one_or_none()
    if banque is None:
        raise HTTPException(status_code=404, detail="Banque introuvable")

    data = payload.model_dump(exclude_unset=True)
    if "nom" in data and data["nom"] is not None:
        nom = data["nom"].strip()
        if not nom:
            raise HTTPException(status_code=400, detail="nom requis")
        res_dupe = await db.execute(
            select(Banque).where(
                func.lower(Banque.nom) == nom.lower(),
                Banque.organisation_id == tenant_id,
                Banque.id != banque.id,
            )
        )
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
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    res = await db.execute(select(Banque).where(Banque.id == banque_id, Banque.organisation_id == tenant_id))
    banque = res.scalar_one_or_none()
    if banque is None:
        raise HTTPException(status_code=404, detail="Banque introuvable")

    comptes_res = await db.execute(
        select(CompteBancaire.id)
        .where(CompteBancaire.banque_id == banque_id, CompteBancaire.organisation_id == tenant_id)
        .limit(1)
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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CompteBancaireOut:
    if (payload.account_type or "BANK").upper() != "BANK":
        raise HTTPException(status_code=400, detail="account_type invalide")

    await _ensure_banque_exists(db, banque_id=payload.banque_id, tenant_id=tenant_id)

    devise = (payload.devise or "USD").upper()
    if devise not in {"USD", "CDF"}:
        raise HTTPException(status_code=400, detail="devise invalide")

    numero = payload.numero_compte
    if not numero:
        raise HTTPException(status_code=400, detail="numero_compte requis")
    if not payload.intitule:
        raise HTTPException(status_code=400, detail="intitule requis")

    principal_changes: list[tuple[int, dict[str, object], dict[str, object]]] = []
    if payload.is_principal:
        principal_changes.extend(await _set_unique_principal(db, tenant_id=tenant_id, compte_id=-1, devise=devise))
    await _ensure_account_unique(
        db,
        tenant_id=tenant_id,
        banque_id=payload.banque_id,
        devise=devise,
        numero_compte=numero,
    )
    await _ensure_rib_unique(db, tenant_id=tenant_id, rib=payload.rib)

    solde_initial = payload.solde_initial
    compte = CompteBancaire(
        organisation_id=tenant_id,
        banque_id=payload.banque_id,
        intitule=payload.intitule,
        numero_compte=numero,
        rib=payload.rib,
        identifiant_client=payload.identifiant_client,
        code_swift_bic=payload.code_swift_bic,
        compte_comptable_associe=payload.compte_comptable_associe,
        journal_comptable_associe=payload.journal_comptable_associe,
        date_ouverture=payload.date_ouverture,
        devise=devise,
        solde_initial=solde_initial,
        solde_actuel=solde_initial,
        is_active=payload.is_active,
        is_principal=payload.is_principal,
        agence_bancaire=payload.agence_bancaire,
        observations=payload.observations,
        account_type="BANK",
    )
    db.add(compte)
    await db.flush()
    await log_action(
        db,
        user_id=user.id,
        action="bank_account.create",
        target_table="comptes_bancaires",
        target_id=str(compte.id),
        old_value=None,
        new_value=_audit_snapshot(compte),
    )
    for principal_id, old_value, new_value in principal_changes:
        await log_action(
            db,
            user_id=user.id,
            action="bank_account.principal_change",
            target_table="comptes_bancaires",
            target_id=str(principal_id),
            old_value={"is_principal": old_value["is_principal"]},
            new_value={"is_principal": new_value["is_principal"]},
        )
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
    user: User = Depends(get_current_user),
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
    if "solde_actuel" in data:
        raise HTTPException(
            status_code=400,
            detail="solde_actuel non modifiable directement; utiliser une opération d'ajustement tracée",
        )
    old_snapshot = _audit_snapshot(compte)
    principal_changes: list[tuple[int, dict[str, object], dict[str, object]]] = []
    if "banque_id" in data and data["banque_id"] is not None:
        if compte.account_type == "CASH":
            raise HTTPException(status_code=400, detail="banque_id interdit pour compte CASH")
        await _ensure_banque_exists(db, banque_id=data["banque_id"], tenant_id=tenant_id)
        compte.banque_id = data["banque_id"]
    if "intitule" in data and data["intitule"] is not None:
        compte.intitule = data["intitule"]
    if "numero_compte" in data and data["numero_compte"] is not None:
        numero = data["numero_compte"]
        if not numero:
            raise HTTPException(status_code=400, detail="numero_compte requis")
        compte.numero_compte = numero
    if "devise" in data and data["devise"] is not None:
        devise = (data["devise"] or "").upper()
        if devise not in {"USD", "CDF"}:
            raise HTTPException(status_code=400, detail="devise invalide")
        compte.devise = devise
    if "solde_initial" in data and data["solde_initial"] is not None:
        compte.solde_initial = data["solde_initial"]
    if "rib" in data:
        compte.rib = data["rib"]
    if "identifiant_client" in data:
        compte.identifiant_client = data["identifiant_client"]
    if "code_swift_bic" in data:
        compte.code_swift_bic = data["code_swift_bic"]
    if "compte_comptable_associe" in data:
        compte.compte_comptable_associe = data["compte_comptable_associe"]
    if "journal_comptable_associe" in data:
        compte.journal_comptable_associe = data["journal_comptable_associe"]
    if "date_ouverture" in data:
        compte.date_ouverture = data["date_ouverture"]
    if "is_active" in data:
        compte.is_active = bool(data["is_active"])
    if "is_principal" in data:
        if bool(data["is_principal"]):
            with db.no_autoflush:
                principal_changes.extend(
                    await _set_unique_principal(db, tenant_id=tenant_id, compte_id=compte.id, devise=compte.devise)
                )
            compte.is_principal = True
        else:
            compte.is_principal = False
    if "agence_bancaire" in data:
        compte.agence_bancaire = data["agence_bancaire"]
    if "observations" in data:
        compte.observations = data["observations"]
    if "account_type" in data and data["account_type"] is not None:
        if data["account_type"].upper() != compte.account_type:
            raise HTTPException(status_code=400, detail="account_type immuable")

    if not compte.intitule:
        raise HTTPException(status_code=400, detail="intitule requis")
    if not compte.numero_compte:
        raise HTTPException(status_code=400, detail="numero_compte requis")
    if compte.banque_id is None:
        raise HTTPException(status_code=400, detail="banque_id requis")
    with db.no_autoflush:
        await _ensure_account_unique(
            db,
            tenant_id=tenant_id,
            banque_id=compte.banque_id,
            devise=compte.devise,
            numero_compte=compte.numero_compte,
            exclude_id=compte.id,
        )
        await _ensure_rib_unique(db, tenant_id=tenant_id, rib=compte.rib, exclude_id=compte.id)
        if compte.is_principal:
            principal_changes.extend(
                await _set_unique_principal(db, tenant_id=tenant_id, compte_id=compte.id, devise=compte.devise)
            )

    await db.flush()
    new_snapshot = _audit_snapshot(compte)
    old_changed, new_changed = _changed_values(old_snapshot, new_snapshot)
    if old_changed:
        actions = ["bank_account.update"]
        if old_changed.get("is_active") != new_changed.get("is_active") and "is_active" in old_changed:
            actions.append("bank_account.status_change")
        if old_changed.get("is_principal") != new_changed.get("is_principal") and "is_principal" in old_changed:
            actions.append("bank_account.principal_change")
        for action in actions:
            await log_action(
                db,
                user_id=user.id,
                action=action,
                target_table="comptes_bancaires",
                target_id=str(compte.id),
                old_value=old_changed,
                new_value=new_changed,
            )
    for principal_id, old_value, new_value in principal_changes:
        await log_action(
            db,
            user_id=user.id,
            action="bank_account.principal_change",
            target_table="comptes_bancaires",
            target_id=str(principal_id),
            old_value={"is_principal": old_value["is_principal"]},
            new_value={"is_principal": new_value["is_principal"]},
        )

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
