from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import tenant_scope_bypass
from app.models.encaissement import Encaissement
from app.models.fonds_tiers_operation import FondsTiersOperation
from app.models.fonds_tiers_versement import RequisitionFondsTiers, SortieFondsTiers
from app.models.organisation import Organisation
from app.models.requisition import Requisition
from app.models.sortie_fonds import SortieFonds


# Une opération sans identité exploitable ne doit pas s'afficher comme une case
# vide : le lecteur croirait à un bug d'affichage plutôt qu'à une donnée
# manquante.
TIERS_NON_IDENTIFIE = "Tiers non identifié"

# Une réquisition qui n'a plus rien à payer ne retient plus aucun fonds.
STATUTS_REQUISITION_CLOS = ("PAYEE", "REJETEE", "ANNULEE")


def _money(value: object) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def _display_name_from_org_names(
    operation: FondsTiersOperation,
    org_names: dict[int, str],
) -> tuple[str, str]:
    """Trois provenances possibles, dans l'ordre de confiance décroissant :
    le référentiel des organisations, la saisie libre, puis le champ
    historique conservé pour les opérations antérieures au référentiel."""
    if operation.tiers_organisation_id is not None:
        nom = org_names.get(operation.tiers_organisation_id)
        if nom:
            return nom, "ORGANISATION"
    if (operation.tiers_nom_libre or "").strip():
        return operation.tiers_nom_libre.strip(), "EXTERNE"
    return (operation.tiers_concerne or "").strip() or TIERS_NON_IDENTIFIE, "LEGACY"


async def resolve_fonds_tiers_display_names(
    db: AsyncSession,
    operations: Sequence[FondsTiersOperation],
) -> dict[uuid.UUID, tuple[str, str]]:
    """Résout le tiers de plusieurs opérations en une seule lecture.

    Le nom vit dans `organisations`, table scopée au tenant courant par
    `_apply_tenant_criteria` alors que le tiers est justement un autre tenant :
    d'où le bypass. Il est pris une fois pour tout le lot, et non par opération,
    une liste ou un export pouvant en compter des centaines.
    """
    org_ids = {op.tiers_organisation_id for op in operations if op.tiers_organisation_id is not None}
    org_names: dict[int, str] = {}
    if org_ids:
        async with tenant_scope_bypass(db):
            res = await db.execute(
                select(Organisation.id, Organisation.nom).where(Organisation.id.in_(org_ids))
            )
            org_names = {row_id: nom for row_id, nom in res.all()}
    return {op.id: _display_name_from_org_names(op, org_names) for op in operations}


async def resolve_fonds_tiers_display_name(
    db: AsyncSession,
    operation: FondsTiersOperation,
) -> tuple[str, str]:
    """Variante unitaire. Préférer `resolve_fonds_tiers_display_names` dès qu'il
    y a plus d'une opération : celle-ci fait une lecture par appel."""
    org_names: dict[int, str] = {}
    if operation.tiers_organisation_id is not None:
        async with tenant_scope_bypass(db):
            nom = await db.scalar(
                select(Organisation.nom).where(Organisation.id == operation.tiers_organisation_id).limit(1)
            )
        if nom:
            org_names[operation.tiers_organisation_id] = nom
    return _display_name_from_org_names(operation, org_names)


async def validate_fonds_tiers_identity(
    db: AsyncSession,
    *,
    organisation_id: int,
    tiers_organisation_id: int | None,
    tiers_nom_libre: str | None,
) -> tuple[int | None, str | None]:
    free_name = (tiers_nom_libre or "").strip() or None
    if tiers_organisation_id is not None and free_name is not None:
        raise HTTPException(status_code=400, detail="tiers_organisation_id et tiers_nom_libre sont exclusifs")
    if tiers_organisation_id is None and free_name is None:
        raise HTTPException(status_code=400, detail="tiers_organisation_id ou tiers_nom_libre requis")
    if tiers_organisation_id is not None:
        if int(tiers_organisation_id) == int(organisation_id):
            raise HTTPException(status_code=400, detail="Le tiers doit être une autre organisation")
        async with tenant_scope_bypass(db):
            org = await db.scalar(
                select(Organisation).where(Organisation.id == tiers_organisation_id).limit(1)
            )
        if org is None:
            raise HTTPException(status_code=404, detail="Organisation tiers introuvable")
        if org.is_active is False:
            raise HTTPException(status_code=400, detail="Organisation tiers inactive")
    return tiers_organisation_id, free_name


async def create_fonds_tiers_operation(
    db: AsyncSession,
    *,
    organisation_id: int,
    encaissement: Encaissement,
    tiers_organisation_id: int | None,
    tiers_nom_libre: str | None,
    payeur_origine: str | None,
    motif: str | None,
    reference: str | None,
    piece_justificative: str | None,
    created_by: uuid.UUID | None,
) -> FondsTiersOperation:
    if encaissement.organisation_id != organisation_id:
        raise HTTPException(status_code=404, detail="Encaissement introuvable")
    if (encaissement.nature_mouvement or "").upper() != "FONDS_DE_TIERS":
        raise HTTPException(status_code=400, detail="L'encaissement n'est pas un fonds de tiers")
    valid_tiers_organisation_id, valid_tiers_nom_libre = await validate_fonds_tiers_identity(
        db,
        organisation_id=organisation_id,
        tiers_organisation_id=tiers_organisation_id,
        tiers_nom_libre=tiers_nom_libre,
    )
    operation = FondsTiersOperation(
        organisation_id=organisation_id,
        encaissement_id=encaissement.id,
        statut="OUVERT",
        tiers_organisation_id=valid_tiers_organisation_id,
        tiers_nom_libre=valid_tiers_nom_libre,
        tiers_concerne=None,
        payeur_origine=(payeur_origine or "").strip() or None,
        motif=(motif or "").strip() or None,
        reference=(reference or "").strip() or None,
        piece_justificative=(piece_justificative or "").strip() or None,
        created_by=created_by,
    )
    db.add(operation)
    await db.flush()
    return operation


async def get_fonds_tiers_locked(
    db: AsyncSession,
    *,
    organisation_id: int,
    operation_id: uuid.UUID,
) -> FondsTiersOperation:
    res = await db.execute(
        select(FondsTiersOperation)
        .where(FondsTiersOperation.id == operation_id, FondsTiersOperation.organisation_id == organisation_id)
        .with_for_update()
    )
    operation = res.scalar_one_or_none()
    if operation is None:
        raise HTTPException(status_code=404, detail="Fonds de tiers introuvable")
    return operation


async def fonds_tiers_amounts(
    db: AsyncSession,
    *,
    organisation_id: int,
    operation: FondsTiersOperation,
) -> tuple[Decimal, str, Decimal, Decimal]:
    enc_res = await db.execute(
        select(Encaissement).where(
            Encaissement.id == operation.encaissement_id,
            Encaissement.organisation_id == organisation_id,
        )
    )
    encaissement = enc_res.scalar_one_or_none()
    if encaissement is None or (encaissement.statut_operation or "ACTIVE").upper() != "ACTIVE":
        montant_recu = Decimal("0.00")
        devise = "USD"
    else:
        montant_recu = _money(encaissement.montant_paye or encaissement.montant_total or encaissement.montant or 0)
        devise = (encaissement.devise_perception or "USD").upper()

    # Une sortie peut solder plusieurs fonds : seule sa part imputée sur
    # celui-ci compte, pas son montant entier.
    remb_res = await db.execute(
        select(func.coalesce(func.sum(SortieFondsTiers.montant), 0))
        .join(SortieFonds, SortieFonds.id == SortieFondsTiers.sortie_fonds_id)
        .where(
            SortieFondsTiers.organisation_id == organisation_id,
            SortieFondsTiers.fonds_tiers_operation_id == operation.id,
            SortieFonds.statut == "VALIDE",
        )
    )
    montant_rembourse = _money(remb_res.scalar_one() or 0)
    solde = max(Decimal("0.00"), montant_recu - montant_rembourse)
    return montant_recu, devise, montant_rembourse, solde


async def refresh_fonds_tiers_status(
    db: AsyncSession,
    *,
    organisation_id: int,
    operation: FondsTiersOperation,
) -> None:
    montant_recu, _devise, montant_rembourse, solde = await fonds_tiers_amounts(
        db,
        organisation_id=organisation_id,
        operation=operation,
    )
    if operation.statut == "ANNULE":
        return
    if montant_recu <= 0:
        operation.statut = "ANNULE"
    elif solde <= 0:
        operation.statut = "REGULARISE"
    elif montant_rembourse > 0:
        operation.statut = "PARTIELLEMENT_REMBOURSE"
    else:
        operation.statut = "OUVERT"
    operation.updated_at = datetime.now(timezone.utc)
    await db.flush()


async def assert_fonds_tiers_refundable(
    db: AsyncSession,
    *,
    organisation_id: int,
    operation_id: uuid.UUID,
    montant: Decimal,
    devise: str,
) -> FondsTiersOperation:
    operation = await get_fonds_tiers_locked(db, organisation_id=organisation_id, operation_id=operation_id)
    if operation.statut == "ANNULE":
        raise HTTPException(status_code=400, detail="Fonds de tiers annulé")
    montant_recu, devise_origine, _rembourse, solde = await fonds_tiers_amounts(
        db,
        organisation_id=organisation_id,
        operation=operation,
    )
    if montant_recu <= 0:
        raise HTTPException(status_code=400, detail="Encaissement d'origine inactif")
    if (devise or "").upper() != devise_origine:
        raise HTTPException(status_code=400, detail="Remboursement dans une devise différente non supporté en V1")
    if _money(montant) > solde:
        raise HTTPException(status_code=400, detail=f"Montant supérieur au solde à rembourser: {solde} {devise_origine}")
    return operation


async def assert_fonds_tiers_origin_can_be_cancelled(
    db: AsyncSession,
    *,
    organisation_id: int,
    encaissement_id: uuid.UUID,
) -> None:
    op_res = await db.execute(
        select(FondsTiersOperation)
        .where(FondsTiersOperation.organisation_id == organisation_id, FondsTiersOperation.encaissement_id == encaissement_id)
        .with_for_update()
    )
    operation = op_res.scalar_one_or_none()
    if operation is None:
        return
    remb_res = await db.execute(
        select(func.count(SortieFondsTiers.id))
        .join(SortieFonds, SortieFonds.id == SortieFondsTiers.sortie_fonds_id)
        .where(
            SortieFondsTiers.organisation_id == organisation_id,
            SortieFondsTiers.fonds_tiers_operation_id == operation.id,
            SortieFonds.statut == "VALIDE",
        )
    )
    if int(remb_res.scalar_one() or 0) > 0:
        raise HTTPException(status_code=409, detail="Annulation refusée: des remboursements fonds de tiers valides existent")
    operation.statut = "ANNULE"
    operation.updated_at = datetime.now(timezone.utc)


async def fonds_tiers_reservations(
    db: AsyncSession,
    *,
    organisation_id: int,
    operation_ids: Sequence[uuid.UUID],
    exclure_requisition_id: uuid.UUID | None = None,
) -> dict[uuid.UUID, tuple[Decimal, list[str]]]:
    """Part de chaque fonds déjà promise par une réquisition en cours.

    Une réquisition non close retient, sur chaque fonds qu'elle nomme, sa part
    moins ce que ses paiements y ont déjà versé (ce versé est, lui, compté dans
    le reversé du fonds). Renvoie le montant retenu et les numéros des
    réquisitions qui le retiennent.
    """
    if not operation_ids:
        return {}
    stmt = (
        select(
            RequisitionFondsTiers.fonds_tiers_operation_id,
            RequisitionFondsTiers.requisition_id,
            RequisitionFondsTiers.montant,
            Requisition.numero_requisition,
        )
        .join(Requisition, Requisition.id == RequisitionFondsTiers.requisition_id)
        .where(
            RequisitionFondsTiers.organisation_id == organisation_id,
            RequisitionFondsTiers.fonds_tiers_operation_id.in_(list(operation_ids)),
            Requisition.is_deleted.is_(False),
            func.upper(func.coalesce(Requisition.status, "")).notin_(STATUTS_REQUISITION_CLOS),
        )
    )
    if exclure_requisition_id is not None:
        stmt = stmt.where(RequisitionFondsTiers.requisition_id != exclure_requisition_id)
    lignes = (await db.execute(stmt)).all()
    if not lignes:
        return {}
    verses = {
        (op_id, req_id): _money(total)
        for op_id, req_id, total in (
            await db.execute(
                select(
                    SortieFondsTiers.fonds_tiers_operation_id,
                    SortieFonds.requisition_id,
                    func.coalesce(func.sum(SortieFondsTiers.montant), 0),
                )
                .join(SortieFonds, SortieFonds.id == SortieFondsTiers.sortie_fonds_id)
                .where(
                    SortieFondsTiers.organisation_id == organisation_id,
                    SortieFondsTiers.fonds_tiers_operation_id.in_(list(operation_ids)),
                    SortieFonds.requisition_id.in_({ligne[1] for ligne in lignes}),
                    SortieFonds.statut == "VALIDE",
                )
                .group_by(SortieFondsTiers.fonds_tiers_operation_id, SortieFonds.requisition_id)
            )
        ).all()
    }
    result: dict[uuid.UUID, tuple[Decimal, list[str]]] = {}
    for op_id, req_id, montant, numero in lignes:
        reste = _money(montant) - verses.get((op_id, req_id), Decimal("0.00"))
        if reste <= 0:
            continue
        total, numeros = result.get(op_id, (Decimal("0.00"), []))
        result[op_id] = (total + reste, [*numeros, numero])
    return result


async def valider_fonds_tiers_requisition(
    db: AsyncSession,
    *,
    organisation_id: int,
    devise: str,
    lignes: Sequence[tuple[uuid.UUID, Decimal]],
    exclure_requisition_id: uuid.UUID | None = None,
) -> list[tuple[uuid.UUID, Decimal]]:
    """Contrôle les fonds qu'une réquisition propose de reverser.

    Chaque fonds doit appartenir au tenant, être encore ouvert, dans la devise
    de la réquisition, et sa part ne pas dépasser ce qui reste à reverser.
    Deux réquisitions concurrentes peuvent viser le même fonds : le solde est
    revérifié, sous verrou, au paiement.
    """
    if not lignes:
        raise HTTPException(status_code=400, detail="Sélectionnez au moins un fonds de tiers à reverser")
    vus: set[uuid.UUID] = set()
    valides: list[tuple[uuid.UUID, Decimal]] = []
    devise = (devise or "USD").upper()
    reservations = await fonds_tiers_reservations(
        db,
        organisation_id=organisation_id,
        operation_ids=[operation_id for operation_id, _montant in lignes],
        exclure_requisition_id=exclure_requisition_id,
    )
    for operation_id, montant in lignes:
        if operation_id in vus:
            raise HTTPException(status_code=400, detail="Un même fonds de tiers est sélectionné deux fois")
        vus.add(operation_id)
        montant = _money(montant)
        if montant <= 0:
            raise HTTPException(status_code=400, detail="Le montant à reverser sur chaque fonds doit être positif")
        operation = await db.scalar(
            select(FondsTiersOperation).where(
                FondsTiersOperation.id == operation_id,
                FondsTiersOperation.organisation_id == organisation_id,
            )
        )
        if operation is None:
            raise HTTPException(status_code=404, detail="Fonds de tiers introuvable")
        if operation.statut in ("ANNULE", "REGULARISE"):
            raise HTTPException(status_code=400, detail="Ce fonds de tiers n'a plus rien à reverser")
        _recu, devise_fonds, _rembourse, solde = await fonds_tiers_amounts(
            db, organisation_id=organisation_id, operation=operation
        )
        if devise_fonds != devise:
            raise HTTPException(
                status_code=400,
                detail=f"Fonds en {devise_fonds} : un versement ne mélange pas les devises ({devise})",
            )
        if montant > solde:
            raise HTTPException(
                status_code=400,
                detail=f"Montant supérieur au solde à reverser sur ce fonds : {solde} {devise_fonds}",
            )
        # Ce qu'une autre réquisition en cours a déjà promis n'est plus
        # disponible : deux pièces approuvées ne se disputeront pas le même
        # argent au guichet.
        reserve, numeros = reservations.get(operation_id, (Decimal("0.00"), []))
        disponible = max(Decimal("0.00"), solde - reserve)
        if montant > disponible:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Fonds déjà retenu par la réquisition {', '.join(numeros)} : "
                    f"disponible {disponible} {devise_fonds}"
                ),
            )
        valides.append((operation_id, montant))
    return valides


async def lignes_fonds_tiers_requisition(
    db: AsyncSession,
    *,
    organisation_id: int,
    requisition_id: uuid.UUID,
) -> list[RequisitionFondsTiers]:
    res = await db.execute(
        select(RequisitionFondsTiers)
        .where(
            RequisitionFondsTiers.organisation_id == organisation_id,
            RequisitionFondsTiers.requisition_id == requisition_id,
        )
        .order_by(RequisitionFondsTiers.created_at, RequisitionFondsTiers.id)
    )
    return list(res.scalars().all())


async def remplacer_fonds_tiers_requisition(
    db: AsyncSession,
    *,
    organisation_id: int,
    requisition_id: uuid.UUID,
    lignes: Sequence[tuple[uuid.UUID, Decimal]],
) -> None:
    for existante in await lignes_fonds_tiers_requisition(
        db, organisation_id=organisation_id, requisition_id=requisition_id
    ):
        await db.delete(existante)
    await db.flush()
    for operation_id, montant in lignes:
        db.add(
            RequisitionFondsTiers(
                organisation_id=organisation_id,
                requisition_id=requisition_id,
                fonds_tiers_operation_id=operation_id,
                montant=_money(montant),
            )
        )
    await db.flush()


async def repartir_versement_fonds_tiers(
    db: AsyncSession,
    *,
    organisation_id: int,
    requisition_id: uuid.UUID,
    montant: Decimal,
    devise: str,
) -> list[tuple[FondsTiersOperation, Decimal]]:
    """Répartit un paiement sur les fonds nommés par la réquisition.

    Les fonds sont servis dans l'ordre où la réquisition les a retenus, chacun
    jusqu'à la plus petite de deux bornes : ce que la réquisition lui destine
    moins ce que ses paiements précédents lui ont déjà versé, et ce qui reste
    réellement à reverser sur le fonds. Un paiement partiel (tranche) remplit
    donc les premiers fonds avant d'entamer les suivants.
    """
    lignes = await lignes_fonds_tiers_requisition(
        db, organisation_id=organisation_id, requisition_id=requisition_id
    )
    if not lignes:
        raise HTTPException(status_code=400, detail="La réquisition ne désigne aucun fonds de tiers")
    reste = _money(montant)
    repartition: list[tuple[FondsTiersOperation, Decimal]] = []
    for ligne in lignes:
        if reste <= 0:
            break
        operation = await get_fonds_tiers_locked(
            db, organisation_id=organisation_id, operation_id=ligne.fonds_tiers_operation_id
        )
        if operation.statut == "ANNULE":
            continue
        _recu, devise_fonds, _rembourse, solde = await fonds_tiers_amounts(
            db, organisation_id=organisation_id, operation=operation
        )
        if devise_fonds != (devise or "").upper():
            raise HTTPException(status_code=400, detail="Remboursement dans une devise différente non supporté en V1")
        deja_verse_par_requisition = _money(
            await db.scalar(
                select(func.coalesce(func.sum(SortieFondsTiers.montant), 0))
                .join(SortieFonds, SortieFonds.id == SortieFondsTiers.sortie_fonds_id)
                .where(
                    SortieFondsTiers.organisation_id == organisation_id,
                    SortieFondsTiers.fonds_tiers_operation_id == operation.id,
                    SortieFonds.requisition_id == requisition_id,
                    SortieFonds.statut == "VALIDE",
                )
            )
        )
        part = min(reste, _money(ligne.montant) - deja_verse_par_requisition, solde)
        if part <= 0:
            continue
        repartition.append((operation, part))
        reste -= part
    if reste > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Montant supérieur au solde à reverser sur les fonds de la réquisition (excédent : {reste} {devise})",
        )
    return repartition


async def enregistrer_versement_fonds_tiers(
    db: AsyncSession,
    *,
    organisation_id: int,
    sortie: SortieFonds,
    repartition: Sequence[tuple[FondsTiersOperation, Decimal]],
) -> None:
    for operation, part in repartition:
        db.add(
            SortieFondsTiers(
                organisation_id=organisation_id,
                sortie_fonds_id=sortie.id,
                fonds_tiers_operation_id=operation.id,
                montant=_money(part),
            )
        )
    await db.flush()
    for operation, _part in repartition:
        await refresh_fonds_tiers_status(db, organisation_id=organisation_id, operation=operation)


async def fonds_tiers_de_sortie(
    db: AsyncSession,
    *,
    organisation_id: int,
    sortie_id: uuid.UUID,
) -> list[uuid.UUID]:
    res = await db.execute(
        select(SortieFondsTiers.fonds_tiers_operation_id).where(
            SortieFondsTiers.organisation_id == organisation_id,
            SortieFondsTiers.sortie_fonds_id == sortie_id,
        )
    )
    return list(res.scalars().all())


async def nom_destinataire_fonds_tiers(db: AsyncSession, requisition: object) -> str:
    """Instance à qui la réquisition fait reverser les fonds.

    Même ordre de confiance que pour le tiers d'un encaissement : le
    référentiel des organisations (hors du scope du tenant, d'où le bypass),
    puis la saisie libre.
    """
    tiers_organisation_id = getattr(requisition, "tiers_organisation_id", None)
    if tiers_organisation_id is not None:
        async with tenant_scope_bypass(db):
            nom = await db.scalar(
                select(Organisation.nom).where(Organisation.id == tiers_organisation_id).limit(1)
            )
        if nom:
            return nom
    return (getattr(requisition, "tiers_nom_libre", None) or "").strip() or TIERS_NON_IDENTIFIE
