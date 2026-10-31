from __future__ import annotations

import re

from sqlalchemy import (
    Boolean,
    Date,
    Integer,
    Numeric,
    String,
    and_,
    case,
    cast,
    func,
    literal,
    or_,
    select,
    union_all,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import (
    TableauAnomalie,
    TableauAnalyse,
    TableauDecision,
    TableauDossier,
    TableauImport,
    TableauPersonneMoraleSnapshot,
    TableauPersonnePhysiqueSnapshot,
    TableauReport,
    TableauSourceRow,
)


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
        func.nullif(func.trim(TableauDossier.numero_ordre), ""),
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


CATEGORIES_MORALES = ("Société", "SEC")


def _annee_exercice(exercice: str | None) -> int | None:
    m = re.search(r"(20\d{2})", str(exercice or ""))
    return int(m.group(1)) if m else None


def _annee_du_numero(numero):
    """Année d'inscription lue en SQL dans le n° d'ordre (EC/17.00002 -> 2017)."""
    return 2000 + cast(func.substring(numero, r"/(\d{2})\."), Integer)


def _filtre_anciennete(numero, exercice: str, anciennete: str):
    annee = _annee_du_numero(numero)
    reference = _annee_exercice(exercice)
    if reference is None:
        return literal(False)
    return annee == reference if anciennete == "Nouveau" else annee < reference


def _sexe_normalise(colonne):
    return func.upper(func.left(func.trim(colonne), 1))


def _provinces_membres(organisation_ids: list[int], exercice: str):
    """Dernière province connue de chaque membre, d'après ses fiches de l'exercice."""
    def lignes(model):
        province = func.upper(func.trim(model.province_attache))
        return (
            select(
                model.organisation_id.label("organisation_id"),
                model.numero_ordre.label("numero_ordre"),
                province.label("province"),
                func.row_number().over(
                    partition_by=(model.organisation_id, model.numero_ordre),
                    order_by=(model.date_situation.desc(), model.id.desc()),
                ).label("rang"),
            )
            .join(TableauImport, TableauImport.id == model.source_import_id)
            .where(
                model.organisation_id.in_(organisation_ids),
                TableauImport.exercice == exercice,
                model.numero_ordre != "",
                func.coalesce(func.trim(model.province_attache), "") != "",
            )
        )

    union = union_all(
        lignes(TableauPersonnePhysiqueSnapshot), lignes(TableauPersonneMoraleSnapshot)
    ).subquery()
    return select(union.c.organisation_id, union.c.numero_ordre, union.c.province).where(union.c.rang == 1).subquery()


async def provinces_par_membre(
    db: AsyncSession, organisation_ids: list[int], exercice: str
) -> dict[tuple[int, str], str]:
    provinces = _provinces_membres(organisation_ids, exercice)
    lignes = (await db.execute(select(provinces))).all()
    return {(ligne.organisation_id, ligne.numero_ordre): ligne.province for ligne in lignes}


async def actifs_par_membre(
    db: AsyncSession, organisation_ids: list[int], exercice: str
) -> dict[tuple[int, str], bool]:
    """Dernier statut « Actif » de chaque membre : seul le fichier des personnes physiques le porte."""
    pp = TableauPersonnePhysiqueSnapshot
    lignes = (await db.execute(
        select(pp.organisation_id, pp.numero_ordre, pp.actif)
        .join(TableauImport, TableauImport.id == pp.source_import_id)
        .where(
            pp.organisation_id.in_(organisation_ids),
            TableauImport.exercice == exercice,
            pp.numero_ordre != "",
            pp.actif.is_not(None),
        )
        .order_by(pp.date_situation.asc(), pp.id.asc())
    )).all()
    return {(ligne.organisation_id, ligne.numero_ordre): ligne.actif for ligne in lignes}


def _base_filtrage(
    q,
    *,
    organisation_ids: list[int],
    exercice: str,
    recherche: str | None = None,
    categorie: str | None = None,
    organisation_id: int | None = None,
    anomalie_only: bool = False,
    personne: str | None = None,
    province: str | None = None,
    sexe: str | None = None,
    anciennete: str | None = None,
):
    if personne == "morale":
        q = q.where(TableauDossier.categorie.in_(CATEGORIES_MORALES))
    elif personne == "physique":
        q = q.where(TableauDossier.categorie.not_in(CATEGORIES_MORALES))
    if sexe:
        q = q.where(_sexe_normalise(TableauDossier.sexe) == sexe)
    if anciennete:
        # Sans année lisible dans le numéro, le libellé du fichier reste la seule information.
        q = q.where(or_(
            _filtre_anciennete(TableauDossier.numero_ordre, exercice, anciennete),
            and_(
                func.substring(TableauDossier.numero_ordre, r"/(\d{2})\.").is_(None),
                func.lower(TableauDossier.anciennete).like(f"%{anciennete.lower()}%"),
            ),
        ))
    if province:
        provinces = _provinces_membres(organisation_ids, exercice)
        q = q.where(
            select(provinces.c.numero_ordre)
            .where(
                provinces.c.organisation_id == TableauDossier.organisation_id,
                provinces.c.numero_ordre == TableauDossier.numero_ordre,
                provinces.c.province == province.strip().upper(),
            )
            .exists()
        )
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
        # Une société d'expertise comptable s'appelle « Société » ; un ancien dossier
        # peut encore porter « SEC » et doit répondre au même filtre.
        categories = ("Société", "SEC") if categorie in ("Société", "SEC") else (categorie,)
        q = q.where(TableauDossier.categorie.in_(categories))
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
    personne: str | None = None,
    province: str | None = None,
    sexe: str | None = None,
    anciennete: str | None = None,
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
        organisation_ids=organisation_ids,
        exercice=exercice,
        recherche=recherche,
        categorie=categorie,
        organisation_id=organisation_id,
        anomalie_only=anomalie_only,
        personne=personne,
        province=province,
        sexe=sexe,
        anciennete=anciennete,
    ).order_by(func.lower(TableauDossier.nom), TableauDossier.id)
    if limit is not None:
        q = q.limit(limit).offset(offset)
    res = await db.execute(q)
    return list(res.scalars().all())


def _membres_a_completer(
    organisation_ids: list[int],
    exercice: str,
    *,
    recherche: str | None = None,
    categorie: str | None = None,
    organisation_id: int | None = None,
    personne: str | None = None,
    province: str | None = None,
    sexe: str | None = None,
    anciennete: str | None = None,
):
    """Membres des fichiers personnes physiques et morales encore sans dossier.

    Lecture seule, sans verdict : ces fichiers ne disent rien de la cotisation ni du CA.
    Le NHV affiché est la colonne « % 120 FOR » du fichier des personnes physiques, telle
    qu'importée. Un dossier du même exercice prime toujours. Une ligne non rattachée
    n'a pas de clé qui la relie à un import suivant : seul le dernier fichier de sa
    source la fait donc foi, sinon chaque réimport la dupliquerait.
    """
    def lignes(model, genre: str, nom, categorie_expr, nif, cabinet, sexe_expr, nhv, actif):
        cle = case(
            (model.identity_id.is_(None), func.concat(genre, "#", cast(model.id, String))),
            else_=model.numero_ordre,
        )
        ordre = (model.date_situation.desc(), TableauImport.created_at.desc(), TableauImport.id.desc())
        return (
            select(
                literal(genre).label("genre"),
                model.id.label("id"),
                model.organisation_id.label("organisation_id"),
                model.source_import_id.label("import_id"),
                model.source_row_id.label("source_row_id"),
                model.identity_id.label("identity_id"),
                model.numero_ordre.label("numero_ordre"),
                nom.label("nom"),
                categorie_expr.label("categorie"),
                nif.label("nif"),
                cabinet.label("cabinet"),
                model.email.label("email"),
                model.telephone.label("telephone"),
                model.assure_synthetique.label("assurance"),
                sexe_expr.label("sexe"),
                nhv.label("nhv"),
                actif.label("actif"),
                func.upper(func.trim(model.province_attache)).label("province"),
                model.date_situation.label("date_situation"),
                TableauImport.file_name.label("source_file_name"),
                func.row_number().over(partition_by=(model.organisation_id, cle), order_by=(*ordre, model.id.desc())).label("rang"),
                func.dense_rank().over(partition_by=model.organisation_id, order_by=ordre).label("rang_import"),
            )
            .join(TableauImport, TableauImport.id == model.source_import_id)
            .where(model.organisation_id.in_(organisation_ids), TableauImport.exercice == exercice)
        )

    pp = TableauPersonnePhysiqueSnapshot
    pm = TableauPersonneMoraleSnapshot
    union = union_all(
        lignes(
            pp, "PP", pp.nom,
            case(
                (pp.statut_normalise == "EN_CABINET", "EC Cabinet"),
                (pp.statut_normalise == "INDEPENDANT", "EC Indépendant"),
                (pp.statut_normalise == "SALARIE", "EC Salarié"),
                else_="Inconnu",
            ),
            func.coalesce(pp.nif, pp.numero_impot),
            func.coalesce(pp.cabinet_attache, pp.nom_employeur),
            pp.sexe,
            pp.pourcentage_120_for,
            pp.actif,
        ),
        lignes(
            pm, "PM", pm.societe, literal("Société"), pm.numero_impot,
            cast(literal(None), String), cast(literal(None), String), cast(literal(None), Numeric(8, 2)),
            cast(literal(None), Boolean),
        ),
    ).subquery()

    a_un_dossier = (
        select(TableauDossier.id)
        .where(
            func.coalesce(func.trim(union.c.numero_ordre), "") != "",
            TableauDossier.organisation_id == union.c.organisation_id,
            TableauDossier.exercice == exercice,
            TableauDossier.numero_ordre == union.c.numero_ordre,
        )
        .exists()
    )
    filtres = [
        union.c.rang == 1,
        or_(union.c.identity_id.is_not(None), union.c.rang_import == 1),
        ~a_un_dossier,
    ]
    if recherche and recherche.strip():
        motif = f"%{recherche.strip()}%"
        filtres.append(or_(
            union.c.numero_ordre.ilike(motif),
            union.c.nom.ilike(motif),
            union.c.email.ilike(motif),
            union.c.nif.ilike(motif),
            union.c.cabinet.ilike(motif),
        ))
    if categorie:
        filtres.append(union.c.categorie == ("Société" if categorie == "SEC" else categorie))
    if personne:
        filtres.append(union.c.genre == ("PM" if personne == "morale" else "PP"))
    if province:
        filtres.append(union.c.province == province.strip().upper())
    if sexe:
        filtres.append(_sexe_normalise(union.c.sexe) == sexe)
    if anciennete:
        filtres.append(_filtre_anciennete(union.c.numero_ordre, exercice, anciennete))
    if organisation_id is not None:
        filtres.append(union.c.organisation_id == organisation_id)
    return union, filtres


async def list_membres_a_completer(
    db: AsyncSession,
    organisation_ids: list[int],
    exercice: str,
    *,
    recherche: str | None = None,
    categorie: str | None = None,
    organisation_id: int | None = None,
    limit: int | None = None,
    offset: int = 0,
    personne: str | None = None,
    province: str | None = None,
    sexe: str | None = None,
    anciennete: str | None = None,
) -> tuple[list, dict]:
    """Renvoie (lignes de la page, résumé de l'ensemble)."""
    union, filtres = _membres_a_completer(
        organisation_ids, exercice, recherche=recherche, categorie=categorie, organisation_id=organisation_id,
        personne=personne, province=province, sexe=sexe, anciennete=anciennete,
    )
    total, sans_numero, imports, organisations = (await db.execute(
        select(
            func.count(),
            func.count().filter(union.c.numero_ordre == ""),
            func.array_agg(func.distinct(union.c.import_id)),
            func.array_agg(func.distinct(union.c.organisation_id)),
        ).select_from(union).where(*filtres)
    )).one()
    q = (
        select(union, TableauSourceRow.normalization_errors.label("erreurs"))
        .join(TableauSourceRow, TableauSourceRow.id == union.c.source_row_id)
        .where(*filtres)
        .order_by(func.lower(union.c.nom), union.c.genre, union.c.id)
    )
    if limit is not None:
        q = q.limit(limit).offset(offset)
    lignes = (await db.execute(q)).all()
    return lignes, {
        "total": total or 0,
        "sans_numero": sans_numero or 0,
        "imports": sorted(imports or []),
        "organisations": sorted(organisations or []),
    }


async def get_base_summary(
    db: AsyncSession,
    organisation_ids: list[int],
    exercice: str,
    *,
    anomalie_only: bool = False,
    recherche: str | None = None,
    categorie: str | None = None,
    organisation_id: int | None = None,
    personne: str | None = None,
    province: str | None = None,
    sexe: str | None = None,
    anciennete: str | None = None,
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
        organisation_ids=organisation_ids,
        exercice=exercice,
        recherche=recherche,
        categorie=categorie,
        organisation_id=organisation_id,
        anomalie_only=anomalie_only,
        personne=personne,
        province=province,
        sexe=sexe,
        anciennete=anciennete,
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
