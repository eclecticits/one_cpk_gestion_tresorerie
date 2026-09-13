from __future__ import annotations

from sqlalchemy import String, cast, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

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
    """Exercice du dernier import connu, tous conseils demandés confondus."""
    res = await db.execute(
        select(TableauImport.exercice)
        .where(TableauImport.organisation_id.in_(organisation_ids))
        .order_by(TableauImport.created_at.desc())
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


async def list_base_tableau(
    db: AsyncSession,
    organisation_ids: list[int],
    exercice: str,
    anomalie_only: bool = False,
) -> list[TableauDossier]:
    """Situation qui fait foi pour chaque membre de l'exercice, tous imports confondus.

    Le Tableau conserve tous les imports ; la base consolidée retient, par membre,
    la situation la plus récente au sens métier — la date de situation du fichier,
    et non sa date de téléversement. Réimporter un ancien fichier ne fait donc pas
    revenir la base en arrière. Le calcul ne dépend d'aucun marqueur stocké : il
    vaut aussi pour les imports antérieurs à cette consolidation.
    """
    cle = _cle_membre()
    q = (
        select(TableauDossier)
        .join(TableauImport, TableauImport.id == TableauDossier.import_id)
        .where(
            TableauDossier.organisation_id.in_(organisation_ids),
            TableauDossier.exercice == exercice,
        )
        .distinct(TableauDossier.organisation_id, cle)
        .order_by(
            TableauDossier.organisation_id,
            cle,
            TableauImport.date_situation.desc().nullslast(),
            TableauImport.created_at.desc(),
            TableauDossier.import_id.desc(),
            TableauDossier.id.desc(),
        )
    )
    if anomalie_only:
        q = q.where(TableauDossier.anomalie_detectee.is_(True))
    res = await db.execute(q)
    dossiers = list(res.scalars().all())
    dossiers.sort(key=lambda d: (d.nom or "").lower())
    return dossiers


async def list_anomalies(
    db: AsyncSession,
    organisation_id: int,
    import_id: int | None = None,
    gravite: str | None = None,
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
    q = q.order_by(TableauAnomalie.gravite.asc(), TableauAnomalie.created_at.desc())
    res = await db.execute(q)
    return list(res.scalars().all())


async def get_analyse_for_import(db: AsyncSession, organisation_id: int, import_id: int) -> TableauAnalyse | None:
    res = await db.execute(
        select(TableauAnalyse).where(
            TableauAnalyse.organisation_id == organisation_id,
            TableauAnalyse.import_id == import_id,
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

    dossiers_count_res = await db.execute(
        select(func.count()).where(TableauDossier.organisation_id == organisation_id)
    )
    dossiers_count = dossiers_count_res.scalar_one() or 0

    anomalies_count_res = await db.execute(
        select(func.count())
        .select_from(TableauAnomalie)
        .join(TableauDossier, TableauAnomalie.dossier_id == TableauDossier.id)
        .where(TableauDossier.organisation_id == organisation_id)
        .where(TableauAnomalie.status == "open")
    )
    anomalies_count = anomalies_count_res.scalar_one() or 0

    incomplets_count_res = await db.execute(
        select(func.count())
        .where(TableauDossier.organisation_id == organisation_id)
        .where(TableauDossier.statut_dossier == "incomplet")
    )
    incomplets_count = incomplets_count_res.scalar_one() or 0

    decisions_count_res = await db.execute(
        select(func.count())
        .where(TableauDecision.organisation_id == organisation_id)
    )
    decisions_count = decisions_count_res.scalar_one() or 0

    last_import_res = await db.execute(
        select(TableauImport.exercice)
        .where(TableauImport.organisation_id == organisation_id)
        .order_by(TableauImport.created_at.desc())
        .limit(1)
    )
    last_exercice = last_import_res.scalar_one_or_none()

    analyses_count_res = await db.execute(
        select(func.count())
        .select_from(TableauAnalyse)
        .where(TableauAnalyse.organisation_id == organisation_id)
        .where(TableauAnalyse.status == "completed")
    )
    analyses_count = analyses_count_res.scalar_one() or 0

    return {
        "dossiers_importes": dossiers_count,
        "dossiers_analyses": analyses_count,
        "dossiers_incomplets": incomplets_count,
        "anomalies_detectees": anomalies_count,
        "decisions_a_valider": decisions_count,
        "imports_count": imports_count,
        "last_exercice": last_exercice,
    }
