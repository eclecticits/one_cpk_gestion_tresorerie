"""Contrôles et validation des écritures comptables.

Tout ce qui figure ici est DÉTERMINISTE : équilibre, exercice ouvert, comptes
actifs, devises. Aucune de ces règles ne doit jamais être déléguée à l'IA —
celle-ci ne fait que suggérer, elle ne valide rien (cf. dossier d'architecture).

Le service s'inscrit dans le style du projet : il rejoint la transaction de
l'appelant (``db.add`` / ``db.flush``) et laisse le ``commit`` à l'endpoint.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.comptabilite.models import (
    ComptaCompte,
    ComptaEcriture,
    ComptaExercice,
    ComptaLigneEcriture,
    ComptaPeriode,
)
from app.modules.comptabilite.services.numerotation import generer_numero_ecriture

CENT = Decimal("0.01")
STATUTS_EXERCICE_SAISISSABLES = {"OUVERT", "ROUVERT"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _q(montant: Decimal | None) -> Decimal:
    """Arrondit au centime (demi-supérieur), norme comptable."""
    return (Decimal(montant or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def controler_equilibre(lignes: list[ComptaLigneEcriture]) -> tuple[Decimal, Decimal]:
    """Vérifie l'équilibre débit = crédit. Retourne (total_débit, total_crédit).

    Contrôle effectué **dans la devise de tenue** : c'est elle qui fait foi au
    Grand Livre. Une écriture multi-devises peut être déséquilibrée dans les
    devises d'origine tout en étant équilibrée en devise de tenue.
    """
    total_debit = sum((_q(l.debit_tenue) for l in lignes), Decimal("0"))
    total_credit = sum((_q(l.credit_tenue) for l in lignes), Decimal("0"))
    return _q(total_debit), _q(total_credit)


async def valider_ecriture(
    db: AsyncSession,
    *,
    ecriture_id: UUID,
    organisation_id: int,
    user_id: UUID | None,
) -> ComptaEcriture:
    """Valide une écriture au brouillon : contrôles complets puis numérotation.

    Une fois validée, l'écriture devient immuable (trigger en base) : seule la
    contre-passation permet de la corriger.
    """
    res = await db.execute(
        select(ComptaEcriture)
        .options(selectinload(ComptaEcriture.lignes))
        .where(
            ComptaEcriture.id == ecriture_id,
            ComptaEcriture.organisation_id == organisation_id,
        )
        .with_for_update()
    )
    ecriture = res.scalar_one_or_none()
    if ecriture is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Écriture introuvable")

    if ecriture.statut != "BROUILLON":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Seul un brouillon peut être validé (statut actuel : {ecriture.statut}).",
        )

    lignes = list(ecriture.lignes or [])

    # ── 1. Structure minimale ────────────────────────────────────────────────
    if len(lignes) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Une écriture doit comporter au moins deux lignes.",
        )

    # ── 2. Équilibre (règle cardinale) ───────────────────────────────────────
    total_debit, total_credit = controler_equilibre(lignes)
    if total_debit != total_credit:
        ecart = _q(total_debit - total_credit)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Écriture déséquilibrée : débit {total_debit} ≠ crédit {total_credit} "
                f"(écart {ecart})."
            ),
        )
    if total_debit <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Le montant total de l'écriture est nul."
        )

    # ── 3. Exercice ouvert et date cohérente ─────────────────────────────────
    exercice = await db.get(ComptaExercice, ecriture.exercice_id)
    if exercice is None or exercice.organisation_id != organisation_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exercice introuvable")
    if exercice.statut not in STATUTS_EXERCICE_SAISISSABLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"L'exercice {exercice.code} est {exercice.statut.lower()} : aucune validation possible.",
        )
    if not (exercice.date_debut <= ecriture.date_ecriture <= exercice.date_fin):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"La date {ecriture.date_ecriture} est hors de l'exercice {exercice.code} "
                f"({exercice.date_debut} → {exercice.date_fin})."
            ),
        )

    # ── 4. Période non fermée ────────────────────────────────────────────────
    per_res = await db.execute(
        select(ComptaPeriode).where(
            ComptaPeriode.exercice_id == exercice.id,
            ComptaPeriode.date_debut <= ecriture.date_ecriture,
            ComptaPeriode.date_fin >= ecriture.date_ecriture,
        )
    )
    periode = per_res.scalar_one_or_none()
    if periode is not None and periode.statut == "FERMEE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"La période {periode.numero:02d}/{exercice.code} est fermée.",
        )

    # ── 5. Comptes : existence, activité, cohérence tenant, devise ───────────
    compte_ids = {l.compte_id for l in lignes} | {
        l.compte_auxiliaire_id for l in lignes if l.compte_auxiliaire_id
    }
    cpt_res = await db.execute(
        select(ComptaCompte).where(
            ComptaCompte.id.in_(compte_ids),
            ComptaCompte.organisation_id == organisation_id,
        )
    )
    comptes = {c.id: c for c in cpt_res.scalars().all()}

    manquants = compte_ids - set(comptes)
    if manquants:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Compte(s) introuvable(s) ou hors organisation : {sorted(manquants)}",
        )

    for ligne in lignes:
        compte = comptes[ligne.compte_id]
        if not compte.actif:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Le compte {compte.numero} ({compte.libelle}) est inactif.",
            )
        if compte.is_collectif and not ligne.compte_auxiliaire_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Le compte collectif {compte.numero} exige un compte auxiliaire "
                    "(compte de tiers)."
                ),
            )
        if compte.devise_autorisee and compte.devise_autorisee != ligne.devise:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Le compte {compte.numero} n'accepte que la devise "
                    f"{compte.devise_autorisee} (ligne en {ligne.devise})."
                ),
            )

    # ── 6. Numérotation (uniquement maintenant : pas de trou de séquence) ────
    ecriture.numero = await generer_numero_ecriture(
        db,
        organisation_id=organisation_id,
        societe_id=ecriture.societe_id,
        exercice_id=ecriture.exercice_id,
        journal_id=ecriture.journal_id,
    )

    ecriture.statut = "VALIDEE"
    ecriture.valide_par = user_id
    ecriture.valide_le = _utcnow()
    ecriture.updated_at = _utcnow()
    await db.flush()

    return ecriture


async def contrepasser_ecriture(
    db: AsyncSession,
    *,
    ecriture_id: UUID,
    organisation_id: int,
    user_id: UUID | None,
    motif: str,
    date_contrepassation=None,
) -> ComptaEcriture:
    """Contre-passe une écriture validée : crée l'écriture inverse.

    L'écriture d'origine n'est JAMAIS modifiée dans ses données comptables ;
    elle est seulement marquée ANNULEE (seule transition permise par le trigger).
    """
    res = await db.execute(
        select(ComptaEcriture)
        .options(selectinload(ComptaEcriture.lignes))
        .where(
            ComptaEcriture.id == ecriture_id,
            ComptaEcriture.organisation_id == organisation_id,
        )
        .with_for_update()
    )
    origine = res.scalar_one_or_none()
    if origine is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Écriture introuvable")
    if origine.statut not in {"VALIDEE", "CLOTUREE"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Seule une écriture validée peut être contre-passée (statut : {origine.statut}).",
        )
    if not (motif or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Le motif de contre-passation est obligatoire."
        )

    exercice = await db.get(ComptaExercice, origine.exercice_id)
    if exercice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exercice introuvable")

    # Exercice clôturé : la contre-passation ne peut pas y être datée.
    if exercice.statut not in STATUTS_EXERCICE_SAISISSABLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"L'exercice {exercice.code} est {exercice.statut.lower()} : la correction doit "
                "être passée en écriture d'ajustement sur l'exercice courant."
            ),
        )

    date_cp = date_contrepassation or _utcnow().date()
    if not (exercice.date_debut <= date_cp <= exercice.date_fin):
        date_cp = exercice.date_fin

    inverse = ComptaEcriture(
        organisation_id=organisation_id,
        societe_id=origine.societe_id,
        etablissement_id=origine.etablissement_id,
        exercice_id=origine.exercice_id,
        journal_id=origine.journal_id,
        numero=None,  # attribué à la validation (NULL au brouillon)
        date_ecriture=date_cp,
        date_piece=origine.date_piece,
        reference_piece=origine.reference_piece,
        libelle=f"Contre-passation de {origine.numero} — {motif.strip()}",
        statut="BROUILLON",
        devise=origine.devise,
        taux_change=origine.taux_change,
        module_origine=origine.module_origine,
        type_origine="CONTREPASSATION",
        objet_origine_id=str(origine.id),
        est_automatique=True,
        created_by=user_id,
        contrepasse_ecriture_id=origine.id,
    )
    db.add(inverse)
    await db.flush()

    # Inversion sens débit ↔ crédit, montants inchangés.
    for ligne in origine.lignes or []:
        db.add(
            ComptaLigneEcriture(
                organisation_id=organisation_id,
                societe_id=ligne.societe_id,
                ecriture_id=inverse.id,
                compte_id=ligne.compte_id,
                compte_auxiliaire_id=ligne.compte_auxiliaire_id,
                ordre=ligne.ordre,
                libelle=f"Contre-passation — {ligne.libelle or ''}".strip(),
                debit=ligne.credit,
                credit=ligne.debit,
                devise=ligne.devise,
                debit_tenue=ligne.credit_tenue,
                credit_tenue=ligne.debit_tenue,
                taux_change=ligne.taux_change,
            )
        )
    await db.flush()

    # Marquage de l'origine (seule mutation tolérée par le trigger).
    origine.statut = "ANNULEE"
    origine.motif_annulation = motif.strip()
    origine.annule_par = user_id
    origine.annule_le = _utcnow()
    await db.flush()

    return inverse
