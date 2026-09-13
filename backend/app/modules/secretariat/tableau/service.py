from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
import unicodedata
import re
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.models.user import User
from . import verdict as verdict_engine
from .analyzer import compute_analyse_stats, detect_anomalies
from .comparison import compare_exercices
from .excel_import import parse_excel_bytes
from .models import TableauAnalyse, TableauAnomalie, TableauDecision, TableauDossier, TableauImport, TableauReport
from .report_generator import generate_analyse_report, generate_pv
from .repository import (
    dernier_exercice,
    get_analyse_for_import,
    get_import,
    get_stats,
    list_anomalies,
    list_base_tableau,
    list_dossiers,
    list_imports,
    list_reports,
)
from .schemas import TableauDecisionCreate, TableauPVCreate, TableauReportCreate


@dataclass
class ImportOutcome:
    """Résultat standardisé d'un import (aligné sur le procédé budget)."""
    imp: TableauImport
    imported: int = 0
    updated: int = 0
    skipped: int = 0
    total: int = 0
    errors: list[dict] = field(default_factory=list)
    reprises: int = 0
    decisions_reportees: int = 0
    nouveaux_membres: int = 0


_CATEGORIES_CONNUES = {"Société", "EC Cabinet", "EC Indépendant", "EC Salarié", "Stagiaire"}


def _norm_numero_ordre(value: str | None) -> str | None:
    """Normalisation prudente du n° d'ordre : trim, majuscules, espaces internes ôtés.

    La structure du numéro (EC/18.00062) n'est jamais retouchée : elle porte
    l'année d'inscription et sert de clé d'identité du membre au Tableau.
    """
    if not value:
        return None
    compact = "".join(str(value).strip().upper().split())
    return compact or None


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _exercice_annee(exercice: str | None) -> int | None:
    m = re.search(r"(20\d{2})", str(exercice or ""))
    return int(m.group(1)) if m else None


def _anciennete_annees(numero_ordre: str | None, exercice: str | None) -> tuple[int | None, int | None]:
    """Année d'inscription lue dans le n° d'ordre, et ancienneté à l'exercice traité."""
    annee_inscription = verdict_engine.annee_ordre(numero_ordre)
    annee_exercice = _exercice_annee(exercice)
    if annee_inscription is None or annee_exercice is None:
        return annee_inscription, None
    return annee_inscription, max(0, annee_exercice - annee_inscription)


def _rang_situation(dossier: TableauDossier) -> tuple[date, datetime, int]:
    """Position d'une situation dans le temps métier : date du fichier, puis import."""
    imp = dossier.import_ref
    situation_date = imp.date_situation if imp and imp.date_situation else dossier.created_at.date()
    import_created = imp.created_at if imp and imp.created_at else dossier.created_at
    return situation_date, import_created, dossier.import_id


def _rang_fraicheur(dossier: TableauDossier) -> tuple[date, datetime, int, int]:
    """Fraîcheur d'une situation : sa position dans le temps, puis son rang d'insertion."""
    return (*_rang_situation(dossier), dossier.id or 0)


# Champs qu'un import peut reprendre de la situation précédente quand sa cellule est
# vide. Le parser distingue l'absence d'information (None) d'un « NON » ou d'un 0
# explicites : seule l'absence déclenche la reprise, jamais une infirmation.
_CHAMPS_REPRENABLES = (
    "prenom", "sexe", "date_naissance", "age", "nif", "email", "telephone",
    "adresse", "cabinet", "statut_membre", "anciennete", "categorie",
    "cotisation_payee", "cotisation_montant", "heures_forco", "assurance",
    "chiffre_affaires",
)


def _valeur_absente(champ: str, valeur: Any) -> bool:
    if valeur is None or valeur == "":
        return True
    # Le parser écrit « Inconnu » quand la feuille ne permet pas de trancher.
    return champ == "categorie" and valeur == "Inconnu"


def _valeur_json(valeur: Any) -> Any:
    if isinstance(valeur, (datetime, date)):
        return valeur.isoformat()
    if isinstance(valeur, Decimal):
        return float(valeur)
    return valeur


async def _situations_precedentes(
    db: AsyncSession,
    organisation_id: int,
    exercice: str,
    numeros: set[str],
    rang_import: tuple[date, datetime, int],
) -> dict[str, TableauDossier]:
    """Dernière situation connue de chaque membre, antérieure au fichier importé.

    L'antériorité s'apprécie au sens métier. Un fichier de mars téléversé après
    celui de juin reprend donc la situation qui le précédait vraiment, et jamais
    une information postérieure à ce qu'il décrit.
    """
    if not numeros:
        return {}
    res = await db.execute(
        select(TableauDossier)
        .options(selectinload(TableauDossier.import_ref))
        .where(
            TableauDossier.organisation_id == organisation_id,
            TableauDossier.exercice == exercice,
            TableauDossier.numero_ordre.in_(numeros),
        )
    )
    precedentes: dict[str, TableauDossier] = {}
    for candidat in res.scalars().all():
        numero = _norm_numero_ordre(candidat.numero_ordre)
        if not numero:
            continue
        rang = _rang_situation(candidat)
        if rang >= rang_import:
            continue
        retenu = precedentes.get(numero)
        if retenu is None or rang > _rang_situation(retenu):
            precedentes[numero] = candidat
    return precedentes


async def _numeros_deja_connus(
    db: AsyncSession,
    organisation_id: int,
    numeros: set[str],
    import_id: int,
) -> set[str]:
    """N° d'ordre que le Tableau de ce conseil connaissait déjà avant cet import.

    Tous exercices confondus : un membre n'est nouveau qu'une fois, et le rester
    d'un exercice à l'autre n'aurait pas de sens.
    """
    if not numeros:
        return set()
    res = await db.execute(
        select(TableauDossier.numero_ordre)
        .where(
            TableauDossier.organisation_id == organisation_id,
            TableauDossier.numero_ordre.in_(numeros),
            TableauDossier.import_id != import_id,
        )
        .distinct()
    )
    return {n for n in (_norm_numero_ordre(v) for v in res.scalars().all()) if n}


def _reprendre_valeurs_manquantes(row: dict[str, Any], precedente: TableauDossier) -> list[dict]:
    """Complète les cellules vides du fichier par la dernière valeur connue.

    Une actualisation dit ce qui a changé ; ce qu'elle ne dit pas ne doit pas
    disparaître de la base pour autant.
    """
    reprises: list[dict] = []
    for champ in _CHAMPS_REPRENABLES:
        if not _valeur_absente(champ, row.get(champ)):
            continue
        valeur = getattr(precedente, champ, None)
        if _valeur_absente(champ, valeur):
            continue
        row[champ] = valeur
        reprises.append({
            "champ": champ,
            "valeur": _valeur_json(valeur),
            "depuis_import": precedente.import_id,
        })
    return reprises


def _set_situation(dossier: TableauDossier, courante: bool, motif: str, **extra: Any) -> None:
    raw = dict(dossier.raw_data or {})
    situation = dict(raw.get("situation") or {})
    situation["courante"] = courante
    situation["motif"] = motif
    situation.update(extra)
    raw["situation"] = situation
    dossier.raw_data = raw
    flag_modified(dossier, "raw_data")


async def _marquer_situations_courantes(db: AsyncSession, dossiers: list[TableauDossier]) -> None:
    """Désigne, pour chaque n° d'ordre touché, la situation qui fait foi sur l'exercice.

    Le Tableau conserve tous les imports : plusieurs situations coexistent donc
    pour un même membre. La plus récente au sens métier — la date de situation du
    fichier, pas la date de téléversement — l'emporte, de sorte que réimporter par
    erreur un ancien fichier ne fait pas revenir la situation opérationnelle en
    arrière. Organisation et exercice étant constants sur un import, une seule
    requête ramène toutes les situations concurrentes.
    """
    numeros: set[str] = set()
    for dossier in dossiers:
        numero = _norm_numero_ordre(dossier.numero_ordre)
        if numero:
            numeros.add(numero)
        else:
            _set_situation(dossier, False, "n° d'ordre absent : situation non rattachable")
    if not numeros:
        return

    res = await db.execute(
        select(TableauDossier)
        .options(selectinload(TableauDossier.import_ref))
        .where(
            TableauDossier.organisation_id.in_({d.organisation_id for d in dossiers}),
            TableauDossier.exercice.in_({d.exercice for d in dossiers}),
            TableauDossier.numero_ordre.in_(numeros),
        )
    )
    groupes: dict[tuple[int, str, str], list[TableauDossier]] = {}
    for candidat in res.scalars().all():
        numero = _norm_numero_ordre(candidat.numero_ordre)
        if numero:
            groupes.setdefault((candidat.organisation_id, candidat.exercice, numero), []).append(candidat)

    for candidats in groupes.values():
        courante = max(candidats, key=_rang_fraicheur)
        date_situation = (
            courante.import_ref.date_situation.isoformat()
            if courante.import_ref and courante.import_ref.date_situation
            else None
        )
        for candidat in candidats:
            est_courante = candidat.id == courante.id
            _set_situation(
                candidat,
                est_courante,
                "situation la plus récente pour ce membre sur l'exercice"
                if est_courante
                else "remplacée par une situation plus récente",
                import_id=courante.import_id,
                date_situation=date_situation,
            )


# Une décision de commission ne fixe une conclusion que si elle en nomme une ;
# les autres (« reporté », « à revoir »…) sont tracées sans rien trancher.
_CONCLUSIONS_DECIDEES = {
    "INSCRIT": verdict_engine.INSCRIT,
    "NONINSCRIT": verdict_engine.NON_INSCRIT,
    "ADELIBERER": verdict_engine.A_DELIBERER,
}


def _conclusion_de_decision(decision: str | None) -> str | None:
    """Conclusion fixée par une décision de commission, si elle en fixe une."""
    if not decision:
        return None
    sans_accent = unicodedata.normalize("NFKD", str(decision).upper())
    cle = "".join(c for c in sans_accent if c.isalnum())
    return _CONCLUSIONS_DECIDEES.get(cle)


def _decision_json(decision: TableauDecision) -> dict[str, Any]:
    return {
        "decision_id": decision.id,
        "dossier_id": decision.dossier_id,
        "type_decision": decision.type_decision,
        "decision": decision.decision,
        "motif": decision.motif,
        "prise_le": decision.created_at.isoformat() if decision.created_at else None,
    }


async def _decisions_par_membre(
    db: AsyncSession,
    organisation_id: int,
    exercice: str,
) -> dict[str, list[TableauDecision]]:
    """Décisions de la commission rattachées au membre, et non au seul import délibéré.

    Une décision est prise sur le dossier d'un import donné ; elle engage pourtant
    le membre pour tout l'exercice. On la retrouve donc par n° d'ordre, afin qu'un
    import ultérieur ne la fasse pas disparaître. La plus récente prime.
    """
    res = await db.execute(
        select(TableauDecision, TableauDossier.numero_ordre)
        .join(TableauDossier, TableauDecision.dossier_id == TableauDossier.id)
        .where(
            TableauDecision.organisation_id == organisation_id,
            TableauDossier.exercice == exercice,
        )
        .order_by(TableauDecision.created_at.desc(), TableauDecision.id.desc())
    )
    groupes: dict[str, list[TableauDecision]] = {}
    for decision, numero_ordre in res.all():
        numero = _norm_numero_ordre(numero_ordre)
        if numero:
            groupes.setdefault(numero, []).append(decision)
    return groupes


def _appliquer_decisions(
    dossiers: list[TableauDossier],
    verdicts: dict[int, dict],
    decisions_par_membre: dict[str, list[TableauDecision]],
) -> dict[int, dict]:
    """Fait primer ce que la commission a tranché sur le verdict automatique.

    Le verdict écarté est conservé : si les données importées depuis la
    délibération conduiraient désormais à une autre conclusion, la divergence est
    signalée pour que la commission puisse revoir sa décision — mais jamais
    appliquée dans son dos.
    """
    appliquees: dict[int, dict] = {}
    for dossier in dossiers:
        numero = _norm_numero_ordre(dossier.numero_ordre)
        retenue = conclusion_decidee = None
        for prise in decisions_par_membre.get(numero or "", []):
            conclusion = _conclusion_de_decision(prise.decision)
            if conclusion:
                retenue, conclusion_decidee = prise, conclusion
                break
        if not retenue:
            continue

        automatique = verdicts.get(dossier.id, {})
        conclusion_auto = automatique.get("conclusion")
        verdicts[dossier.id] = {
            **automatique,
            "conclusion": conclusion_decidee,
            "motif": retenue.motif or f"Décision de la commission ({retenue.type_decision})",
        }
        appliquees[dossier.id] = {
            **_decision_json(retenue),
            "verdict_automatique": conclusion_auto,
            "diverge": bool(conclusion_auto) and conclusion_auto != conclusion_decidee,
        }
    return appliquees


def _valider_lignes(rows: list[dict]) -> list[dict]:
    """Contrôles non bloquants ligne par ligne -> [{ligne, champ, message}]."""
    errors: list[dict] = []
    for idx, row in enumerate(rows):
        ligne = idx + 2  # +1 en-tête, +1 base 1
        nom = row.get("nom") or "?"
        if not row.get("numero_ordre"):
            errors.append({"ligne": ligne, "champ": "numero_ordre",
                           "message": f"N° d'ordre manquant ({nom})"})
        if row.get("categorie") in (None, "", "Inconnu"):
            errors.append({"ligne": ligne, "champ": "categorie",
                           "message": f"Catégorie non reconnue ({nom})"})
    return errors


async def import_excel(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    file_name: str,
    content: bytes,
    exercice: str,
    date_situation: date | None = None,
) -> ImportOutcome:
    rows, errors = parse_excel_bytes(content, exercice)
    situation_date = date_situation or _today()

    imp = TableauImport(
        organisation_id=organisation_id,
        user_id=user.id,
        exercice=exercice,
        date_situation=situation_date,
        file_name=file_name,
        status="processing" if not errors else "error",
        total_rows=len(rows),
        imported_rows=0,
        error_message="; ".join(errors) if errors else None,
    )
    db.add(imp)
    await db.flush()

    # Erreur bloquante : fichier illisible / en-tête introuvable
    if errors and not rows:
        await db.commit()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="; ".join(errors))

    for row in rows:
        row["numero_ordre"] = _norm_numero_ordre(row.get("numero_ordre")) or row.get("numero_ordre")

    # Une seule requête ramène la situation précédente de tous les membres du fichier.
    rang_import = (situation_date, imp.created_at, imp.id)
    numeros = {n for n in (_norm_numero_ordre(r.get("numero_ordre")) for r in rows) if n}
    precedentes = await _situations_precedentes(db, organisation_id, exercice, numeros, rang_import)
    decisions = await _decisions_par_membre(db, organisation_id, exercice)
    deja_connus = await _numeros_deja_connus(db, organisation_id, numeros, imp.id)
    total_reprises = 0
    total_decisions = 0
    nouveaux_vus: set[str] = set()

    dossiers: list[TableauDossier] = []
    for row in rows:
        annee_inscription, anciennete_annees = _anciennete_annees(row.get("numero_ordre"), exercice)
        numero = _norm_numero_ordre(row.get("numero_ordre"))
        precedente = precedentes.get(numero) if numero else None
        reprises = _reprendre_valeurs_manquantes(row, precedente) if precedente else []
        total_reprises += len(reprises)

        raw = dict(row.get("raw_data") or {})
        if reprises:
            raw["situation"] = {**(raw.get("situation") or {}), "reprises": reprises}
        if numero:
            nouveau = numero not in deja_connus
            raw["situation"] = {**(raw.get("situation") or {}), "nouveau": nouveau}
            if nouveau:
                nouveaux_vus.add(numero)
        prises = decisions.get(numero or "")
        if prises:
            # La commission a déjà statué sur ce membre : la nouvelle situation en
            # porte la mémoire, pour qu'aucun import ne l'efface en silence.
            raw["decisions"] = [_decision_json(p) for p in prises]
            total_decisions += 1
        raw["source_import"] = {
            "file_name": file_name,
            "exercice": exercice,
            "import_id": imp.id,
            "date_situation": situation_date.isoformat(),
        }
        row["raw_data"] = raw

        dossier = TableauDossier(
            organisation_id=organisation_id,
            import_id=imp.id,
            annee_inscription=annee_inscription,
            anciennete_annees=anciennete_annees,
            **{k: v for k, v in row.items() if k != "id"},
        )
        db.add(dossier)
        dossiers.append(dossier)

    await db.flush()
    await _marquer_situations_courantes(db, dossiers)

    imp.imported_rows = len(rows)
    imp.status = "completed"
    await db.commit()

    row_errors = _valider_lignes(rows)
    return ImportOutcome(
        imp=imp,
        imported=len(rows),
        updated=0,
        skipped=0,
        total=len(rows),
        errors=row_errors,
        reprises=total_reprises,
        decisions_reportees=total_decisions,
        nouveaux_membres=len(nouveaux_vus),
    )


async def get_base_tableau(
    db: AsyncSession,
    organisation_ids: list[int],
    exercice: str | None = None,
    anomalie_only: bool = False,
    national: bool = False,
) -> dict[str, Any]:
    """Base consolidée du Tableau pour un exercice.

    Chaque conseil tient sa propre base ; le Conseil National peut demander la
    consolidation de tous les conseils à la fois.
    """
    exercice = exercice or await dernier_exercice(db, organisation_ids)
    if not exercice:
        return {
            "exercice": "",
            "national": national,
            "organisations": organisation_ids,
            "total_membres": 0,
            "membres_sans_numero": 0,
            "imports_couverts": [],
            "dossiers": [],
        }

    dossiers = await list_base_tableau(db, organisation_ids, exercice, anomalie_only=anomalie_only)
    return {
        "exercice": exercice,
        "national": national,
        "organisations": sorted({d.organisation_id for d in dossiers}) or organisation_ids,
        "total_membres": len(dossiers),
        "membres_sans_numero": sum(1 for d in dossiers if not d.numero_ordre),
        "imports_couverts": sorted({d.import_id for d in dossiers}),
        "dossiers": dossiers,
    }

async def run_analyse(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    import_id: int,
) -> TableauAnalyse:
    imp = await get_import(db, organisation_id, import_id)
    if imp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import introuvable")

    dossier_rows = await list_dossiers(db, organisation_id, import_id=import_id)
    return await _analyser_dossiers(db, organisation_id, imp, dossier_rows)


async def run_analyse_base(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    exercice: str | None = None,
) -> TableauAnalyse:
    """Analyse la base consolidée de l'exercice plutôt qu'un fichier isolé.

    Dès que la situation d'un exercice s'étale sur plusieurs imports, délibérer
    sur un seul fichier revient à juger sur des données périmées. L'analyse porte
    donc sur la situation qui fait foi pour chaque membre ; elle est rattachée à
    l'import le plus récent de l'exercice, qui en porte les réglages.
    """
    exercice = exercice or await dernier_exercice(db, [organisation_id])
    if not exercice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Aucun import pour ce conseil.")

    res = await db.execute(
        select(TableauImport)
        .where(TableauImport.organisation_id == organisation_id, TableauImport.exercice == exercice)
        .order_by(TableauImport.date_situation.desc().nullslast(), TableauImport.created_at.desc())
        .limit(1)
    )
    imp = res.scalars().first()
    if imp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Aucun import pour l'exercice {exercice}.")

    dossier_rows = await list_base_tableau(db, [organisation_id], exercice)
    return await _analyser_dossiers(db, organisation_id, imp, dossier_rows)


async def _analyser_dossiers(
    db: AsyncSession,
    organisation_id: int,
    imp: TableauImport,
    dossier_rows: list[TableauDossier],
) -> TableauAnalyse:
    """Verdict, anomalies et statistiques sur un ensemble de dossiers donné."""
    exercice_annee = _exercice_annee(imp.exercice)
    reglages = verdict_engine.TableauReglages.from_dict((imp.metadata_json or {}).get("reglages"))
    import_id = imp.id

    dossier_dicts = []
    for d in dossier_rows:
        raw = d.raw_data or {}
        dossier_dicts.append({
            "id": d.id,
            "numero_ordre": d.numero_ordre,
            "nom": d.nom,
            "prenom": d.prenom,
            "categorie": d.categorie,
            "cotisation_payee": d.cotisation_payee,
            "heures_forco": float(d.heures_forco) if d.heures_forco is not None else None,
            "assurance": d.assurance,
            "chiffre_affaires": d.chiffre_affaires,
            "hformation": raw.get("hformation"),
            "anciennete": d.anciennete,
            "age": d.age,
        })

    verdicts = {
        dd["id"]: verdict_engine.evaluer(dd, exercice_annee, reglages) for dd in dossier_dicts
    }
    # Ce que la commission a tranché prime sur le verdict automatique, et doit le
    # faire avant le calcul des statistiques pour que les deux concordent.
    decisions = await _decisions_par_membre(db, organisation_id, imp.exercice)
    decisions_appliquees = _appliquer_decisions(dossier_rows, verdicts, decisions)

    anomaly_dicts = detect_anomalies(dossier_dicts, exercice_annee)
    stats = compute_analyse_stats(dossier_dicts, anomaly_dicts, verdicts)

    existing = await get_analyse_for_import(db, organisation_id, import_id)
    if existing:
        for k, v in stats.items():
            setattr(existing, k, v)
        existing.status = "completed"
        existing.updated_at = datetime.now(timezone.utc)
        analyse = existing
    else:
        analyse = TableauAnalyse(
            organisation_id=organisation_id,
            import_id=import_id,
            exercice=imp.exercice,
            status="completed",
            **stats,
        )
        db.add(analyse)

    await db.flush()

    for d in dossier_rows:
        d.anomalie_detectee = any(a["dossier_id"] == d.id for a in anomaly_dicts)
        v = verdicts.get(d.id, {})
        conclusion = v.get("conclusion") or "analysé"
        # colonnes dédiées
        d.conclusion = conclusion
        d.conclusion_motif = v.get("motif")
        d.statut_dossier = conclusion  # compat UI existante
        # exemptions conservées dans raw_data (JSONB)
        raw = dict(d.raw_data or {})
        raw["exemptions"] = v.get("exemptions")
        if d.id in decisions_appliquees:
            raw["decision_appliquee"] = decisions_appliquees[d.id]
        else:
            raw.pop("decision_appliquee", None)
        d.raw_data = raw
        flag_modified(d, "raw_data")

    # On ne remplace que les anomalies des dossiers réellement réanalysés.
    res = await db.execute(
        select(TableauAnomalie)
        .join(TableauDossier, TableauAnomalie.dossier_id == TableauDossier.id)
        .where(
            TableauDossier.organisation_id == organisation_id,
            TableauAnomalie.dossier_id.in_([d.id for d in dossier_rows]),
        )
    )
    for old in res.scalars().all():
        await db.delete(old)
    await db.flush()

    for a_dict in anomaly_dicts:
        db.add(TableauAnomalie(
            organisation_id=organisation_id,
            **a_dict,
        ))

    await db.commit()
    return analyse


async def run_comparison(
    db: AsyncSession,
    organisation_id: int,
    exercice_a: str,
    exercice_b: str,
) -> dict:
    dossiers_a_rows = await list_dossiers(db, organisation_id, exercice=exercice_a)
    dossiers_b_rows = await list_dossiers(db, organisation_id, exercice=exercice_b)

    if not dossiers_a_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Aucun dossier pour l'exercice {exercice_a}")
    if not dossiers_b_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Aucun dossier pour l'exercice {exercice_b}")

    def to_dict(d: TableauDossier) -> dict:
        return {"id": d.id, "nom": d.nom, "prenom": d.prenom, "categorie": d.categorie}

    return compare_exercices(
        [to_dict(d) for d in dossiers_a_rows],
        [to_dict(d) for d in dossiers_b_rows],
        exercice_a,
        exercice_b,
    )


async def create_decision(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    payload: TableauDecisionCreate,
) -> TableauDecision:
    decision = TableauDecision(
        organisation_id=organisation_id,
        user_id=user.id,
        dossier_id=payload.dossier_id,
        type_decision=payload.type_decision,
        decision=payload.decision,
        motif=payload.motif,
        observations=payload.observations,
    )
    db.add(decision)
    await db.commit()
    return decision


async def set_reglages(
    db: AsyncSession,
    organisation_id: int,
    import_id: int,
    reglages: dict,
) -> dict:
    """Enregistre les réglages de délibération sur un import (metadata_json)."""
    imp = await get_import(db, organisation_id, import_id)
    if imp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import introuvable")
    meta = dict(imp.metadata_json or {})
    current = dict(meta.get("reglages") or {})
    current.update({k: v for k, v in reglages.items() if v is not None})
    # valider via le dataclass (ignore les clés inconnues)
    validated = verdict_engine.TableauReglages.from_dict(current)
    meta["reglages"] = validated.__dict__
    imp.metadata_json = meta
    flag_modified(imp, "metadata_json")
    await db.commit()
    return meta["reglages"]


async def export_tableau(
    db: AsyncSession,
    organisation_id: int,
    import_id: int,
    organisation_nom: str = "CONSEIL PROVINCIAL",
) -> tuple[bytes, str]:
    """Génère le tableau provincial de sortie (.xlsx). Renvoie (octets, nom_fichier)."""
    from .exporter import build_workbook

    imp = await get_import(db, organisation_id, import_id)
    if imp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import introuvable")

    exercice_annee = _exercice_annee(imp.exercice)
    reglages = verdict_engine.TableauReglages.from_dict((imp.metadata_json or {}).get("reglages"))

    dossier_rows = await list_dossiers(db, organisation_id, import_id=import_id)
    dossiers = [
        {
            "numero_ordre": d.numero_ordre,
            "nom": d.nom,
            "prenom": d.prenom,
            "categorie": d.categorie,
            "cotisation_payee": d.cotisation_payee,
            "assurance": d.assurance,
            "chiffre_affaires": d.chiffre_affaires,
            "heures_forco": float(d.heures_forco) if d.heures_forco is not None else None,
            "sexe": d.sexe,
            "date_naissance": d.date_naissance.isoformat() if d.date_naissance else None,
            "age": d.age,
            "nif": d.nif,
            "anciennete": d.anciennete,
            "telephone": d.telephone,
            "email": d.email,
            "cabinet": d.cabinet,
            "raw_data": d.raw_data or {},
        }
        for d in dossier_rows
    ]
    content = build_workbook(dossiers, imp.exercice, reglages, exercice_annee, organisation_nom)
    fname = f"Tableau_{imp.exercice}_{import_id}.xlsx"
    return content, fname


async def create_report(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    payload: TableauReportCreate,
) -> TableauReport:
    imp = await get_import(db, organisation_id, payload.import_id)
    if imp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import introuvable")

    analyse = await get_analyse_for_import(db, organisation_id, payload.import_id)
    anomaly_rows = await list_anomalies(db, organisation_id, import_id=payload.import_id)
    anomaly_dicts = [
        {"dossier_id": a.dossier_id, "type_anomalie": a.type_anomalie, "gravite": a.gravite, "description": a.description}
        for a in anomaly_rows
    ]

    stats = {
        "total_dossiers": analyse.total_dossiers if analyse else 0,
        "dossiers_complets": analyse.dossiers_complets if analyse else 0,
        "dossiers_incomplets": analyse.dossiers_incomplets if analyse else 0,
        "anomalies_count": analyse.anomalies_count if analyse else 0,
        "doublons_count": analyse.doublons_count if analyse else 0,
        "cotisations_non_payees": analyse.cotisations_non_payees if analyse else 0,
        "heures_forco_insuffisantes": analyse.heures_forco_insuffisantes if analyse else 0,
        "assurances_manquantes": analyse.assurances_manquantes if analyse else 0,
        "stats_json": analyse.stats_json if analyse else {},
    }

    contenu = generate_analyse_report(payload.exercice, stats, anomaly_dicts, payload.instructions)

    report = TableauReport(
        organisation_id=organisation_id,
        user_id=user.id,
        import_id=payload.import_id,
        exercice=payload.exercice,
        type_rapport=payload.type_rapport,
        titre=payload.titre,
        contenu=contenu,
        format_sortie="text",
        status="draft",
    )
    db.add(report)
    await db.commit()
    return report


async def create_pv(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    payload: TableauPVCreate,
) -> TableauReport:
    imp = await get_import(db, organisation_id, payload.import_id)
    if imp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import introuvable")

    analyse = await get_analyse_for_import(db, organisation_id, payload.import_id)
    stats = {
        "total_dossiers": analyse.total_dossiers if analyse else 0,
        "dossiers_complets": analyse.dossiers_complets if analyse else 0,
        "anomalies_count": analyse.anomalies_count if analyse else 0,
    }

    res = await db.execute(
        select(TableauDecision).where(
            TableauDecision.organisation_id == organisation_id,
        ).order_by(TableauDecision.created_at.desc()).limit(50)
    )
    decisions = [
        {"dossier_id": d.dossier_id, "type_decision": d.type_decision, "decision": d.decision, "motif": d.motif}
        for d in res.scalars().all()
    ]

    contenu = generate_pv(payload.exercice, stats, decisions, payload.instructions)

    report = TableauReport(
        organisation_id=organisation_id,
        user_id=user.id,
        import_id=payload.import_id,
        exercice=payload.exercice,
        type_rapport="pv",
        titre=f"Procès-verbal Commission Tableau — {payload.exercice}",
        contenu=contenu,
        format_sortie="text",
        status="draft",
    )
    db.add(report)
    await db.commit()
    return report
