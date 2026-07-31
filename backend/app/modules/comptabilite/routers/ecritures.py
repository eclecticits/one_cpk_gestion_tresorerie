"""API minimale du module Comptabilité (chemin viable Lot 1).

Expose les services déjà écrits (numérotation, validation, contre-passation,
plans de démarrage, provisioning) : pas de logique métier nouvelle ici, juste
le branchement HTTP + permissions.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_tenant_id, get_current_user, has_any_permission, has_permission
from app.db.session import get_db
from app.models.organisation import Organisation
from app.models.user import User
from app.modules.comptabilite.models import (
    ComptaCompte,
    ComptaEcriture,
    ComptaJournal,
    ComptaLigneEcriture,
    ComptaReferentiel,
    ComptaSociete,
)
from app.modules.comptabilite.schemas.ecritures import (
    CompteOut,
    ContrepasserIn,
    EcritureCreateIn,
    EcritureListOut,
    EcritureOut,
    ExerciceOut,
    JournalOut,
    LigneEcritureOut,
    SetupComptabiliteIn,
    SetupComptabiliteOut,
)
from app.modules.comptabilite.services.ecriture_service import (
    contrepasser_ecriture,
    valider_ecriture,
)
from app.modules.comptabilite.services.setup_service import setup_comptabilite

router = APIRouter()

ANY_COMPTA_PERMISSION = [
    "compta.saisie", "compta.validation", "compta.cloture", "compta.parametrage", "compta.lecture", "compta.export",
]


def _ecriture_to_out(ecriture: ComptaEcriture, comptes_by_id: dict[int, ComptaCompte] | None = None) -> EcritureOut:
    comptes_by_id = comptes_by_id or {}
    lignes_out = [
        LigneEcritureOut(
            id=l.id,
            compte_id=l.compte_id,
            compte_numero=comptes_by_id.get(l.compte_id).numero if comptes_by_id.get(l.compte_id) else None,
            compte_libelle=comptes_by_id.get(l.compte_id).libelle if comptes_by_id.get(l.compte_id) else None,
            compte_auxiliaire_id=l.compte_auxiliaire_id,
            libelle=l.libelle,
            debit=l.debit,
            credit=l.credit,
            devise=l.devise,
        )
        for l in sorted(ecriture.lignes or [], key=lambda x: x.ordre)
    ]
    return EcritureOut(
        id=ecriture.id,
        numero=ecriture.numero,
        journal_id=ecriture.journal_id,
        exercice_id=ecriture.exercice_id,
        date_ecriture=ecriture.date_ecriture,
        date_piece=ecriture.date_piece,
        reference_piece=ecriture.reference_piece,
        libelle=ecriture.libelle,
        statut=ecriture.statut,
        devise=ecriture.devise,
        module_origine=ecriture.module_origine,
        est_automatique=ecriture.est_automatique,
        valide_par=ecriture.valide_par,
        valide_le=ecriture.valide_le,
        contrepasse_ecriture_id=ecriture.contrepasse_ecriture_id,
        motif_annulation=ecriture.motif_annulation,
        created_at=ecriture.created_at,
        lignes=lignes_out,
    )


# ── Provisioning ──────────────────────────────────────────────────────────────


@router.post("/setup", response_model=SetupComptabiliteOut, dependencies=[Depends(has_permission("compta.parametrage"))])
async def setup(
    payload: SetupComptabiliteIn,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> SetupComptabiliteOut:
    org_res = await db.execute(select(Organisation.nom).where(Organisation.id == tenant_id))
    org_nom = org_res.scalar_one_or_none() or "Organisation"

    result = await setup_comptabilite(
        db,
        organisation_id=tenant_id,
        organisation_nom=org_nom,
        type_referentiel=payload.type_referentiel,
        exercice_date_debut=payload.exercice_date_debut,
        exercice_date_fin=payload.exercice_date_fin,
    )
    await db.commit()
    return SetupComptabiliteOut(**result)


@router.get("/statut", dependencies=[Depends(has_any_permission(ANY_COMPTA_PERMISSION))])
async def statut(
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    res = await db.execute(
        select(ComptaSociete).where(
            ComptaSociete.organisation_id == tenant_id, ComptaSociete.is_default.is_(True)
        )
    )
    societe = res.scalar_one_or_none()
    return {"provisionne": societe is not None, "societe_id": societe.id if societe else None}


# ── Référentiel (lecture) ────────────────────────────────────────────────────


@router.get("/comptes", response_model=list[CompteOut], dependencies=[Depends(has_any_permission(ANY_COMPTA_PERMISSION))])
async def list_comptes(
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[CompteOut]:
    res = await db.execute(
        select(ComptaCompte)
        .join(ComptaReferentiel, ComptaReferentiel.id == ComptaCompte.referentiel_id)
        .where(ComptaCompte.organisation_id == tenant_id, ComptaReferentiel.is_default.is_(True))
        .order_by(ComptaCompte.numero)
    )
    return list(res.scalars().all())


@router.get("/journaux", response_model=list[JournalOut], dependencies=[Depends(has_any_permission(ANY_COMPTA_PERMISSION))])
async def list_journaux(
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[JournalOut]:
    res = await db.execute(
        select(ComptaJournal)
        .where(ComptaJournal.organisation_id == tenant_id, ComptaJournal.actif.is_(True))
        .order_by(ComptaJournal.code)
    )
    return list(res.scalars().all())


@router.get("/exercices", dependencies=[Depends(has_any_permission(ANY_COMPTA_PERMISSION))])
async def list_exercices(
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[ExerciceOut]:
    from app.modules.comptabilite.models import ComptaExercice

    res = await db.execute(
        select(ComptaExercice)
        .where(ComptaExercice.organisation_id == tenant_id)
        .order_by(ComptaExercice.code.desc())
    )
    return list(res.scalars().all())


# ── Écritures ────────────────────────────────────────────────────────────────


@router.get("/ecritures", response_model=EcritureListOut, dependencies=[Depends(has_any_permission(ANY_COMPTA_PERMISSION))])
async def list_ecritures(
    statut: str | None = None,
    journal_id: int | None = None,
    exercice_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> EcritureListOut:
    stmt = select(ComptaEcriture).where(ComptaEcriture.organisation_id == tenant_id)
    count_stmt = select(func.count()).select_from(ComptaEcriture).where(ComptaEcriture.organisation_id == tenant_id)
    if statut:
        stmt = stmt.where(ComptaEcriture.statut == statut)
        count_stmt = count_stmt.where(ComptaEcriture.statut == statut)
    if journal_id:
        stmt = stmt.where(ComptaEcriture.journal_id == journal_id)
        count_stmt = count_stmt.where(ComptaEcriture.journal_id == journal_id)
    if exercice_id:
        stmt = stmt.where(ComptaEcriture.exercice_id == exercice_id)
        count_stmt = count_stmt.where(ComptaEcriture.exercice_id == exercice_id)

    stmt = stmt.options(selectinload(ComptaEcriture.lignes)).order_by(
        ComptaEcriture.date_ecriture.desc(), ComptaEcriture.created_at.desc()
    ).limit(limit).offset(offset)

    total = (await db.execute(count_stmt)).scalar_one()
    res = await db.execute(stmt)
    ecritures = list(res.scalars().unique().all())

    compte_ids = {l.compte_id for e in ecritures for l in (e.lignes or [])}
    comptes_by_id: dict[int, ComptaCompte] = {}
    if compte_ids:
        cpt_res = await db.execute(select(ComptaCompte).where(ComptaCompte.id.in_(compte_ids)))
        comptes_by_id = {c.id: c for c in cpt_res.scalars().all()}

    return EcritureListOut(
        items=[_ecriture_to_out(e, comptes_by_id) for e in ecritures],
        total=total,
    )


@router.get("/ecritures/{ecriture_id}", response_model=EcritureOut, dependencies=[Depends(has_any_permission(ANY_COMPTA_PERMISSION))])
async def get_ecriture(
    ecriture_id: UUID,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> EcritureOut:
    res = await db.execute(
        select(ComptaEcriture)
        .options(selectinload(ComptaEcriture.lignes))
        .where(ComptaEcriture.id == ecriture_id, ComptaEcriture.organisation_id == tenant_id)
    )
    ecriture = res.scalar_one_or_none()
    if ecriture is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Écriture introuvable")

    compte_ids = {l.compte_id for l in (ecriture.lignes or [])}
    comptes_by_id: dict[int, ComptaCompte] = {}
    if compte_ids:
        cpt_res = await db.execute(select(ComptaCompte).where(ComptaCompte.id.in_(compte_ids)))
        comptes_by_id = {c.id: c for c in cpt_res.scalars().all()}

    return _ecriture_to_out(ecriture, comptes_by_id)


@router.post("/ecritures", response_model=EcritureOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(has_permission("compta.saisie"))])
async def create_ecriture(
    payload: EcritureCreateIn,
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EcritureOut:
    journal_res = await db.execute(
        select(ComptaJournal).where(ComptaJournal.id == payload.journal_id, ComptaJournal.organisation_id == tenant_id)
    )
    journal = journal_res.scalar_one_or_none()
    if journal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Journal introuvable")

    from app.modules.comptabilite.models import ComptaExercice

    exercice_res = await db.execute(
        select(ComptaExercice).where(
            ComptaExercice.id == payload.exercice_id, ComptaExercice.organisation_id == tenant_id
        )
    )
    exercice = exercice_res.scalar_one_or_none()
    if exercice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exercice introuvable")
    if journal.societe_id != exercice.societe_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Journal et exercice appartiennent à des sociétés différentes.")

    ecriture = ComptaEcriture(
        organisation_id=tenant_id,
        societe_id=journal.societe_id,
        exercice_id=exercice.id,
        journal_id=journal.id,
        numero=None,
        date_ecriture=payload.date_ecriture,
        date_piece=payload.date_piece,
        reference_piece=payload.reference_piece,
        libelle=payload.libelle,
        statut="BROUILLON",
        devise=payload.devise,
        created_by=user.id,
    )
    db.add(ecriture)
    await db.flush()

    for ordre, ligne_in in enumerate(payload.lignes, start=1):
        db.add(
            ComptaLigneEcriture(
                organisation_id=tenant_id,
                societe_id=journal.societe_id,
                ecriture_id=ecriture.id,
                compte_id=ligne_in.compte_id,
                compte_auxiliaire_id=ligne_in.compte_auxiliaire_id,
                ordre=ordre,
                libelle=ligne_in.libelle,
                debit=ligne_in.debit,
                credit=ligne_in.credit,
                devise=payload.devise,
                debit_tenue=ligne_in.debit,
                credit_tenue=ligne_in.credit,
            )
        )
    await db.flush()
    await db.commit()
    await db.refresh(ecriture, attribute_names=["lignes"])

    compte_ids = {l.compte_id for l in ecriture.lignes}
    cpt_res = await db.execute(select(ComptaCompte).where(ComptaCompte.id.in_(compte_ids)))
    comptes_by_id = {c.id: c for c in cpt_res.scalars().all()}

    return _ecriture_to_out(ecriture, comptes_by_id)


@router.post("/ecritures/{ecriture_id}/valider", response_model=EcritureOut, dependencies=[Depends(has_permission("compta.validation"))])
async def valider(
    ecriture_id: UUID,
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EcritureOut:
    ecriture = await valider_ecriture(db, ecriture_id=ecriture_id, organisation_id=tenant_id, user_id=user.id)
    await db.commit()
    await db.refresh(ecriture, attribute_names=["lignes"])

    compte_ids = {l.compte_id for l in ecriture.lignes}
    cpt_res = await db.execute(select(ComptaCompte).where(ComptaCompte.id.in_(compte_ids)))
    comptes_by_id = {c.id: c for c in cpt_res.scalars().all()}
    return _ecriture_to_out(ecriture, comptes_by_id)


@router.post("/ecritures/{ecriture_id}/contrepasser", response_model=EcritureOut, dependencies=[Depends(has_permission("compta.validation"))])
async def contrepasser(
    ecriture_id: UUID,
    payload: ContrepasserIn,
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EcritureOut:
    inverse = await contrepasser_ecriture(
        db, ecriture_id=ecriture_id, organisation_id=tenant_id, user_id=user.id, motif=payload.motif,
    )
    await db.commit()
    await db.refresh(inverse, attribute_names=["lignes"])

    compte_ids = {l.compte_id for l in inverse.lignes}
    cpt_res = await db.execute(select(ComptaCompte).where(ComptaCompte.id.in_(compte_ids)))
    comptes_by_id = {c.id: c for c in cpt_res.scalars().all()}
    return _ecriture_to_out(inverse, comptes_by_id)
