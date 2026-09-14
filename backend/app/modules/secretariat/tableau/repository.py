from __future__ import annotations

from sqlalchemy import Date, String, cast, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import TableauAnomalie, TableauAnalyse, TableauDecision, TableauDossier, TableauImport, TableauReport


async def get_import(db: AsyncSession, organisation_id: int, import_id: int) -> TableauImport | None:
    res = await db.execute(
        select(TableauImport).where(
            TableauImport.organisation_id == organisation_id,
            TableauImport.id == import_id,
        )
    )
    return res.scalar_one_or_none()


async def list_imports(db: AsyncSession, organisation_id: int) -> list[TableauImport]:
    res = await db.execute(
        select(TableauImport)
        .where(TableauImport.organisation_id == organisation_id)
        .order_by(TableauImport.created_at.desc())
    )
    return list(res.scalars().all())


async def list_dossiers(
    db: AsyncSession,
    organisation_id: int,
    import_id: int | None = None,
    exercice: str | None = None,
    anomalie_only: bool = False,
) -> list[TableauDossier]:
    q = select(TableauDossier).where(TableauDossier.organisation_id == organisation_id)
    if import_id:
        q = q.where(TableauDossier.import_id == import_id)
    if exercice:
        q = q.where(TableauDossier.exercice == exercice)
    if anomalie_only:
        q = q.where(TableauDossier.anomalie_detectee.is_(True))
    q = q.order_by(TableauDossier.nom.asc())
    res = await db.execute(q)
    return list(res.scalars().all())


async def dernier_exercice(db: AsyncSession, organisation_ids: list[int]) -> str | None:
    """Exercice de la situation métier la plus récente."""
    res = await db.execute(
        select(TableauImport.exercice)
        .where(TableauImport.organisation_id.in_(organisation_ids))
        .order_by(
            func.coalesce(TableauImport.date_situation, cast(TableauImport.created_at, Date)).desc(),
            TableauImport.created_at.desc(),
        )
        .limit(1)
    )
    return res.scalar_one_or_none()


def _cle_membre():
    """Identité d'un membre au Tableau : son n° d'ordre, à défaut la ligne elle-même.

    Une ligne sans n° d'ordre ne peut être rapprochée d'aucune autre : elle reste
    donc présente telle quelle dans la base, à charge pour l'Agent Tableau de la
    corriger.
    """
    return func.coalesce(
        TableauDossier.numero_ordre,
        literal("#") + cast(TableauDossier.id, String),
    )


def _base_classee(organisation_ids: list[int], exercice: str):
    """Sous-requête canonique désignant une seule situation par membre."""
    cle = _cle_membre()
    date_effective = func.coalesce(
        TableauImport.date_situation,
        cast(TableauImport.created_at, Date),
    )
    return (
        select(
            TableauDossier.id.label("dossier_id"),
            func.row_number().over(
                partition_by=(TableauDossier.organisation_id, cle),
                order_by=(
                    date_effective.desc(),
                    TableauImport.created_at.desc(),
                    TableauDossier.import_id.desc(),
                    TableauDossier.id.desc(),
                ),
            ).label("rang"),
        )
        .join(TableauImport, TableauImport.id == TableauDossier.import_id)
        .where(
            TableauDossier.organisation_id.in_(organisation_ids),
            TableauDossier.exercice == exercice,
        )
        .subquery()
    )


def _base_filtrage(
    q,
    *,
    recherche: str | None = None,
    categorie: str | None = None,
    organisation_id: int | None = None,
    anomalie_only: bool = False,
):
    if recherche and recherche.strip():
        motif = f"%{recherche.strip()}%"
        q = q.where(or_(
            TableauDossier.numero_ordre.ilike(motif),
            TableauDossier.nom.ilike(motif),
            TableauDossier.prenom.ilike(motif),
            TableauDossier.email.ilike(motif),
            TableauDossier.nif.ilike(motif),
            TableauDossier.cabinet.ilike(motif),
        ))
    if categorie:
        q = q.where(TableauDossier.categorie == categorie)
    if organisation_id is not None:
        q = q.where(TableauDossier.organisation_id == organisation_id)
    if anomalie_only:
        # Le filtre intervient après le classement : une ancienne anomalie corrigée
        # ne doit jamais faire réapparaître une situation historique.
        q = q.where(TableauDossier.anomalie_detectee.is_(True))
    return q


async def list_base_tableau(
    db: AsyncSession,
    organisation_ids: list[int],
    exercice: str,
    anomalie_only: bool = False,
    recherche: str | None = None,
    categorie: str | None = None,
    organisation_id: int | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[TableauDossier]:
    """Situation qui fait foi pour chaque membre de l'exercice, tous imports confondus.

    Le Tableau conserve tous les imports ; la base consolidée retient, par membre,
    la situation la plus récente au sens métier — la date de situation du fichier,
    et non sa date de téléversement. Réimporter un ancien fichier ne fait donc pas
    revenir la base en arrière. Le calcul ne dépend d'aucun marqueur stocké : il
    vaut aussi pour les imports antérieurs à cette consolidation.
    """
    classee = _base_classee(organisation_ids, exercice)
    q = (
        select(TableauDossier)
        .options(selectinload(TableauDossier.import_ref))
        .join(classee, classee.c.dossier_id == TableauDossier.id)
        .where(classee.c.rang == 1)
    )
    q = _base_filtrage(
        q,
        recherche=recherche,
        categorie=categorie,
        organisation_id=organisation_id,
        anomalie_only=anomalie_only,
    ).order_by(func.lower(TableauDossier.nom), TableauDossier.id)
    if limit is not None:
        q = q.limit(limit).offset(offset)
    res = await db.execute(q)
    return list(res.scalars().all())


async def get_base_summary(
    db: AsyncSession,
    organisation_ids: list[int],
    exercice: str,
    *,
    anomalie_only: bool = False,
    recherche: str | None = None,
    categorie: str | None = None,
    organisation_id: int | None = None,
) -> dict:
    classee = _base_classee(organisation_ids, exercice)
    q = (
        select(
            func.count(TableauDossier.id),
            func.count(TableauDossier.id).filter(TableauDossier.numero_ordre.is_(None)),
            func.array_agg(func.distinct(TableauDossier.import_id)),
            func.array_agg(func.distinct(TableauDossier.organisation_id)),
        )
        .join(classee, classee.c.dossier_id == TableauDossier.id)
        .where(classee.c.rang == 1)
    )
    q = _base_filtrage(
        q,
        recherche=recherche,
        categorie=categorie,
        organisation_id=organisation_id,
        anomalie_only=anomalie_only,
    )
    total, sans_numero, imports, organisations = (await db.execute(q)).one()
    return {
        "total": total or 0,
        "sans_numero": sans_numero or 0,
        "imports": sorted(imports or []),
        "organisations": sorted(organisations or []),
    }


async def list_anomalies(
    db: AsyncSession,
    organisation_id: int,
    import_id: int | None = None,
    gravite: str | None = None,
    analyse_id: int | None = None,
    legacy_only: bool = False,
) -> list[TableauAnomalie]:
    q = (
        select(TableauAnomalie)
        .join(TableauDossier, TableauAnomalie.dossier_id == TableauDossier.id)
        .where(TableauDossier.organisation_id == organisation_id)
    )
    if import_id:
        q = q.where(TableauDossier.import_id == import_id)
    if gravite:
        q = q.where(TableauAnomalie.gravite == gravite)
    if analyse_id is not None:
        q = q.where(TableauAnomalie.analyse_id == analyse_id)
    elif legacy_only:
        q = q.where(TableauAnomalie.analyse_id.is_(None))
    q = q.order_by(TableauAnomalie.gravite.asc(), TableauAnomalie.created_at.desc())
    res = await db.execute(q)
    return list(res.scalars().all())


async def get_analyse_for_import(
    db: AsyncSession,
    organisation_id: int,
    import_id: int,
    scope: str = "import",
) -> TableauAnalyse | None:
    res = await db.execute(
        select(TableauAnalyse).where(
            TableauAnalyse.organisation_id == organisation_id,
            TableauAnalyse.import_id == import_id,
            TableauAnalyse.scope == scope,
        ).order_by(TableauAnalyse.created_at.desc())
    )
    return res.scalars().first()


async def list_reports(db: AsyncSession, organisation_id: int) -> list[TableauReport]:
    res = await db.execute(
        select(TableauReport)
        .where(TableauReport.organisation_id == organisation_id)
        .order_by(TableauReport.created_at.desc())
    )
    return list(res.scalars().all())


async def get_stats(db: AsyncSession, organisation_id: int) -> dict:
    imports_count_res = await db.execute(
        select(func.count()).where(TableauImport.organisation_id == organisation_id)
    )
    imports_count = imports_count_res.scalar_one() or 0

    last_exercice = await dernier_exercice(db, [organisation_id])
    dossiers_count = analyses_count = anomalies_count = decisions_count = 0
    # « Incomplet » ne se déduit pas d'une colonne : c'est le barème appliqué à la
    # catégorie qui le dit. Sans analyse de base à jour, le chiffre est inconnu —
    # et un zéro affiché à sa place se lirait comme « aucun dossier incomplet ».
    incomplets_count: int | None = None
    analyse_base_status: str | None = None
    if last_exercice:
        classee = _base_classee([organisation_id], last_exercice)
        dossiers_count_res = await db.execute(
            select(
                func.count(TableauDossier.id),
                func.count(TableauDossier.id).filter(TableauDossier.conclusion.is_not(None)),
                func.count(TableauDossier.id).filter(TableauDossier.anomalie_detectee.is_(True)),
            )
            .join(classee, classee.c.dossier_id == TableauDossier.id)
            .where(classee.c.rang == 1)
        )
        dossiers_count, analyses_count, anomalies_count = dossiers_count_res.one()

        analyse_res = await db.execute(
            select(TableauAnalyse)
            .where(
                TableauAnalyse.organisation_id == organisation_id,
                TableauAnalyse.exercice == last_exercice,
                TableauAnalyse.scope == "base",
            )
            .order_by(TableauAnalyse.updated_at.desc(), TableauAnalyse.id.desc())
            .limit(1)
        )
        analyse = analyse_res.scalars().first()
        analyse_base_status = analyse.status if analyse is not None else None
        if analyse is not None and analyse.status == "completed":
            analyses_count = analyse.total_dossiers
            incomplets_count = analyse.dossiers_incomplets
            anomalies_count = analyse.anomalies_count

        decisions_count_res = await db.execute(
            select(func.count(func.distinct(TableauDecision.id)))
            .join(TableauDossier, TableauDecision.dossier_id == TableauDossier.id)
            .where(
                TableauDecision.organisation_id == organisation_id,
                TableauDossier.organisation_id == organisation_id,
                TableauDossier.exercice == last_exercice,
            )
        )
        decisions_count = decisions_count_res.scalar_one() or 0

    return {
        "dossiers_importes": dossiers_count or 0,
        "dossiers_analyses": analyses_count or 0,
        "dossiers_incomplets": incomplets_count,
        "anomalies_detectees": anomalies_count,
        "decisions_a_valider": decisions_count,
        "imports_count": imports_count,
        "last_exercice": last_exercice,
        "analyse_base_status": analyse_base_status,
    }
