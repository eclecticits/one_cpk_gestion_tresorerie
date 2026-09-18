"""Tarifs d'encaissement : ce que vaut un libellé connu, et où il s'impute.

Lecture ouverte à qui encaisse (la saisie en a besoin), écriture réservée aux
réglages (`can_edit_settings`), comme les autres référentiels.

Un tarif qui a servi ne se modifie ni ne s'efface : il se CLÔT et se ROUVRE.
Les chiffres du passé ne risquaient rien — un article garde sa propre photo —,
mais la définition, elle, disparaissait : plus moyen de dire qu'un reçu d'hier
avait été émis au prix réglé de l'époque. Une modification substantielle sur un
tarif déjà employé crée donc une version neuve et referme l'ancienne, qui
demeure lisible et continue de valoir pour les dates qu'elle couvrait.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, has_permission
from app.db.session import get_db
from app.models.budget import BudgetPoste
from app.models.encaissement import EncaissementArticle
from app.models.encaissement_tarif import EncaissementTarif, normaliser_libelle
from app.models.user import User
from app.schemas.encaissement_tarif import (
    EncaissementTarifCreate,
    EncaissementTarifOut,
    EncaissementTarifUpdate,
)
from app.services.audit_service import log_action
from app.services.encaissement_tarifs import postes_par_code, tarifs_resolus

router = APIRouter(prefix="/encaissement-tarifs")

#: Ce qui engage un reçu, et mérite donc une version à part entière. `is_active`
#: et `position` n'en sont pas : ils règlent ce que la caisse se voit proposer,
#: non ce qu'un encaissement devait. Les verser ici ferait naître une version à
#: chaque réordonnancement, et l'histoire se noierait dans son propre bruit.
CHAMPS_SUBSTANTIELS = ("libelle", "montant", "devise", "budget_poste_code")


def _sortie(
    tarif: EncaissementTarif, poste: BudgetPoste | None, utilisations: int = 0
) -> EncaissementTarifOut:
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
        effet_du=tarif.effet_du,
        effet_au=tarif.effet_au,
        remplace_id=tarif.remplace_id,
        utilisations=utilisations,
        created_at=tarif.created_at,
        updated_at=tarif.updated_at,
    )


async def _poste_du_code(db: AsyncSession, tenant_id: int, code: str | None) -> BudgetPoste | None:
    if not (code or "").strip():
        return None
    return (await postes_par_code(db, tenant_id, [code or ""])).get((code or "").strip().upper())


async def _usages(db: AsyncSession, tarif_ids: list[int]) -> dict[int, int]:
    """Combien de lignes d'encaissement sont passées sous chaque version.

    C'est ce nombre qui décide si une modification se fait en place ou crée une
    version : un tarif que personne n'a employé n'a pas d'histoire à préserver,
    et le versionner n'apprendrait rien à personne.
    """
    if not tarif_ids:
        return {}
    lignes = (
        await db.execute(
            select(EncaissementArticle.tarif_id, func.count())
            .where(EncaissementArticle.tarif_id.in_(tarif_ids))
            .group_by(EncaissementArticle.tarif_id)
        )
    ).all()
    return {int(tid): int(n) for tid, n in lignes if tid is not None}


async def _refuser_doublon(db: AsyncSession, tenant_id: int, libelle: str, *, sauf_id: int | None = None) -> None:
    """Un libellé ne peut désigner qu'un tarif EN VIGUEUR : sinon la saisie ne
    saurait pas lequel appliquer. La casse et les espaces ne font pas deux
    libellés. Les versions closes gardent le leur sans gêner personne — c'est ce
    qui permet de relire un ancien reçu, et de reprendre un nom abandonné."""
    requete = select(EncaissementTarif).where(
        EncaissementTarif.organisation_id == tenant_id,
        EncaissementTarif.libelle_normalise == normaliser_libelle(libelle),
        EncaissementTarif.effet_au.is_(None),
    )
    if sauf_id is not None:
        requete = requete.where(EncaissementTarif.id != sauf_id)
    if (await db.execute(requete.limit(1))).scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ce libellé de tarif existe déjà.")


def _valeurs(tarif: EncaissementTarif) -> dict[str, Any]:
    """L'état substantiel d'une version, sous une forme comparable.

    Les montants restent des `Decimal` : `Decimal("50")` et `Decimal("50.00")`
    s'y reconnaissent égaux, alors que leurs écritures diffèrent — comparer les
    textes ferait naître une version à chaque enregistrement.
    """
    return {
        "libelle": tarif.libelle,
        "montant": tarif.montant,
        "devise": tarif.devise,
        "budget_poste_code": tarif.budget_poste_code,
    }


def _journal(etat: dict[str, Any]) -> dict[str, Any]:
    """Le même état, écrit pour le journal d'audit (qui ne connaît pas les
    décimaux)."""
    return {**etat, "montant": str(etat["montant"]) if etat["montant"] is not None else None}


@router.get("", response_model=list[EncaissementTarifOut])
async def list_encaissement_tarifs(
    actifs: bool = Query(default=False, description="N'afficher que les tarifs actifs"),
    archives: bool = Query(default=False, description="Inclure les versions closes"),
    _user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[EncaissementTarifOut]:
    resolus = await tarifs_resolus(
        db, tenant_id, actifs_seulement=actifs, inclure_closes=archives
    )
    usages = await _usages(db, [tarif.id for tarif, _ in resolus])
    return [_sortie(tarif, poste, usages.get(tarif.id, 0)) for tarif, poste in resolus]


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
        effet_du=date.today(),
        created_by=user.id,
    )
    db.add(tarif)
    await db.flush()
    await log_action(
        db,
        user_id=user.id,
        action="ENCAISSEMENT_TARIF_CREE",
        target_table="encaissement_tarifs",
        target_id=str(tarif.id),
        new_value=_journal(_valeurs(tarif)),
    )
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
    user: User = Depends(get_current_user),
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
    if tarif.effet_au is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cette version est close : elle ne se modifie plus, elle se relit.",
        )

    data = payload.model_dump(exclude_unset=True)

    # Ce que la demande veut voir, une fois fondu dans l'existant.
    voulu = _valeurs(tarif)
    if "libelle" in data and data["libelle"]:
        voulu["libelle"] = data["libelle"].strip()
    if "montant" in data:
        voulu["montant"] = data["montant"]
    if "devise" in data and data["devise"]:
        voulu["devise"] = data["devise"]
    if "budget_poste_code" in data:
        voulu["budget_poste_code"] = (data["budget_poste_code"] or "").strip().upper() or None

    avant = _valeurs(tarif)
    substantiel = voulu != avant
    renomme = normaliser_libelle(voulu["libelle"]) != tarif.libelle_normalise
    if renomme:
        await _refuser_doublon(db, tenant_id, voulu["libelle"], sauf_id=tarif_id)

    utilise = (await _usages(db, [tarif.id])).get(tarif.id, 0) > 0

    if substantiel and utilise:
        # Une version se clôt aujourd'hui, la suivante prend le relais le même
        # jour : un encaissement daté d'hier retrouvera l'ancienne, avec son
        # prix et son imputation d'alors.
        aujourdhui = date.today()
        tarif.effet_au = aujourdhui
        tarif.archived_at = datetime.now(timezone.utc)
        tarif.archived_by = user.id
        # `is_active` n'est pas touché : il dit ce que la caisse se voit
        # proposer, et l'éteindre ici rendrait la version inapplicable aux
        # dates qu'elle couvrait — le passé cesserait de se relire.
        if "position" in data and data["position"] is not None:
            tarif.position = data["position"]

        nouvelle = EncaissementTarif(
            organisation_id=tenant_id,
            libelle=voulu["libelle"],
            libelle_normalise=normaliser_libelle(voulu["libelle"]),
            montant=voulu["montant"],
            devise=voulu["devise"] or "USD",
            budget_poste_code=voulu["budget_poste_code"],
            is_active=data.get("is_active") if data.get("is_active") is not None else tarif.is_active,
            position=tarif.position,
            effet_du=aujourdhui,
            remplace_id=tarif.id,
            created_by=user.id,
        )
        db.add(nouvelle)
        await db.flush()
        await log_action(
            db,
            user_id=user.id,
            action="ENCAISSEMENT_TARIF_VERSION",
            target_table="encaissement_tarifs",
            target_id=str(nouvelle.id),
            old_value={**_journal(avant), "id": tarif.id, "utilise": utilise},
            new_value={**_journal(_valeurs(nouvelle)), "id": nouvelle.id, "remplace_id": tarif.id},
        )
        await db.commit()
        await db.refresh(nouvelle)
        return _sortie(
            nouvelle,
            await _poste_du_code(db, tenant_id, nouvelle.budget_poste_code),
            0,
        )

    # Rien d'engageant n'a servi : la version se corrige sur place.
    tarif.libelle = voulu["libelle"]
    tarif.libelle_normalise = normaliser_libelle(voulu["libelle"])
    tarif.montant = voulu["montant"]
    tarif.devise = voulu["devise"] or "USD"
    tarif.budget_poste_code = voulu["budget_poste_code"]
    if "is_active" in data and data["is_active"] is not None:
        tarif.is_active = data["is_active"]
    if "position" in data and data["position"] is not None:
        tarif.position = data["position"]

    if substantiel:
        await log_action(
            db,
            user_id=user.id,
            action="ENCAISSEMENT_TARIF_MODIFIE",
            target_table="encaissement_tarifs",
            target_id=str(tarif.id),
            old_value=_journal(avant),
            new_value=_journal(voulu),
        )
    await db.commit()
    await db.refresh(tarif)
    return _sortie(
        tarif,
        await _poste_du_code(db, tenant_id, tarif.budget_poste_code),
        (await _usages(db, [tarif.id])).get(tarif.id, 0),
    )


@router.delete(
    "/{tarif_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[Depends(has_permission("can_edit_settings"))],
)
async def delete_encaissement_tarif(
    tarif_id: int,
    user: User = Depends(get_current_user),
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

    utilise = (await _usages(db, [tarif.id])).get(tarif.id, 0)
    # L'état se lit avant tout effacement : après, l'objet n'a plus à répondre.
    etat = _journal(_valeurs(tarif))
    if utilise:
        # Un tarif qui a servi se clôt : les reçus passés continuent de le
        # désigner, et l'on peut encore dire à quel prix réglé ils sont sortis.
        # La clé étrangère en RESTRICT refuserait de toute façon l'effacement —
        # cette branche dit simplement pourquoi, au lieu d'une erreur de base.
        tarif.effet_au = date.today()
        tarif.archived_at = datetime.now(timezone.utc)
        tarif.archived_by = user.id
        action = "ENCAISSEMENT_TARIF_CLOS"
    else:
        # Jamais employé : rien à préserver, et le garder encombrerait la
        # relecture d'une version qui n'a jamais rien tarifé.
        await db.delete(tarif)
        action = "ENCAISSEMENT_TARIF_SUPPRIME"

    await log_action(
        db,
        user_id=user.id,
        action=action,
        target_table="encaissement_tarifs",
        target_id=str(tarif_id),
        old_value={**etat, "utilisations": utilise},
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
