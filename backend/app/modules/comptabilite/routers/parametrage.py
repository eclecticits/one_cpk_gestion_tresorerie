"""Paramétrage des mappings comptables.

Le moteur de génération ne contient aucun numéro de compte : il résout chaque
compte via ces trois tables de mapping, et une résolution manquante est un
échec bloquant. Cet écran est donc le point de contrôle avant toute mise en
service réelle du module — et le seul endroit où corriger le mapping par
défaut, volontairement grossier (tous les postes de dépense sur 605).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, has_permission
from app.db.session import get_db
from app.models.budget import BudgetExercice, BudgetPoste
from app.models.compte_bancaire import CompteBancaire
from app.modules.comptabilite.models import (
    RUBRIQUES_DESCRIPTIONS,
    RUBRIQUES_TECHNIQUES,
    ComptaCompte,
    ComptaMappingCompteBancaire,
    ComptaMappingPosteBudgetaire,
    ComptaMappingRubrique,
    ComptaReferentiel,
    ComptaSociete,
)
from app.modules.comptabilite.schemas.parametrage import (
    MappingCompteBancaireOut,
    MappingCompteIn,
    MappingPosteOut,
    MappingRubriqueOut,
    MappingsDefautOut,
    MappingsOut,
)
from app.modules.comptabilite.services.mapping_defaut_service import generer_mappings_par_defaut

router = APIRouter()


async def _societe(db: AsyncSession, tenant_id: int) -> ComptaSociete:
    res = await db.execute(
        select(ComptaSociete).where(
            ComptaSociete.organisation_id == tenant_id, ComptaSociete.is_default.is_(True)
        )
    )
    societe = res.scalar_one_or_none()
    if societe is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Comptabilité non activée pour cette organisation.",
        )
    return societe


async def _valider_compte(db: AsyncSession, tenant_id: int, compte_id: int) -> ComptaCompte:
    """Vérifie qu'un compte est utilisable comme cible de mapping.

    Un compte collectif (401, 411) est refusé : le moteur générerait des
    écritures sans compte auxiliaire, que la validation rejetterait ensuite —
    autant l'interdire au paramétrage, où l'erreur est compréhensible.
    """
    compte = await db.get(ComptaCompte, compte_id)
    if compte is None or compte.organisation_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Compte comptable introuvable.")
    if not compte.actif:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Le compte {compte.numero} est inactif : il ne peut pas être mappé.",
        )
    if compte.is_collectif:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Le compte {compte.numero} est un compte collectif : il exige un compte auxiliaire "
                "à chaque écriture et ne peut pas être mappé directement."
            ),
        )
    return compte


def _compte_fields(compte: ComptaCompte | None) -> dict:
    return {
        "compte_id": compte.id if compte else None,
        "compte_numero": compte.numero if compte else None,
        "compte_libelle": compte.libelle if compte else None,
    }


@router.get("/mappings", response_model=MappingsOut, dependencies=[Depends(has_permission("compta.parametrage"))])
async def list_mappings(
    budget_exercice_id: int | None = None,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> MappingsOut:
    """État complet du paramétrage, mappé ou non.

    Les postes budgétaires sont ceux d'un seul exercice budgétaire (le plus
    récent par défaut) : sur plusieurs années, la liste complète serait
    ingérable, alors que seul l'exercice en cours conditionne les saisies.
    """
    societe = await _societe(db, tenant_id)

    comptes_res = await db.execute(
        select(ComptaCompte)
        .join(ComptaReferentiel, ComptaReferentiel.id == ComptaCompte.referentiel_id)
        .where(ComptaCompte.organisation_id == tenant_id, ComptaReferentiel.is_default.is_(True))
    )
    comptes_by_id = {c.id: c for c in comptes_res.scalars().all()}

    # ── Exercice budgétaire de référence ────────────────────────────────────
    if budget_exercice_id is not None:
        exercice_res = await db.execute(
            select(BudgetExercice).where(
                BudgetExercice.id == budget_exercice_id,
                BudgetExercice.organisation_id == tenant_id,
            )
        )
    else:
        exercice_res = await db.execute(
            select(BudgetExercice)
            .where(BudgetExercice.organisation_id == tenant_id)
            .order_by(BudgetExercice.annee.desc())
            .limit(1)
        )
    budget_exercice = exercice_res.scalar_one_or_none()

    # ── Postes budgétaires ──────────────────────────────────────────────────
    mappings_postes_res = await db.execute(
        select(ComptaMappingPosteBudgetaire).where(
            ComptaMappingPosteBudgetaire.organisation_id == tenant_id
        )
    )
    compte_par_poste = {m.budget_poste_id: m.compte_id for m in mappings_postes_res.scalars().all()}

    postes: list[MappingPosteOut] = []
    if budget_exercice is not None:
        postes_res = await db.execute(
            select(BudgetPoste)
            .where(
                BudgetPoste.organisation_id == tenant_id,
                BudgetPoste.exercice_id == budget_exercice.id,
                BudgetPoste.is_deleted.is_(False),
                BudgetPoste.active.is_(True),
            )
            .order_by(BudgetPoste.code)
        )
        for poste in postes_res.scalars().all():
            compte = comptes_by_id.get(compte_par_poste.get(poste.id))
            postes.append(
                MappingPosteOut(
                    budget_poste_id=poste.id,
                    code=poste.code,
                    libelle=poste.libelle,
                    type=poste.type,
                    **_compte_fields(compte),
                )
            )

    # ── Comptes de trésorerie ───────────────────────────────────────────────
    mappings_cb_res = await db.execute(
        select(ComptaMappingCompteBancaire).where(
            ComptaMappingCompteBancaire.organisation_id == tenant_id
        )
    )
    compte_par_banque = {m.compte_bancaire_id: m.compte_id for m in mappings_cb_res.scalars().all()}

    banques_res = await db.execute(
        select(CompteBancaire)
        .where(CompteBancaire.organisation_id == tenant_id, CompteBancaire.is_active.is_(True))
        .order_by(CompteBancaire.intitule)
    )
    comptes_bancaires = [
        MappingCompteBancaireOut(
            compte_bancaire_id=banque.id,
            intitule=banque.intitule,
            numero_compte=banque.numero_compte,
            account_type=banque.account_type,
            devise=banque.devise,
            **_compte_fields(comptes_by_id.get(compte_par_banque.get(banque.id))),
        )
        for banque in banques_res.scalars().all()
    ]

    # ── Rubriques techniques ────────────────────────────────────────────────
    mappings_rub_res = await db.execute(
        select(ComptaMappingRubrique).where(ComptaMappingRubrique.organisation_id == tenant_id)
    )
    compte_par_rubrique = {m.code_rubrique: m.compte_id for m in mappings_rub_res.scalars().all()}

    rubriques: list[MappingRubriqueOut] = []
    for code in RUBRIQUES_TECHNIQUES:
        libelle, description = RUBRIQUES_DESCRIPTIONS[code]
        rubriques.append(
            MappingRubriqueOut(
                code_rubrique=code,
                libelle=libelle,
                description=description,
                **_compte_fields(comptes_by_id.get(compte_par_rubrique.get(code))),
            )
        )

    caisse_defaut = comptes_by_id.get(societe.compte_caisse_defaut_id)
    nb_non_mappes = (
        sum(1 for p in postes if p.compte_id is None)
        + sum(1 for c in comptes_bancaires if c.compte_id is None)
        + sum(1 for r in rubriques if r.compte_id is None)
        + (1 if caisse_defaut is None else 0)
    )

    return MappingsOut(
        budget_exercice_id=budget_exercice.id if budget_exercice else None,
        budget_exercice_annee=budget_exercice.annee if budget_exercice else None,
        caisse_defaut_compte_id=caisse_defaut.id if caisse_defaut else None,
        caisse_defaut_compte_numero=caisse_defaut.numero if caisse_defaut else None,
        caisse_defaut_compte_libelle=caisse_defaut.libelle if caisse_defaut else None,
        postes=postes,
        comptes_bancaires=comptes_bancaires,
        rubriques=rubriques,
        nb_non_mappes=nb_non_mappes,
    )


@router.put(
    "/mappings/poste/{budget_poste_id}",
    response_model=MappingPosteOut,
    dependencies=[Depends(has_permission("compta.parametrage"))],
)
async def set_mapping_poste(
    budget_poste_id: int,
    payload: MappingCompteIn,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> MappingPosteOut:
    await _societe(db, tenant_id)
    compte = await _valider_compte(db, tenant_id, payload.compte_id)

    poste_res = await db.execute(
        select(BudgetPoste).where(
            BudgetPoste.id == budget_poste_id,
            BudgetPoste.organisation_id == tenant_id,
            BudgetPoste.is_deleted.is_(False),
        )
    )
    poste = poste_res.scalar_one_or_none()
    if poste is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Poste budgétaire introuvable.")

    res = await db.execute(
        select(ComptaMappingPosteBudgetaire).where(
            ComptaMappingPosteBudgetaire.organisation_id == tenant_id,
            ComptaMappingPosteBudgetaire.budget_poste_id == budget_poste_id,
        )
    )
    mapping = res.scalar_one_or_none()
    if mapping is None:
        db.add(
            ComptaMappingPosteBudgetaire(
                organisation_id=tenant_id, budget_poste_id=budget_poste_id, compte_id=compte.id
            )
        )
    else:
        mapping.compte_id = compte.id
    await db.commit()

    return MappingPosteOut(
        budget_poste_id=poste.id,
        code=poste.code,
        libelle=poste.libelle,
        type=poste.type,
        **_compte_fields(compte),
    )


@router.put(
    "/mappings/compte-bancaire/{compte_bancaire_id}",
    response_model=MappingCompteBancaireOut,
    dependencies=[Depends(has_permission("compta.parametrage"))],
)
async def set_mapping_compte_bancaire(
    compte_bancaire_id: int,
    payload: MappingCompteIn,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> MappingCompteBancaireOut:
    await _societe(db, tenant_id)
    compte = await _valider_compte(db, tenant_id, payload.compte_id)

    banque_res = await db.execute(
        select(CompteBancaire).where(
            CompteBancaire.id == compte_bancaire_id,
            CompteBancaire.organisation_id == tenant_id,
        )
    )
    banque = banque_res.scalar_one_or_none()
    if banque is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Compte de trésorerie introuvable.")

    res = await db.execute(
        select(ComptaMappingCompteBancaire).where(
            ComptaMappingCompteBancaire.organisation_id == tenant_id,
            ComptaMappingCompteBancaire.compte_bancaire_id == compte_bancaire_id,
        )
    )
    mapping = res.scalar_one_or_none()
    if mapping is None:
        db.add(
            ComptaMappingCompteBancaire(
                organisation_id=tenant_id, compte_bancaire_id=compte_bancaire_id, compte_id=compte.id
            )
        )
    else:
        mapping.compte_id = compte.id
    await db.commit()

    return MappingCompteBancaireOut(
        compte_bancaire_id=banque.id,
        intitule=banque.intitule,
        numero_compte=banque.numero_compte,
        account_type=banque.account_type,
        devise=banque.devise,
        **_compte_fields(compte),
    )


@router.put(
    "/mappings/rubrique/{code_rubrique}",
    response_model=MappingRubriqueOut,
    dependencies=[Depends(has_permission("compta.parametrage"))],
)
async def set_mapping_rubrique(
    code_rubrique: str,
    payload: MappingCompteIn,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> MappingRubriqueOut:
    await _societe(db, tenant_id)
    if code_rubrique not in RUBRIQUES_TECHNIQUES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Rubrique inconnue : {code_rubrique}"
        )
    compte = await _valider_compte(db, tenant_id, payload.compte_id)

    res = await db.execute(
        select(ComptaMappingRubrique).where(
            ComptaMappingRubrique.organisation_id == tenant_id,
            ComptaMappingRubrique.code_rubrique == code_rubrique,
        )
    )
    mapping = res.scalar_one_or_none()
    if mapping is None:
        db.add(
            ComptaMappingRubrique(
                organisation_id=tenant_id, code_rubrique=code_rubrique, compte_id=compte.id
            )
        )
    else:
        mapping.compte_id = compte.id
    await db.commit()

    libelle, description = RUBRIQUES_DESCRIPTIONS[code_rubrique]
    return MappingRubriqueOut(
        code_rubrique=code_rubrique,
        libelle=libelle,
        description=description,
        **_compte_fields(compte),
    )


@router.put(
    "/mappings/caisse-defaut",
    response_model=MappingsDefautOut,
    dependencies=[Depends(has_permission("compta.parametrage"))],
)
async def set_caisse_defaut(
    payload: MappingCompteIn,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> MappingsDefautOut:
    """Compte de la caisse unique (`CaisseCentrale`), qui n'a pas de ligne
    `CompteBancaire` à mapper — il est porté par la société."""
    societe = await _societe(db, tenant_id)
    compte = await _valider_compte(db, tenant_id, payload.compte_id)
    societe.compte_caisse_defaut_id = compte.id
    await db.commit()
    return MappingsDefautOut(
        postes_mappes=0, comptes_bancaires_mappes=0, rubriques_mappees=0,
        compte_caisse_defaut_id=compte.id,
    )


@router.post(
    "/mappings/defaut",
    response_model=MappingsDefautOut,
    dependencies=[Depends(has_permission("compta.parametrage"))],
)
async def appliquer_mappings_defaut(
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> MappingsDefautOut:
    """Complète les mappings manquants par des comptes génériques.

    Ne touche jamais un mapping déjà configuré : sert à débloquer rapidement,
    pas à écraser un paramétrage affiné.
    """
    try:
        resume = await generer_mappings_par_defaut(db, organisation_id=tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return MappingsDefautOut(**resume)
