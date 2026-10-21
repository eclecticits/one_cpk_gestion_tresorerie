from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, has_permission
from app.db.session import get_db
from app.models.encaissement import Encaissement
from app.models.expert_comptable import ExpertComptable
from app.models.projet_activite import ProjetActivite
from app.models.requisition import Requisition
from app.models.sortie_fonds import SortieFonds
from app.models.user import User
from app.schemas.projet_activite import ProjetActiviteCreate, ProjetActiviteResponse, ProjetActiviteUpdate

router = APIRouter(prefix="/projets-activites")


@router.get("", response_model=list[ProjetActiviteResponse])
async def list_projets_activites(
    active: bool | None = Query(default=None),
    type: str | None = Query(default=None),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ProjetActivite).where(ProjetActivite.organisation_id == tenant_id)
    if active is not None:
        stmt = stmt.where(ProjetActivite.is_active.is_(active))
    if type:
        stmt = stmt.where(ProjetActivite.type == type.upper())
    stmt = stmt.order_by(ProjetActivite.type, func.lower(ProjetActivite.libelle))
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("", response_model=ProjetActiviteResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(has_permission("can_edit_settings"))])
async def create_projet_activite(
    payload: ProjetActiviteCreate,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    code = payload.code.strip().upper()
    libelle = payload.libelle.strip()
    duplicate = await db.scalar(
        select(ProjetActivite).where(
            ProjetActivite.organisation_id == tenant_id,
            func.upper(ProjetActivite.code) == code,
        )
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="Ce code projet/activité existe déjà.")
    item = ProjetActivite(
        organisation_id=tenant_id,
        code=code,
        libelle=libelle,
        type=payload.type.upper(),
        description=payload.description,
        is_active=payload.is_active,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.patch("/{item_id}", response_model=ProjetActiviteResponse, dependencies=[Depends(has_permission("can_edit_settings"))])
async def update_projet_activite(
    item_id: int,
    payload: ProjetActiviteUpdate,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    item = await db.scalar(select(ProjetActivite).where(ProjetActivite.id == item_id, ProjetActivite.organisation_id == tenant_id))
    if item is None:
        raise HTTPException(status_code=404, detail="Projet ou activité introuvable.")
    data = payload.model_dump(exclude_unset=True)
    if "code" in data and data["code"] is not None:
        code = data["code"].strip().upper()
        duplicate = await db.scalar(
            select(ProjetActivite).where(
                ProjetActivite.organisation_id == tenant_id,
                func.upper(ProjetActivite.code) == code,
                ProjetActivite.id != item_id,
            )
        )
        if duplicate:
            raise HTTPException(status_code=409, detail="Ce code projet/activité existe déjà.")
        data["code"] = code
    if "libelle" in data and data["libelle"] is not None:
        data["libelle"] = data["libelle"].strip()
    if "type" in data and data["type"] is not None:
        data["type"] = data["type"].upper()
    for key, value in data.items():
        setattr(item, key, value)
    await db.commit()
    await db.refresh(item)
    return item


# ── Entrées et sorties d'un projet ─────────────────────────────────────────
#
# Entrées : encaissements actifs rattachés au projet, pour ce qui a été
# réellement perçu (`montant_paye`, en USD comme partout ailleurs).
# Sorties : sorties de fonds validées dont le projet est celui de la sortie
# (sortie directe) ou, à défaut, celui de sa réquisition. Les montants sont
# gardés par devise : additionner USD et CDF n'aurait pas de sens.

def _bornes(date_debut: date | None, date_fin: date | None) -> tuple[datetime | None, datetime | None]:
    debut = datetime.combine(date_debut, time.min, tzinfo=timezone.utc) if date_debut else None
    fin = datetime.combine(date_fin, time.max, tzinfo=timezone.utc) if date_fin else None
    return debut, fin


def _filtres_entrees(tenant_id: int, debut: datetime | None, fin: datetime | None) -> list[Any]:
    date_entree = func.coalesce(Encaissement.date_paiement, Encaissement.date_encaissement)
    filtres: list[Any] = [
        Encaissement.organisation_id == tenant_id,
        Encaissement.project_activity_id.is_not(None),
        Encaissement.est_proforma.is_(False),
        Encaissement.is_deleted.is_(False),
        or_(Encaissement.statut_operation.is_(None), Encaissement.statut_operation == "ACTIVE"),
        Encaissement.montant_paye > 0,
    ]
    if debut:
        filtres.append(date_entree >= debut)
    if fin:
        filtres.append(date_entree <= fin)
    return filtres


_PROJET_SORTIE = func.coalesce(SortieFonds.project_activity_id, Requisition.project_activity_id)


def _filtres_sorties(tenant_id: int, debut: datetime | None, fin: datetime | None) -> list[Any]:
    filtres: list[Any] = [
        SortieFonds.organisation_id == tenant_id,
        _PROJET_SORTIE.is_not(None),
        SortieFonds.statut == "VALIDE",
        SortieFonds.annulee_le.is_(None),
    ]
    if debut:
        filtres.append(SortieFonds.date_paiement >= debut)
    if fin:
        filtres.append(SortieFonds.date_paiement <= fin)
    return filtres


def _joindre_requisition(stmt):
    return stmt.outerjoin(
        Requisition,
        and_(Requisition.id == SortieFonds.requisition_id, Requisition.organisation_id == SortieFonds.organisation_id),
    )


@router.get("/synthese")
async def synthese_projets_activites(
    date_debut: date | None = Query(default=None),
    date_fin: date | None = Query(default=None),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Totaux d'entrées et de sorties par projet, pour la liste."""
    debut, fin = _bornes(date_debut, date_fin)
    entrees = await db.execute(
        select(
            Encaissement.project_activity_id,
            func.count(Encaissement.id),
            func.coalesce(func.sum(Encaissement.montant_paye), 0),
        )
        .where(*_filtres_entrees(tenant_id, debut, fin))
        .group_by(Encaissement.project_activity_id)
    )
    sorties = await db.execute(
        _joindre_requisition(
            select(_PROJET_SORTIE, SortieFonds.devise, func.count(SortieFonds.id), func.coalesce(func.sum(SortieFonds.montant_paye), 0))
            .select_from(SortieFonds)
        )
        .where(*_filtres_sorties(tenant_id, debut, fin))
        .group_by(_PROJET_SORTIE, SortieFonds.devise)
    )
    par_projet: dict[int, dict[str, Any]] = {}

    def ligne(pid: int) -> dict[str, Any]:
        return par_projet.setdefault(
            pid, {"projet_id": pid, "nb_entrees": 0, "entrees_usd": Decimal("0"), "nb_sorties": 0, "sorties": {}}
        )

    for pid, nb, total in entrees.all():
        ligne(pid).update(nb_entrees=int(nb), entrees_usd=Decimal(total))
    for pid, devise, nb, total in sorties.all():
        item = ligne(pid)
        item["nb_sorties"] += int(nb)
        item["sorties"][(devise or "USD").upper()] = Decimal(total)
    for item in par_projet.values():
        item["solde_usd"] = item["entrees_usd"] - item["sorties"].get("USD", Decimal("0"))
    return list(par_projet.values())


@router.get("/{item_id}/mouvements")
async def mouvements_projet_activite(
    item_id: int,
    date_debut: date | None = Query(default=None),
    date_fin: date | None = Query(default=None),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Détail d'un projet : chaque entrée, chaque sortie, et les totaux."""
    projet = await db.scalar(
        select(ProjetActivite).where(ProjetActivite.id == item_id, ProjetActivite.organisation_id == tenant_id)
    )
    if projet is None:
        raise HTTPException(status_code=404, detail="Projet ou activité introuvable.")
    debut, fin = _bornes(date_debut, date_fin)

    res_entrees = await db.execute(
        select(Encaissement, ExpertComptable.nom_denomination)
        .outerjoin(ExpertComptable, ExpertComptable.id == Encaissement.expert_comptable_id)
        .where(*_filtres_entrees(tenant_id, debut, fin), Encaissement.project_activity_id == item_id)
        .order_by(func.coalesce(Encaissement.date_paiement, Encaissement.date_encaissement).desc())
    )
    entrees = [
        {
            "id": str(enc.id),
            "date": enc.date_paiement or enc.date_encaissement,
            "numero": enc.numero_recu,
            "tiers": nom_expert or enc.client_nom or enc.type_client,
            "montant_usd": enc.montant_paye,
            "montant_percu": enc.montant_percu,
            "devise_perception": enc.devise_perception,
            "canal": enc.canal,
            "statut_paiement": enc.statut_paiement,
        }
        for enc, nom_expert in res_entrees.all()
    ]

    res_sorties = await db.execute(
        _joindre_requisition(select(SortieFonds, Requisition.numero_requisition).select_from(SortieFonds))
        .where(*_filtres_sorties(tenant_id, debut, fin), _PROJET_SORTIE == item_id)
        .order_by(SortieFonds.date_paiement.desc())
    )
    sorties = [
        {
            "id": str(sortie.id),
            "date": sortie.date_paiement,
            "numero": sortie.reference_numero or sortie.reference,
            "beneficiaire": sortie.beneficiaire,
            "motif": sortie.motif,
            "montant": sortie.montant_paye,
            "devise": sortie.devise,
            "canal": sortie.canal,
            "requisition": numero_requisition,
        }
        for sortie, numero_requisition in res_sorties.all()
    ]

    sorties_par_devise: dict[str, Decimal] = {}
    for item in sorties:
        devise = (item["devise"] or "USD").upper()
        sorties_par_devise[devise] = sorties_par_devise.get(devise, Decimal("0")) + Decimal(item["montant"] or 0)
    entrees_usd = sum((Decimal(item["montant_usd"] or 0) for item in entrees), Decimal("0"))
    return {
        "projet": {"id": projet.id, "code": projet.code, "libelle": projet.libelle, "type": projet.type},
        "totaux": {
            "entrees_usd": entrees_usd,
            "sorties": sorties_par_devise,
            "solde_usd": entrees_usd - sorties_par_devise.get("USD", Decimal("0")),
        },
        "entrees": entrees,
        "sorties": sorties,
    }
