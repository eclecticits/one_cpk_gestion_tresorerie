"""API du lettrage des comptes de tiers.

Branchement HTTP de `lettrage_service` : contrôle d'accès et conversion en
schémas. Les règles (groupe soldé, écritures validées, même tiers) vivent dans
le service.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, has_any_permission, has_permission
from app.db.session import get_db
from app.models.user import User
from app.modules.comptabilite.models import ComptaCompte
from app.modules.comptabilite.schemas.ecritures import CompteOut
from app.modules.comptabilite.schemas.lettrage import (
    BalanceAgeeOut,
    CompteALettrerOut,
    LigneBalanceAgeeOut,
    CompteLettrableIn,
    DelettrerIn,
    GroupeProposeOut,
    LettrageAutoIn,
    LettrageAutoOut,
    LettrageOut,
    LettrerIn,
    LigneLettrableOut,
    LignesCompteOut,
)
from app.modules.comptabilite.services.balance_agee_service import balance_agee
from app.modules.comptabilite.services.lettrage_service import (
    LettrageRefuse,
    LigneLettrable,
    comptes_a_lettrer,
    definir_lettrable,
    delettrer,
    lettrage_automatique,
    lettrer,
    lignes_du_compte,
)

router = APIRouter()

LECTURE_COMPTA = [
    "compta.lecture", "compta.saisie", "compta.validation", "compta.cloture",
    "compta.parametrage", "compta.export",
]
# Lettrer est un pointage : il revient à qui saisit ou valide les écritures.
LETTRAGE = ["compta.saisie", "compta.validation"]

# Au-delà, l'aperçu d'un lettrage automatique deviendrait illisible ; le
# traitement, lui, porte toujours sur tous les groupes trouvés.
APERCU_GROUPES_MAX = 300


def _ligne_out(ligne: LigneLettrable) -> LigneLettrableOut:
    return LigneLettrableOut(
        ligne_id=ligne.ligne_id,
        ecriture_id=ligne.ecriture_id,
        numero=ligne.numero,
        date_ecriture=ligne.date_ecriture,
        journal_code=ligne.journal_code,
        libelle=ligne.libelle,
        reference_piece=ligne.reference_piece,
        debit=ligne.debit,
        credit=ligne.credit,
        compte_auxiliaire_id=ligne.compte_auxiliaire_id,
        lettrage=ligne.lettrage,
        date_lettrage=ligne.date_lettrage,
    )


def _refus(exc: LettrageRefuse) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get(
    "/lettrage/comptes",
    response_model=list[CompteALettrerOut],
    dependencies=[Depends(has_any_permission(LECTURE_COMPTA))],
)
async def get_comptes_a_lettrer(
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[CompteALettrerOut]:
    return [
        CompteALettrerOut(
            compte_id=c.compte_id,
            numero=c.numero,
            libelle=c.libelle,
            lignes_non_lettrees=c.lignes_non_lettrees,
            debit_non_lettre=c.debit_non_lettre,
            credit_non_lettre=c.credit_non_lettre,
            solde_non_lettre=c.solde_non_lettre,
        )
        for c in await comptes_a_lettrer(db, organisation_id=tenant_id)
    ]


@router.get(
    "/lettrage/lignes",
    response_model=LignesCompteOut,
    dependencies=[Depends(has_any_permission(LECTURE_COMPTA))],
)
async def get_lignes_du_compte(
    compte_id: int,
    inclure_lettrees: bool = False,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> LignesCompteOut:
    compte = await db.get(ComptaCompte, compte_id)
    if compte is None or compte.organisation_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Compte comptable introuvable.")
    lignes = await lignes_du_compte(
        db, organisation_id=tenant_id, compte_id=compte_id, inclure_lettrees=inclure_lettrees
    )
    debit = sum((l.debit for l in lignes if not l.lettrage), Decimal("0"))
    credit = sum((l.credit for l in lignes if not l.lettrage), Decimal("0"))
    return LignesCompteOut(
        compte_id=compte.id,
        compte_numero=compte.numero,
        compte_libelle=compte.libelle,
        lignes=[_ligne_out(l) for l in lignes],
        debit_non_lettre=debit,
        credit_non_lettre=credit,
        solde_non_lettre=debit - credit,
    )


@router.post(
    "/lettrage",
    response_model=LettrageOut,
    dependencies=[Depends(has_any_permission(LETTRAGE))],
)
async def post_lettrer(
    payload: LettrerIn,
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LettrageOut:
    try:
        code = await lettrer(db, organisation_id=tenant_id, ligne_ids=payload.ligne_ids, user_id=user.id)
    except LettrageRefuse as exc:
        raise _refus(exc) from exc
    await db.commit()
    return LettrageOut(code=code, lignes=len(set(payload.ligne_ids)))


@router.post(
    "/lettrage/delettrer",
    response_model=LettrageOut,
    dependencies=[Depends(has_any_permission(LETTRAGE))],
)
async def post_delettrer(
    payload: DelettrerIn,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> LettrageOut:
    try:
        lignes = await delettrer(
            db, organisation_id=tenant_id, compte_id=payload.compte_id, code=payload.code.strip().upper()
        )
    except LettrageRefuse as exc:
        raise _refus(exc) from exc
    await db.commit()
    return LettrageOut(code=payload.code.strip().upper(), lignes=lignes)


@router.post(
    "/lettrage/automatique",
    response_model=LettrageAutoOut,
    dependencies=[Depends(has_any_permission(LETTRAGE))],
)
async def post_lettrage_automatique(
    payload: LettrageAutoIn,
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LettrageAutoOut:
    """Rapproche ce qui l'est sans ambiguïté. `simulation` vaut True par défaut."""
    try:
        rapport = await lettrage_automatique(
            db,
            organisation_id=tenant_id,
            compte_id=payload.compte_id,
            simulation=payload.simulation,
            user_id=user.id,
        )
    except LettrageRefuse as exc:
        raise _refus(exc) from exc
    if not payload.simulation:
        await db.commit()
    return LettrageAutoOut(
        simulation=rapport.simulation,
        comptes_examines=rapport.comptes_examines,
        groupes_lettres=len(rapport.groupes),
        lignes_lettrees=rapport.lignes_lettrees,
        groupes=[
            GroupeProposeOut(
                compte_id=g.compte_id,
                compte_numero=g.compte_numero,
                motif=g.motif,
                montant=g.montant,
                code=g.code,
                lignes=[_ligne_out(l) for l in g.lignes],
            )
            for g in rapport.groupes[:APERCU_GROUPES_MAX]
        ],
    )


@router.put(
    "/comptes/{compte_id}/lettrable",
    response_model=CompteOut,
    dependencies=[Depends(has_permission("compta.parametrage"))],
)
async def put_compte_lettrable(
    compte_id: int,
    payload: CompteLettrableIn,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> CompteOut:
    try:
        compte = await definir_lettrable(
            db, organisation_id=tenant_id, compte_id=compte_id, lettrable=payload.lettrable
        )
    except LettrageRefuse as exc:
        raise _refus(exc) from exc
    await db.commit()
    await db.refresh(compte)
    return CompteOut.model_validate(compte)


@router.get(
    "/balance-agee",
    response_model=BalanceAgeeOut,
    dependencies=[Depends(has_any_permission(LECTURE_COMPTA))],
)
async def get_balance_agee(
    date_arret: date | None = None,
    sens: Literal["CREANCES", "DETTES"] = "CREANCES",
    prefixe: str | None = Query(default=None, max_length=30, pattern=r"^[0-9A-Za-z]*$"),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> BalanceAgeeOut:
    """Reste dû par compte de tiers, par tranche d'ancienneté, à la date d'arrêt."""
    balance = await balance_agee(
        db,
        organisation_id=tenant_id,
        date_arret=date_arret or datetime.now(timezone.utc).date(),
        sens=sens,
        prefixe=prefixe or None,
    )
    return BalanceAgeeOut(
        date_arret=balance.date_arret,
        sens=balance.sens,
        lignes=[
            LigneBalanceAgeeOut(
                compte_id=l.compte_id,
                compte_numero=l.compte_numero,
                compte_libelle=l.compte_libelle,
                lignes=l.lignes,
                plus_ancienne=l.plus_ancienne,
                solde=l.solde,
                **l.tranches,
            )
            for l in balance.lignes
        ],
        total=balance.total,
        **balance.totaux,
    )
