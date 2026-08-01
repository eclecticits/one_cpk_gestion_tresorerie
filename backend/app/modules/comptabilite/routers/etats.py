"""API des états financiers et de la clôture d'exercice (Lot 5)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, has_any_permission, has_permission
from app.db.session import get_db
from app.models.user import User
from app.modules.comptabilite.models import TYPES_ETAT, ComptaExercice
from app.modules.comptabilite.routers.restitutions import LECTURE_COMPTA
from app.modules.comptabilite.schemas.etats import (
    ANouveauxIn,
    ANouveauxOut,
    ClotureOut,
    ControleBilanOut,
    DeterminationResultatOut,
    EtatOut,
    LigneEtatOut,
)
from app.modules.comptabilite.services.cloture_service import (
    ClotureError,
    cloturer_exercice,
    determiner_resultat,
    reporter_a_nouveaux,
)
from app.modules.comptabilite.services.etats_financiers import calculer_etat, controler_bilan

router = APIRouter()


async def _exercice(db: AsyncSession, tenant_id: int, exercice_id: int | None) -> ComptaExercice:
    stmt = select(ComptaExercice).where(ComptaExercice.organisation_id == tenant_id)
    if exercice_id is not None:
        stmt = stmt.where(ComptaExercice.id == exercice_id)
    else:
        stmt = stmt.order_by(ComptaExercice.date_debut.desc()).limit(1)
    res = await db.execute(stmt)
    exercice = res.scalar_one_or_none()
    if exercice is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aucun exercice comptable pour cette organisation.",
        )
    return exercice


@router.get(
    "/etats/{type_etat}", response_model=EtatOut, dependencies=[Depends(has_any_permission(LECTURE_COMPTA))]
)
async def get_etat(
    type_etat: str,
    exercice_id: int | None = None,
    date_arrete: date | None = None,
    inclure_brouillons: bool = False,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> EtatOut:
    if type_etat not in TYPES_ETAT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"État inconnu : {type_etat}. Attendu : {', '.join(TYPES_ETAT)}.",
        )
    exercice = await _exercice(db, tenant_id, exercice_id)
    try:
        etat = await calculer_etat(
            db,
            organisation_id=tenant_id,
            exercice_id=exercice.id,
            type_etat=type_etat,
            date_arrete=date_arrete,
            inclure_brouillons=inclure_brouillons,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return EtatOut(
        type_etat=etat.type_etat,
        exercice_id=exercice.id,
        exercice_code=exercice.code,
        devise_tenue=etat.devise_tenue,
        date_arrete=etat.date_arrete,
        inclure_brouillons=etat.inclure_brouillons,
        lignes=[
            LigneEtatOut(
                poste_id=l.poste_id, code=l.code, libelle=l.libelle, niveau=l.niveau,
                est_total=l.est_total, sens_normal=l.sens_normal,
                brut=l.brut, amortissement=l.amortissement, net=l.net,
            )
            for l in etat.lignes
        ],
        total=etat.total,
        comptes_non_couverts=etat.comptes_non_couverts,
    )


@router.get(
    "/etats-controle/bilan",
    response_model=ControleBilanOut,
    dependencies=[Depends(has_any_permission(LECTURE_COMPTA))],
)
async def get_controle_bilan(
    exercice_id: int | None = None,
    date_arrete: date | None = None,
    inclure_brouillons: bool = False,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ControleBilanOut:
    exercice = await _exercice(db, tenant_id, exercice_id)
    try:
        controle = await controler_bilan(
            db, organisation_id=tenant_id, exercice_id=exercice.id,
            date_arrete=date_arrete, inclure_brouillons=inclure_brouillons,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ControleBilanOut(
        total_actif=controle.total_actif,
        total_passif=controle.total_passif,
        ecart=controle.ecart,
        equilibre=controle.equilibre,
        comptes_non_couverts=controle.comptes_non_couverts,
    )


# ── Clôture ──────────────────────────────────────────────────────────────────


@router.post(
    "/exercices/{exercice_id}/determiner-resultat",
    response_model=DeterminationResultatOut,
    dependencies=[Depends(has_permission("compta.cloture"))],
)
async def post_determiner_resultat(
    exercice_id: int,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> DeterminationResultatOut:
    try:
        resume = await determiner_resultat(
            db, organisation_id=tenant_id, exercice_id=exercice_id, user_id=user.id
        )
    except ClotureError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return DeterminationResultatOut(**resume)


@router.post(
    "/exercices/{exercice_id}/cloturer",
    response_model=ClotureOut,
    dependencies=[Depends(has_permission("compta.cloture"))],
)
async def post_cloturer(
    exercice_id: int,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ClotureOut:
    try:
        resume = await cloturer_exercice(
            db, organisation_id=tenant_id, exercice_id=exercice_id, user_id=user.id
        )
    except ClotureError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return ClotureOut(**resume)


@router.post(
    "/exercices/{exercice_id}/a-nouveaux",
    response_model=ANouveauxOut,
    dependencies=[Depends(has_permission("compta.cloture"))],
)
async def post_a_nouveaux(
    exercice_id: int,
    payload: ANouveauxIn,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ANouveauxOut:
    try:
        resume = await reporter_a_nouveaux(
            db,
            organisation_id=tenant_id,
            exercice_id=exercice_id,
            exercice_suivant_id=payload.exercice_suivant_id,
            user_id=user.id,
        )
    except ClotureError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return ANouveauxOut(**resume)
