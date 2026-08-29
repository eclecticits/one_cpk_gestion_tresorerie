"""Paramétrage des mappings comptables.

Le moteur de génération ne contient aucun numéro de compte : il résout chaque
compte via ces trois tables de mapping, et une résolution manquante est un
échec bloquant. Cet écran est donc le point de contrôle avant toute mise en
service réelle du module — et le seul endroit où corriger le mapping par
défaut, volontairement grossier (tous les postes de dépense sur 605).
"""

from __future__ import annotations

from decimal import Decimal

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
    ComptaExercice,
    ComptaReferentiel,
    ComptaSociete,
    ComptaTauxChange,
)
from app.modules.comptabilite.schemas.parametrage import (
    MappingCompteBancaireOut,
    MappingCompteIn,
    MappingPosteOut,
    MappingRubriqueOut,
    MappingsDefautOut,
    MappingsOut,
    TauxChangeIn,
    TauxChangeListOut,
    TauxChangeManquantOut,
    TauxChangeOut,
)
from app.modules.comptabilite.services.change_service import taux_tresorerie_vers_comptable
from app.modules.comptabilite.services.mapping_defaut_service import generer_mappings_par_defaut
from app.utils.budget_code import cle_tri_code_budget

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
        for poste in sorted(postes_res.scalars().all(), key=lambda item: cle_tri_code_budget(item.code)):
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


# ── Taux de change comptables ────────────────────────────────────────────────
#
# Distincts des taux de trésorerie : la trésorerie applique le taux du jour
# pour encaisser ou décaisser, la comptabilité retient le taux de la période
# (taux moyen, de clôture, officiel). Le moteur de génération n'utilise QUE
# ces taux-ci — le taux de trésorerie n'est jamais repris automatiquement.


def _taux_out(taux: ComptaTauxChange) -> TauxChangeOut:
    return TauxChangeOut(
        id=taux.id,
        devise_source=taux.devise_source,
        devise_cible=taux.devise_cible,
        taux=taux.taux,
        date_taux=taux.date_taux,
        source=taux.source,
        # Le comptable lit un taux « 2800 CDF pour 1 USD », pas « 0,00035714 ».
        taux_inverse=(Decimal(1) / Decimal(taux.taux)).quantize(Decimal("0.00000001"))
        if Decimal(taux.taux) > 0
        else Decimal(0),
    )


@router.get(
    "/taux-change",
    response_model=TauxChangeListOut,
    dependencies=[Depends(has_permission("compta.parametrage"))],
)
async def list_taux_change(
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> TauxChangeListOut:
    """Taux comptables saisis, et devises qui en manquent.

    `manquants` liste les devises effectivement utilisées par l'organisation
    (comptes bancaires, opérations) pour lesquelles aucun taux comptable
    n'existe : sans lui, toute écriture dans cette devise sera refusée.
    """
    societe = await _societe(db, tenant_id)

    exercice_res = await db.execute(
        select(ComptaExercice)
        .where(ComptaExercice.organisation_id == tenant_id, ComptaExercice.societe_id == societe.id)
        .order_by(ComptaExercice.date_debut.desc())
        .limit(1)
    )
    exercice = exercice_res.scalar_one_or_none()
    devise_tenue = (exercice.devise_tenue if exercice else societe.devise_tenue or "USD").upper()

    taux_res = await db.execute(
        select(ComptaTauxChange)
        .where(ComptaTauxChange.organisation_id == tenant_id)
        .order_by(ComptaTauxChange.date_taux.desc(), ComptaTauxChange.devise_source)
    )
    taux = list(taux_res.scalars().all())
    couvertes = {t.devise_source.upper() for t in taux} | {t.devise_cible.upper() for t in taux}

    # Devises réellement en usage : celles des comptes de trésorerie déclarés.
    devises_res = await db.execute(
        select(CompteBancaire.devise).where(
            CompteBancaire.organisation_id == tenant_id, CompteBancaire.is_active.is_(True)
        )
    )
    en_usage = {(d or "").upper() for d, in devises_res.all() if d}
    en_usage.discard("")
    en_usage.discard(devise_tenue)

    manquants: list[TauxChangeManquantOut] = []
    for devise in sorted(en_usage - couvertes):
        manquants.append(
            TauxChangeManquantOut(
                devise=devise,
                devise_tenue=devise_tenue,
                taux_tresorerie_propose=await taux_tresorerie_vers_comptable(
                    db, tenant_id, devise, devise_tenue
                ),
            )
        )

    return TauxChangeListOut(
        devise_tenue=devise_tenue,
        taux=[_taux_out(t) for t in taux],
        manquants=manquants,
    )


@router.post(
    "/taux-change",
    response_model=TauxChangeOut,
    dependencies=[Depends(has_permission("compta.parametrage"))],
)
async def upsert_taux_change(
    payload: TauxChangeIn,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> TauxChangeOut:
    """Enregistre un taux comptable pour une date.

    Un taux existant à la même date et pour le même couple de devises est
    remplacé : c'est une correction, pas un doublon. Les écritures déjà
    générées ne sont pas recalculées — leur taux est figé, comme le veut le
    principe d'immuabilité.
    """
    await _societe(db, tenant_id)
    source = payload.devise_source.upper()
    cible = payload.devise_cible.upper()
    if source == cible:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Les devises source et cible doivent être différentes.",
        )

    res = await db.execute(
        select(ComptaTauxChange).where(
            ComptaTauxChange.organisation_id == tenant_id,
            ComptaTauxChange.devise_source == source,
            ComptaTauxChange.devise_cible == cible,
            ComptaTauxChange.date_taux == payload.date_taux,
        )
    )
    taux = res.scalar_one_or_none()
    if taux is None:
        taux = ComptaTauxChange(
            organisation_id=tenant_id,
            devise_source=source,
            devise_cible=cible,
            taux=payload.taux,
            date_taux=payload.date_taux,
            source=payload.source,
        )
        db.add(taux)
    else:
        taux.taux = payload.taux
        taux.source = payload.source
    await db.commit()
    await db.refresh(taux)
    return _taux_out(taux)


@router.delete(
    "/taux-change/{taux_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    dependencies=[Depends(has_permission("compta.parametrage"))],
)
async def delete_taux_change(
    taux_id: int,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    taux = await db.get(ComptaTauxChange, taux_id)
    if taux is None or taux.organisation_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Taux introuvable.")
    await db.delete(taux)
    await db.commit()
