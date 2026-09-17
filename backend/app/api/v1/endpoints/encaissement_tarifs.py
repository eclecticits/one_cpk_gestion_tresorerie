"""Tarifs d'encaissement : ce que vaut un libellé connu, et où il s'impute.

Lecture ouverte à qui encaisse (la saisie en a besoin), écriture réservée aux
réglages (`can_edit_settings`), comme les autres référentiels.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, has_permission
from app.db.session import get_db
from app.models.budget import BudgetPoste
from app.models.encaissement_tarif import EncaissementTarif, normaliser_libelle
from app.models.user import User
from app.schemas.encaissement_tarif import (
    EncaissementTarifCreate,
    EncaissementTarifOut,
    EncaissementTarifUpdate,
)
from app.services.encaissement_tarifs import postes_par_code, tarifs_resolus

router = APIRouter(prefix="/encaissement-tarifs")


def _sortie(tarif: EncaissementTarif, poste: BudgetPoste | None) -> EncaissementTarifOut:
    return EncaissementTarifOut(
        id=tarif.id,
        libelle=tarif.libelle,
        montant=tarif.montant,
        devise=tarif.devise,
        budget_poste_code=tarif.budget_poste_code,
        is_active=tarif.is_active,
        position=tarif.position,
        budget_poste_id=poste.id if poste else None,
        budget_poste_libelle=poste.libelle if poste else None,
        created_at=tarif.created_at,
        updated_at=tarif.updated_at,
    )


async def _poste_du_code(db: AsyncSession, tenant_id: int, code: str | None) -> BudgetPoste | None:
    if not (code or "").strip():
        return None
    return (await postes_par_code(db, tenant_id, [code or ""])).get((code or "").strip().upper())


async def _refuser_doublon(db: AsyncSession, tenant_id: int, libelle: str, *, sauf_id: int | None = None) -> None:
    """Un libellé ne peut désigner qu'un tarif : sinon la saisie ne saurait pas
    lequel appliquer. La casse et les espaces ne font pas deux libellés."""
    requete = select(EncaissementTarif).where(
        EncaissementTarif.organisation_id == tenant_id,
        EncaissementTarif.libelle_normalise == normaliser_libelle(libelle),
    )
    if sauf_id is not None:
        requete = requete.where(EncaissementTarif.id != sauf_id)
    if (await db.execute(requete.limit(1))).scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ce libellé de tarif existe déjà.")


@router.get("", response_model=list[EncaissementTarifOut])
async def list_encaissement_tarifs(
    actifs: bool = Query(default=False, description="N'afficher que les tarifs actifs"),
    _user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[EncaissementTarifOut]:
    return [
        _sortie(tarif, poste)
        for tarif, poste in await tarifs_resolus(db, tenant_id, actifs_seulement=actifs)
    ]


@router.post(
    "",
    response_model=EncaissementTarifOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_permission("can_edit_settings"))],
)
async def create_encaissement_tarif(
    payload: EncaissementTarifCreate,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> EncaissementTarifOut:
    libelle = payload.libelle.strip()
    await _refuser_doublon(db, tenant_id, libelle)
    # La position par défaut met le nouveau tarif en fin de liste, là où
    # l'ancienne pré-liste ajoutait ses lignes.
    derniere = (
        await db.execute(
            select(func.coalesce(func.max(EncaissementTarif.position), 0)).where(
                EncaissementTarif.organisation_id == tenant_id
            )
        )
    ).scalar_one()
    tarif = EncaissementTarif(
        organisation_id=tenant_id,
        libelle=libelle,
        libelle_normalise=normaliser_libelle(libelle),
        montant=payload.montant,
        devise=payload.devise,
        budget_poste_code=(payload.budget_poste_code or "").strip().upper() or None,
        is_active=payload.is_active,
        position=payload.position or int(derniere) + 1,
        created_by=user.id,
    )
    db.add(tarif)
    await db.commit()
    await db.refresh(tarif)
    return _sortie(tarif, await _poste_du_code(db, tenant_id, tarif.budget_poste_code))


@router.patch(
    "/{tarif_id}",
    response_model=EncaissementTarifOut,
    dependencies=[Depends(has_permission("can_edit_settings"))],
)
async def update_encaissement_tarif(
    tarif_id: int,
    payload: EncaissementTarifUpdate,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> EncaissementTarifOut:
    tarif = (
        await db.execute(
            select(EncaissementTarif).where(
                EncaissementTarif.id == tarif_id,
                EncaissementTarif.organisation_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if tarif is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarif introuvable.")

    data = payload.model_dump(exclude_unset=True)
    if "libelle" in data and data["libelle"]:
        libelle = data["libelle"].strip()
        await _refuser_doublon(db, tenant_id, libelle, sauf_id=tarif_id)
        tarif.libelle = libelle
        tarif.libelle_normalise = normaliser_libelle(libelle)
    # `montant` et `budget_poste_code` se vident indépendamment l'un de l'autre :
    # un tarif peut ne fixer que le prix, ne fixer que l'imputation, ou les deux.
    if "montant" in data:
        tarif.montant = data["montant"]
    if "devise" in data and data["devise"]:
        tarif.devise = data["devise"]
    if "budget_poste_code" in data:
        tarif.budget_poste_code = (data["budget_poste_code"] or "").strip().upper() or None
    if "is_active" in data and data["is_active"] is not None:
        tarif.is_active = data["is_active"]
    if "position" in data and data["position"] is not None:
        tarif.position = data["position"]

    await db.commit()
    await db.refresh(tarif)
    return _sortie(tarif, await _poste_du_code(db, tenant_id, tarif.budget_poste_code))


@router.delete(
    "/{tarif_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[Depends(has_permission("can_edit_settings"))],
)
async def delete_encaissement_tarif(
    tarif_id: int,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    tarif = (
        await db.execute(
            select(EncaissementTarif).where(
                EncaissementTarif.id == tarif_id,
                EncaissementTarif.organisation_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if tarif is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarif introuvable.")
    # Suppression franche : un tarif ne porte aucun historique — les
    # encaissements gardent leur propre montant et leur propre imputation.
    # Pour cesser de le proposer sans le perdre, il y a `is_active`.
    await db.delete(tarif)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
