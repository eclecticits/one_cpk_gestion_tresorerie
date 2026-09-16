from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import unicodedata
import re
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.models.user import User
from app.models.organisation import Organisation
from . import verdict as verdict_engine
from .audit import record_tableau_audit
from .analyzer import compute_analyse_stats, detect_anomalies
from .comparison import compare_exercices
from .excel_import import parse_excel_bytes
from .models import (
    TableauAnalyse,
    TableauAnomalie,
    TableauDecision,
    TableauDossier,
    TableauImport,
    TableauCaDeclaration,
    TableauInsuranceDeclaration,
    TableauMemberIdentity,
    TableauPersonneMoraleSnapshot,
    TableauPersonnePhysiqueSnapshot,
    TableauReport,
    TableauSourceRow,
)
from .official_reference import OfficialExpertRecord, list_official_experts_read_only
from .source_adapters import SOURCE_TYPES, file_sha256, parse_source_excel, row_sha256
from .report_generator import generate_analyse_report, generate_pv
from .repository import (
    dernier_exercice,
    get_analyse_for_import,
    get_base_summary,
    get_import,
    get_stats,
    list_anomalies,
    list_base_tableau,
    list_dossiers,
    list_imports,
    list_reports,
)
from .schemas import TableauDecisionCreate, TableauDossierCorrection, TableauPVCreate, TableauReportCreate


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
    duplicate_detected: bool = False
    source_type: str = "tableau"


@dataclass
class PreparatoryTableauRow:
    identity_id: int
    organisation_id: int
    numero_ordre: str
    member_kind: str
    person_kind: str
    nom_denomination: str | None
    statut_professionnel: str | None
    tableau_category: str
    actif: bool | None
    cabinet_attache: str | None = None
    nif: str | None = None
    nom_employeur: str | None = None
    ca_present: bool = False
    ca_declaration_count: int = 0
    annees_ca_connues: list[int] = field(default_factory=list)
    devises_ca_connues: list[str] = field(default_factory=list)
    derniere_date_situation_ca: date | None = None
    insurance_status: str = "UNKNOWN"
    assure_source: bool | None = None
    insurance_source_mismatch: bool = False
    source_dates: dict[str, date | None] = field(default_factory=dict)
    anomaly_codes: list[str] = field(default_factory=list)
    projection_status: str = "READY"


@dataclass
class PreparatoryTableauProjection:
    evaluation_date: date
    rows: list[PreparatoryTableauRow] = field(default_factory=list)
    orphan_ca: list[TableauCaDeclaration] = field(default_factory=list)
    orphan_insurance: list[TableauInsuranceDeclaration] = field(default_factory=list)


# Les catégories corrigeables sont celles que le barème de délibération sait juger.
# Une liste tenue à part finissait par diverger : « SEC » y manquait, si bien
# qu'une société d'expertise ne pouvait plus être corrigée sans changer de
# catégorie.
_CATEGORIES_CONNUES = frozenset(verdict_engine.CATEGORIE_CRITERES)


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


def _date_situation_par_defaut(exercice: str) -> date:
    """Valeur de compatibilité pour les appels internes antérieurs au champ requis."""
    annees = [int(v) for v in re.findall(r"20\d{2}", str(exercice or ""))]
    return date(max(annees), 12, 31) if annees else _today()


_ORDER_PATTERN = re.compile(r"^(EC|SEC)/\d{2}\.\d{5}$")


def _classification_from_order(numero_ordre: str | None) -> tuple[str | None, str | None]:
    """Retourne le type structurel sans corriger la valeur source."""
    numero = _norm_numero_ordre(numero_ordre)
    if not numero or not _ORDER_PATTERN.fullmatch(numero):
        return None, None
    prefix = numero.split("/", 1)[0]
    return prefix, "PHYSIQUE" if prefix == "EC" else "MORALE"


def _normaliser_bool_source(value: Any) -> tuple[bool | None, bool]:
    if value is None or str(value).strip() == "":
        return None, False
    token = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().strip().lower()
    if token in {"oui", "o", "yes", "y", "1", "true", "vrai", "x"}:
        return True, False
    if token in {"non", "n", "no", "0", "false", "faux"}:
        return False, False
    return None, True


def _normaliser_decimal_source(value: Any) -> tuple[Decimal | None, bool]:
    if value is None or str(value).strip() == "":
        return None, False
    text = str(value).strip().replace(" ", "").replace("\u202f", "").replace(",", ".")
    try:
        return Decimal(text), False
    except (InvalidOperation, ValueError):
        return None, True


def _normaliser_ca_decimal(value: Any) -> tuple[Decimal | None, bool]:
    """Parse un montant sans perdre la valeur source."""
    if value is None or str(value).strip() == "":
        return None, False
    text = str(value).strip().replace(" ", "").replace("\u202f", "")
    if "," in text and "." in text:
        # Le dernier séparateur est généralement le séparateur décimal.
        decimal_sep = "," if text.rfind(",") > text.rfind(".") else "."
        thousands_sep = "." if decimal_sep == "," else ","
        text = text.replace(thousands_sep, "").replace(decimal_sep, ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return Decimal(text), False
    except (InvalidOperation, ValueError):
        return None, True


def _normaliser_annee_ca(value: Any) -> tuple[int | None, bool]:
    if value is None or str(value).strip() == "":
        return None, True
    try:
        year = int(str(value).strip())
    except (TypeError, ValueError):
        return None, True
    return (year, False) if 1900 <= year <= 2200 and len(str(year)) == 4 else (None, True)


def _normaliser_devise(value: Any) -> tuple[str | None, bool]:
    if value is None or str(value).strip() == "":
        return None, True
    value = str(value).strip().upper()
    return (value, False) if re.fullmatch(r"[A-Z]{3}", value) else (value, True)


def _normaliser_date_source(value: Any) -> tuple[date | None, bool]:
    if value is None or str(value).strip() == "":
        return None, False
    if isinstance(value, datetime):
        return value.date(), False
    if isinstance(value, date):
        return value, False
    try:
        return datetime.fromisoformat(str(value).strip()).date(), False
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date(), False
        except ValueError:
            continue
    return None, True


def _normaliser_statut(value: Any) -> str | None:
    token = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    token = " ".join(token.replace("_", " ").replace("-", " ").split())
    return {
        "en cabinet": "EN_CABINET",
        "cabinet": "EN_CABINET",
        "independant": "INDEPENDANT",
        "salarie": "SALARIE",
    }.get(token)


def _looks_like_sec(value: Any) -> bool:
    return bool(value and re.fullmatch(r"SEC/\d{2}\.\d{5}", _norm_numero_ordre(str(value)) or ""))


def _looks_like_nif(value: Any) -> bool:
    return bool(value and re.fullmatch(r"[A-Z]\d{7}[A-Z]", str(value).strip().upper()))


def _exercice_annee(exercice: str | None) -> int | None:
    m = re.search(r"(20\d{2})", str(exercice or ""))
    return int(m.group(1)) if m else None


def valider_date_situation(exercice: str, date_situation: date) -> None:
    """Refuse une date qui ne peut pas appartenir à l'exercice annoncé."""
    annees = {int(v) for v in re.findall(r"20\d{2}", str(exercice or ""))}
    if not annees:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="L'exercice doit contenir une année sur quatre chiffres.",
        )
    if date_situation.year not in annees:
        attendues = ", ".join(str(v) for v in sorted(annees))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"La date de situation doit appartenir à l'exercice ({attendues}).",
        )


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


async def _invalider_analyses(
    db: AsyncSession,
    organisation_id: int,
    exercice: str,
    *,
    scopes: set[str] | None = None,
    dossier_id: int | None = None,
    import_id: int | None = None,
) -> None:
    """Marque les calculs touchés comme obsolètes sans effacer leur historique."""
    q = select(TableauAnalyse).where(
        TableauAnalyse.organisation_id == organisation_id,
        TableauAnalyse.exercice == exercice,
        TableauAnalyse.status == "completed",
    )
    if scopes:
        q = q.where(TableauAnalyse.scope.in_(scopes))
    if dossier_id is not None or import_id is not None:
        cibles = []
        if dossier_id is not None:
            cibles.append(TableauAnalyse.source_dossier_ids.contains([dossier_id]))
        if import_id is not None:
            cibles.append(TableauAnalyse.import_id == import_id)
        q = q.where(or_(*cibles))
    for analyse in (await db.execute(q)).scalars().all():
        analyse.status = "stale"
        analyse.updated_at = datetime.now(timezone.utc)


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


def _cle_decision(numero_ordre: str | None, nom: str | None, prenom: str | None) -> str | None:
    """Identité d'un membre pour lui rattacher une décision de commission.

    Le n° d'ordre fait foi. À défaut — cas des dossiers « à compléter », qui sont
    précisément ceux que la commission délibère — le nom prend le relais : sans
    cela, une décision prise sur un membre sans numéro n'était ni reportée d'un
    import à l'autre, ni reprise au procès-verbal.
    """
    numero = _norm_numero_ordre(numero_ordre)
    if numero:
        return f"ordre:{numero}"
    nom_seul = " ".join(str(nom or "").split()).lower()
    if not nom_seul:
        return None
    return f"nom:{nom_seul}|{' '.join(str(prenom or '').split()).lower()}"


def _cles_homonymes(cles: Iterable[str | None]) -> set[str]:
    """Clés de repli portées par plusieurs personnes du lot examiné.

    Deux homonymes sans n° d'ordre ne sont pas distinguables : plutôt que
    d'appliquer à l'un la décision prise sur l'autre, on n'applique rien et le
    procès-verbal signale la décision comme non rattachée.
    """
    vues: dict[str, int] = {}
    for cle in cles:
        if cle and cle.startswith("nom:"):
            vues[cle] = vues.get(cle, 0) + 1
    return {cle for cle, total in vues.items() if total > 1}


async def _decisions_par_membre(
    db: AsyncSession,
    organisation_id: int,
    exercice: str,
) -> dict[str, list[TableauDecision]]:
    """Décisions de la commission rattachées au membre, et non au seul import délibéré.

    Une décision est prise sur le dossier d'un import donné ; elle engage pourtant
    le membre pour tout l'exercice. On la retrouve donc par son identité — n°
    d'ordre, ou nom à défaut — afin qu'un import ultérieur ne la fasse pas
    disparaître. La plus récente prime.
    """
    res = await db.execute(
        select(TableauDecision, TableauDossier.numero_ordre, TableauDossier.nom, TableauDossier.prenom)
        .join(TableauDossier, TableauDecision.dossier_id == TableauDossier.id)
        .where(
            TableauDecision.organisation_id == organisation_id,
            TableauDossier.exercice == exercice,
        )
        .order_by(TableauDecision.created_at.desc(), TableauDecision.id.desc())
    )
    groupes: dict[str, list[TableauDecision]] = {}
    for decision, numero_ordre, nom, prenom in res.all():
        cle = _cle_decision(numero_ordre, nom, prenom)
        if cle:
            groupes.setdefault(cle, []).append(decision)
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
    cles = {d.id: _cle_decision(d.numero_ordre, d.nom, d.prenom) for d in dossiers}
    homonymes = _cles_homonymes(cles.values())

    appliquees: dict[int, dict] = {}
    for dossier in dossiers:
        cle = cles[dossier.id]
        if not cle or cle in homonymes:
            continue
        retenue = conclusion_decidee = None
        for prise in decisions_par_membre.get(cle, []):
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
    content_hash = file_sha256(content)
    duplicate_res = await db.execute(
        select(TableauImport).where(
            TableauImport.organisation_id == organisation_id,
            TableauImport.source_type == "tableau",
            TableauImport.date_situation == (date_situation or _date_situation_par_defaut(exercice)),
            TableauImport.file_sha256 == content_hash,
        ).order_by(TableauImport.id.desc()).limit(1)
    )
    duplicate = duplicate_res.scalars().first()
    if duplicate is not None:
        return ImportOutcome(imp=duplicate, total=duplicate.total_rows, duplicate_detected=True)

    rows, errors = parse_excel_bytes(content, exercice)
    situation_date = date_situation or _date_situation_par_defaut(exercice)

    if date_situation is not None:
        valider_date_situation(exercice, date_situation)

    # Les règles appartiennent à l'exercice. Un import partiel plus récent ne doit
    # pas rétablir silencieusement les valeurs par défaut.
    reglages_res = await db.execute(
        select(TableauImport.metadata_json)
        .where(
            TableauImport.organisation_id == organisation_id,
            TableauImport.exercice == exercice,
        )
        .order_by(TableauImport.date_situation.desc().nullslast(), TableauImport.created_at.desc())
    )
    reglages_herites = None
    for metadata in reglages_res.scalars().all():
        if (metadata or {}).get("reglages"):
            reglages_herites = dict(metadata["reglages"])
            break

    imp = TableauImport(
        organisation_id=organisation_id,
        user_id=user.id,
        exercice=exercice,
        date_situation=situation_date,
        source_type="tableau",
        file_name=file_name,
        file_sha256=content_hash,
        file_size=len(content),
        status="processing" if not errors else "error",
        total_rows=len(rows),
        imported_rows=0,
        accepted_rows=0,
        rejected_rows=0,
        error_count=len(errors),
        error_message="; ".join(errors) if errors else None,
        metadata_json={"reglages": reglages_herites} if reglages_herites else None,
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
    homonymes_import = _cles_homonymes(
        _cle_decision(r.get("numero_ordre"), r.get("nom"), r.get("prenom")) for r in rows
    )
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
        cle_decision = _cle_decision(row.get("numero_ordre"), row.get("nom"), row.get("prenom"))
        prises = decisions.get(cle_decision) if cle_decision and cle_decision not in homonymes_import else None
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
    await _invalider_analyses(db, organisation_id, exercice, scopes={"base"})

    row_errors = _valider_lignes(rows)
    imp.imported_rows = len(rows)
    imp.accepted_rows = len(rows)
    imp.rejected_rows = 0
    imp.error_count = len(row_errors)
    imp.status = "completed"
    # Le snapshot brut est conservé même pour l'ancien format Tableau. Si le
    # parseur générique ne reconnaît pas une feuille, le flux historique reste
    # prioritaire et l'import métier n'est pas bloqué.
    raw_snapshot = parse_source_excel(content, "tableau")
    for parsed in raw_snapshot.rows:
        db.add(TableauSourceRow(
            organisation_id=organisation_id,
            import_id=imp.id,
            feuille=parsed.feuille,
            line_number=parsed.line_number,
            raw_data=parsed.raw_data,
            row_hash=row_sha256(parsed.raw_data),
            normalization_status="error" if parsed.errors else "accepted",
            normalization_errors=parsed.errors or None,
            business_key_candidate=parsed.business_key_candidate,
        ))
    await db.commit()

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
        source_type="tableau",
    )


async def import_source_snapshot(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    file_name: str,
    content: bytes,
    source_type: str,
    exercice: str,
    date_situation: date,
) -> ImportOutcome:
    """Importe une source détaillée jusqu'au snapshot/contrôle uniquement."""
    if source_type not in SOURCE_TYPES or source_type == "tableau":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Type de source détaillée invalide")
    valider_date_situation(exercice, date_situation)
    digest = file_sha256(content)
    existing_res = await db.execute(
        select(TableauImport).where(
            TableauImport.organisation_id == organisation_id,
            TableauImport.source_type == source_type,
            TableauImport.date_situation == date_situation,
            TableauImport.file_sha256 == digest,
        ).order_by(TableauImport.id.desc()).limit(1)
    )
    existing = existing_res.scalars().first()
    if existing is not None:
        return ImportOutcome(imp=existing, total=existing.total_rows, duplicate_detected=True, source_type=source_type)

    parsed = parse_source_excel(content, source_type)
    official_rows = (
        await list_official_experts_read_only(db)
        if source_type in {"personnes_physiques", "personnes_morales"}
        else []
    )
    imp = TableauImport(
        organisation_id=organisation_id,
        user_id=user.id,
        exercice=exercice,
        date_situation=date_situation,
        source_type=source_type,
        file_name=file_name,
        file_sha256=digest,
        file_size=len(content),
        status="processing",
        total_rows=len(parsed.rows),
        imported_rows=0,
        accepted_rows=0,
        rejected_rows=0,
        error_count=len(parsed.errors),
        error_message="; ".join(str(item.get("message", "")) for item in parsed.errors) or None,
        metadata_json={"pipeline": "raw_snapshot_only", "source_type": source_type},
    )
    db.add(imp)
    try:
        await db.flush()
        source_row_objects: list[tuple[Any, TableauSourceRow]] = []
        for parsed_row in parsed.rows:
            has_error = bool(parsed_row.errors)
            source_row = TableauSourceRow(
                organisation_id=organisation_id,
                import_id=imp.id,
                feuille=parsed_row.feuille,
                line_number=parsed_row.line_number,
                raw_data=parsed_row.raw_data,
                row_hash=row_sha256(parsed_row.raw_data),
                normalization_status="error" if has_error else "accepted",
                normalization_errors=parsed_row.errors or None,
                business_key_candidate=parsed_row.business_key_candidate,
            )
            db.add(source_row)
            source_row_objects.append((parsed_row, source_row))
        await db.flush()

        if source_type in {"personnes_physiques", "personnes_morales", "chiffres_affaires", "assurances"}:
            for parsed_row, source_row in source_row_objects:
                if source_type == "chiffres_affaires":
                    await _materialize_ca_declaration(db, imp=imp, parsed_row=parsed_row, source_row=source_row)
                elif source_type == "assurances":
                    await _materialize_insurance_declaration(db, imp=imp, parsed_row=parsed_row, source_row=source_row)
                else:
                    await _materialize_member_snapshot(
                        db,
                        imp=imp,
                        source_type=source_type,
                        parsed_row=parsed_row,
                        source_row=source_row,
                        official_rows=official_rows,
                    )

        rejected = sum(1 for _parsed, source_row in source_row_objects if source_row.normalization_status == "blocking")
        accepted = len(source_row_objects) - rejected
        imp.accepted_rows = accepted
        imp.rejected_rows = rejected
        imp.imported_rows = accepted
        imp.status = "error" if not parsed.rows else ("partial" if rejected or parsed.errors else "completed")
        imp.error_count = len(parsed.errors) + rejected
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return ImportOutcome(
        imp=imp,
        imported=accepted,
        skipped=rejected,
        total=len(parsed.rows),
        errors=parsed.errors + [error for row in parsed.rows for error in row.errors],
        duplicate_detected=False,
        source_type=source_type,
    )


def _extract_order_from_member(value: Any) -> str | None:
    match = re.search(
        r"\b(?:(?:EC|SEC)/\d{2}\.\d{5}|[A-Z]{1,10}/[A-Z0-9.-]+)\b",
        str(value or "").upper(),
    )
    return _norm_numero_ordre(match.group(0)) if match else None


def _normaliser_annee_assurance(value: Any) -> tuple[int | None, bool]:
    return _normaliser_annee_ca(value)


async def _materialize_insurance_declaration(db: AsyncSession, *, imp: TableauImport, parsed_row: Any, source_row: TableauSourceRow) -> None:
    data = dict(parsed_row.normalized_data or {})
    errors = list(source_row.normalization_errors or [])
    line = parsed_row.line_number
    membre = data.get("membre")
    numero = _extract_order_from_member(membre)
    identity = None
    if not numero:
        _ajouter_anomalie(errors, ligne=line, champ="membre", message="Numéro d'ordre absent ou invalide", severity="WARNING")
    else:
        identity = (await db.execute(select(TableauMemberIdentity).where(
            TableauMemberIdentity.organisation_id == imp.organisation_id,
            TableauMemberIdentity.numero_ordre_normalise == numero,
        ).limit(1))).scalars().first()
        if identity is None:
            _ajouter_anomalie(errors, ligne=line, champ="membre", message="Membre non rapproché", severity="WARNING")
    declared, declared_bad = _normaliser_bool_source(data.get("declare"))
    subscribed, subscribed_bad = _normaliser_bool_source(data.get("souscrit"))
    end_date, end_bad = _normaliser_date_source(data.get("fin_couverture"))
    year, year_bad = _normaliser_annee_assurance(data.get("annee_souscription"))
    if declared_bad:
        _ajouter_anomalie(errors, ligne=line, champ="declare", message="Déclaré ambigu", severity="WARNING")
    if subscribed_bad:
        _ajouter_anomalie(errors, ligne=line, champ="souscrit", message="Souscrit ambigu", severity="WARNING")
    if end_bad:
        _ajouter_anomalie(errors, ligne=line, champ="fin_couverture", message="Fin de couverture invalide", severity="WARNING")
    if year_bad:
        _ajouter_anomalie(errors, ligne=line, champ="annee_souscription", message="Année de souscription invalide", severity="WARNING")
    insurer_source = data.get("assureur")
    insurer_normalized = " ".join(str(insurer_source).strip().split()).casefold() if insurer_source not in (None, "") else None
    if subscribed is True and not insurer_normalized:
        _ajouter_anomalie(errors, ligne=line, champ="assureur", message="Souscrit sans assureur", severity="WARNING")
    period_source = data.get("periode")
    period_normalized = " ".join(str(period_source).strip().split()) if period_source not in (None, "") else None
    duplicate = (await db.execute(select(TableauInsuranceDeclaration.id).where(
        TableauInsuranceDeclaration.source_import_id == imp.id,
        TableauInsuranceDeclaration.row_hash == source_row.row_hash,
    ).limit(1))).scalar_one_or_none()
    if duplicate is not None:
        _ajouter_anomalie(errors, ligne=line, champ="ligne", message="Doublon exact dans le même import", severity="WARNING")
    if identity and year is not None:
        previous = (await db.execute(select(TableauInsuranceDeclaration).where(
            TableauInsuranceDeclaration.organisation_id == imp.organisation_id,
            TableauInsuranceDeclaration.member_identity_id == identity.id,
            TableauInsuranceDeclaration.annee_souscription == year,
        ).limit(20))).scalars().all()
        if any(p.souscrit_normalise is not None and subscribed is not None and p.souscrit_normalise != subscribed for p in previous):
            _ajouter_anomalie(errors, ligne=line, champ="souscrit", message="Déclarations contradictoires pour le même membre et la même année", severity="WARNING")
    source_row.business_key_candidate = numero or parsed_row.business_key_candidate
    source_row.normalization_errors = errors or None
    source_row.normalization_status = "warning" if errors else "accepted"
    db.add(TableauInsuranceDeclaration(
        organisation_id=imp.organisation_id, source_import_id=imp.id, source_row_id=source_row.id,
        member_identity_id=identity.id if identity else None, membre_source=str(membre) if membre is not None else None,
        numero_ordre_source=str(membre) if membre is not None else None, numero_ordre_normalise=numero,
        declare_source=str(data.get("declare")) if data.get("declare") is not None else None, declare_normalise=declared,
        souscrit_source=str(data.get("souscrit")) if data.get("souscrit") is not None else None, souscrit_normalise=subscribed,
        fin_couverture_source=str(data.get("fin_couverture")) if data.get("fin_couverture") is not None else None,
        fin_couverture=end_date, annee_souscription_source=str(data.get("annee_souscription")) if data.get("annee_souscription") is not None else None,
        annee_souscription=year, assureur_source=str(insurer_source) if insurer_source is not None else None,
        assureur_normalise=insurer_normalized, periode_source=str(period_source) if period_source is not None else None,
        periode_normalisee=period_normalized, date_situation=imp.date_situation, row_hash=source_row.row_hash,
    ))


async def get_insurance_declarations_at_date(db: AsyncSession, organisation_id: int, numero_ordre: str | None, situation_date: date) -> list[TableauInsuranceDeclaration]:
    numero = _norm_numero_ordre(numero_ordre)
    query = select(TableauInsuranceDeclaration).where(
        TableauInsuranceDeclaration.organisation_id == organisation_id,
        TableauInsuranceDeclaration.date_situation <= situation_date,
    )
    if numero:
        query = query.where(TableauInsuranceDeclaration.numero_ordre_normalise == numero)
    return list((await db.execute(query.order_by(TableauInsuranceDeclaration.date_situation.asc(), TableauInsuranceDeclaration.created_at.asc(), TableauInsuranceDeclaration.id.asc()))).scalars().all())


async def insurance_status_at_date(db: AsyncSession, organisation_id: int, numero_ordre: str, evaluated_date: date) -> str:
    declarations = await get_insurance_declarations_at_date(db, organisation_id, numero_ordre, evaluated_date)
    return _insurance_status_from_declarations(declarations, evaluated_date)


def _insurance_status_from_declarations(declarations: list[TableauInsuranceDeclaration], evaluated_date: date) -> str:
    if not declarations:
        return "UNKNOWN"
    has_unknown = False
    for declaration in declarations:
        if declaration.souscrit_normalise is False:
            return "FALSE"
        if declaration.souscrit_normalise is True:
            if declaration.fin_couverture is None:
                has_unknown = True
            elif declaration.fin_couverture >= evaluated_date:
                return "TRUE"
            else:
                return "FALSE"
        else:
            has_unknown = True
    return "UNKNOWN" if has_unknown else "FALSE"


async def build_preparatory_tableau_at_date(
    db: AsyncSession, organisation_id: int, evaluation_date: date
) -> PreparatoryTableauProjection:
    """Construit une projection explicable, sans lire le Tableau historique."""
    identities = (await db.execute(select(TableauMemberIdentity).where(
        TableauMemberIdentity.organisation_id == organisation_id,
    ).order_by(TableauMemberIdentity.id.asc()))).scalars().all()
    pp_snapshots = (await db.execute(select(TableauPersonnePhysiqueSnapshot).where(
        TableauPersonnePhysiqueSnapshot.organisation_id == organisation_id,
        TableauPersonnePhysiqueSnapshot.date_situation <= evaluation_date,
    ).order_by(TableauPersonnePhysiqueSnapshot.date_situation.desc(), TableauPersonnePhysiqueSnapshot.created_at.desc(), TableauPersonnePhysiqueSnapshot.id.desc()))).scalars().all()
    pm_snapshots = (await db.execute(select(TableauPersonneMoraleSnapshot).where(
        TableauPersonneMoraleSnapshot.organisation_id == organisation_id,
        TableauPersonneMoraleSnapshot.date_situation <= evaluation_date,
    ).order_by(TableauPersonneMoraleSnapshot.date_situation.desc(), TableauPersonneMoraleSnapshot.created_at.desc(), TableauPersonneMoraleSnapshot.id.desc()))).scalars().all()
    ca_rows = (await db.execute(select(TableauCaDeclaration).where(
        TableauCaDeclaration.organisation_id == organisation_id,
        TableauCaDeclaration.date_situation <= evaluation_date,
    ))).scalars().all()
    insurance_rows = (await db.execute(select(TableauInsuranceDeclaration).where(
        TableauInsuranceDeclaration.organisation_id == organisation_id,
        TableauInsuranceDeclaration.date_situation <= evaluation_date,
    ))).scalars().all()
    pp_by_identity: dict[int, list[TableauPersonnePhysiqueSnapshot]] = {}
    pm_by_identity: dict[int, list[TableauPersonneMoraleSnapshot]] = {}
    for snapshot in pp_snapshots:
        if snapshot.identity_id is not None:
            pp_by_identity.setdefault(snapshot.identity_id, []).append(snapshot)
    for snapshot in pm_snapshots:
        if snapshot.identity_id is not None:
            pm_by_identity.setdefault(snapshot.identity_id, []).append(snapshot)
    ca_by_identity: dict[int, list[TableauCaDeclaration]] = {}
    for declaration in ca_rows:
        if declaration.member_identity_id is not None:
            ca_by_identity.setdefault(declaration.member_identity_id, []).append(declaration)
    result = PreparatoryTableauProjection(evaluation_date=evaluation_date)
    result.orphan_ca = [row for row in ca_rows if row.member_identity_id is None]
    result.orphan_insurance = [row for row in insurance_rows if row.member_identity_id is None]
    insurance_by_identity: dict[int, list[TableauInsuranceDeclaration]] = {}
    for declaration in insurance_rows:
        if declaration.member_identity_id is not None:
            insurance_by_identity.setdefault(declaration.member_identity_id, []).append(declaration)
    for identity in identities:
        pp = pp_by_identity.get(identity.id, [])
        pm = pm_by_identity.get(identity.id, [])
        anomalies: list[str] = []
        if not pp and not pm:
            anomalies.append("IDENTITY_WITHOUT_SNAPSHOT")
        if identity.member_kind == "EC" and pm:
            anomalies.append("EC_WITH_PM_SNAPSHOT")
        if identity.member_kind == "SEC" and pp:
            anomalies.append("SEC_WITH_PP_SNAPSHOT")
        if pp and pm:
            anomalies.append("MULTIPLE_PERSON_KINDS")
        snapshots = pp if pp else pm
        snapshot = snapshots[0] if snapshots else None
        if len([s for s in snapshots if s.date_situation == snapshot.date_situation]) > 1 if snapshot else False:
            anomalies.append("AMBIGUOUS_SNAPSHOT_DATE")
        if snapshot is not None:
            status = snapshot.statut_normalise if isinstance(snapshot, TableauPersonnePhysiqueSnapshot) else None
            category = "Société" if identity.member_kind == "SEC" else {"EN_CABINET": "EC Cabinet", "INDEPENDANT": "EC Indépendant", "SALARIE": "EC Salarié"}.get(status, "UNKNOWN")
            name = snapshot.nom if isinstance(snapshot, TableauPersonnePhysiqueSnapshot) else snapshot.societe
            actif = getattr(snapshot, "actif", None)
            cabinet = getattr(snapshot, "cabinet_attache", None)
            nif = getattr(snapshot, "nif", None)
            employer = getattr(snapshot, "nom_employeur", None)
            assure = getattr(snapshot, "assure_synthetique", None)
            source_date = snapshot.date_situation
            if identity.member_kind == "EC" and status is None:
                anomalies.append("UNKNOWN_PP_STATUS")
        else:
            category = "Société" if identity.member_kind == "SEC" else "UNKNOWN"
            name = actif = cabinet = nif = employer = assure = source_date = status = None
        declarations = ca_by_identity.get(identity.id, [])
        ca_valid = [d for d in declarations if d.ca_present]
        insurance_status = _insurance_status_from_declarations(insurance_by_identity.get(identity.id, []), evaluation_date)
        if assure is not None and insurance_status != "UNKNOWN" and assure != (insurance_status == "TRUE"):
            anomalies.append("INSURANCE_SOURCE_MISMATCH")
        if any(d.member_identity_id is None for d in ca_rows):
            pass
        row = PreparatoryTableauRow(
            identity_id=identity.id, organisation_id=organisation_id, numero_ordre=identity.numero_ordre,
            member_kind=identity.member_kind, person_kind=identity.person_kind, nom_denomination=name,
            statut_professionnel=status, tableau_category=category, actif=actif, cabinet_attache=cabinet,
            nif=nif, nom_employeur=employer, ca_present=bool(ca_valid), ca_declaration_count=len(declarations),
            annees_ca_connues=sorted({d.annee for d in declarations if d.annee is not None}),
            devises_ca_connues=sorted({d.devise_normalisee for d in declarations if d.devise_normalisee}),
            derniere_date_situation_ca=max((d.date_situation for d in declarations), default=None),
            insurance_status=insurance_status, assure_source=assure, insurance_source_mismatch="INSURANCE_SOURCE_MISMATCH" in anomalies,
            source_dates={"personne": source_date, "ca": max((d.date_situation for d in declarations), default=None), "assurance": max((d.date_situation for d in insurance_by_identity.get(identity.id, [])), default=None)},
            anomaly_codes=anomalies, projection_status="BLOCKED" if any(code in {"IDENTITY_WITHOUT_SNAPSHOT", "EC_WITH_PM_SNAPSHOT", "SEC_WITH_PP_SNAPSHOT", "MULTIPLE_PERSON_KINDS"} for code in anomalies) else ("WARNING" if anomalies else "READY"),
        )
        result.rows.append(row)
    return result


async def _materialize_ca_declaration(db: AsyncSession, *, imp: TableauImport, parsed_row: Any, source_row: TableauSourceRow) -> None:
    data = dict(parsed_row.normalized_data or {})
    errors = list(source_row.normalization_errors or [])
    line = parsed_row.line_number
    raw_numero = data.get("numero_ordre")
    numero = _norm_numero_ordre(raw_numero)
    identity = None
    if not numero:
        _ajouter_anomalie(errors, ligne=line, champ="numero_ordre", message="N° d'ordre absent ou invalide", severity="ERROR")
    else:
        identity = (await db.execute(select(TableauMemberIdentity).where(
            TableauMemberIdentity.organisation_id == imp.organisation_id,
            TableauMemberIdentity.numero_ordre_normalise == numero,
        ).limit(1))).scalars().first()
        if identity is None:
            _ajouter_anomalie(errors, ligne=line, champ="numero_ordre", message="Membre non rapproché", severity="WARNING")
    annee, annee_bad = _normaliser_annee_ca(data.get("annee"))
    devise, devise_bad = _normaliser_devise(data.get("devise"))
    facture, facture_bad = _normaliser_ca_decimal(data.get("ca_facture"))
    collecte, collecte_bad = _normaliser_ca_decimal(data.get("ca_collecte"))
    date_maj, date_bad = _normaliser_date_source(data.get("date_mise_a_jour"))
    actif, actif_bad = _normaliser_bool_source(data.get("actif"))
    for champ, bad, severity in (
        ("annee", annee_bad, "ERROR"), ("devise", devise_bad, "WARNING"),
        ("ca_facture", facture_bad, "ERROR"), ("ca_collecte", collecte_bad, "ERROR"),
        ("date_mise_a_jour", date_bad, "WARNING"), ("actif", actif_bad, "WARNING"),
    ):
        if bad:
            _ajouter_anomalie(errors, ligne=line, champ=champ, message="Valeur invalide ou inconnue", severity=severity)
    if facture is not None and collecte is not None and collecte > facture:
        _ajouter_anomalie(errors, ligne=line, champ="ca_collecte", message="CA collecté supérieur au CA facturé", severity="WARNING")
    if data.get("membre") and identity and str(data.get("membre")).strip().lower() != str(identity.numero_ordre).strip().lower():
        # Le libellé Membre est descriptif, il ne remplace jamais le rapprochement par numéro.
        pp = (await db.execute(select(TableauPersonnePhysiqueSnapshot.nom).where(
            TableauPersonnePhysiqueSnapshot.identity_id == identity.id
        ).order_by(TableauPersonnePhysiqueSnapshot.date_situation.desc()).limit(1))).scalar_one_or_none()
        pm = (await db.execute(select(TableauPersonneMoraleSnapshot.societe).where(
            TableauPersonneMoraleSnapshot.identity_id == identity.id
        ).order_by(TableauPersonneMoraleSnapshot.date_situation.desc()).limit(1))).scalar_one_or_none()
        known_label = pp or pm
        if known_label and str(data.get("membre")).strip().casefold() != str(known_label).strip().casefold():
            _ajouter_anomalie(errors, ligne=line, champ="membre", message="Libellé Membre divergent de l'identité préparatoire", severity="WARNING")
    duplicate = (await db.execute(select(TableauCaDeclaration.id).where(
        TableauCaDeclaration.source_import_id == imp.id,
        TableauCaDeclaration.row_hash == source_row.row_hash,
    ).limit(1))).scalar_one_or_none()
    if duplicate is not None:
        _ajouter_anomalie(errors, ligne=line, champ="ligne", message="Doublon exact dans le même import", severity="WARNING")
    source_row.business_key_candidate = numero or parsed_row.business_key_candidate
    source_row.normalization_errors = errors or None
    source_row.normalization_status = "error" if any(e.get("severity") == "ERROR" for e in errors) else ("warning" if errors else "accepted")
    db.add(TableauCaDeclaration(
        organisation_id=imp.organisation_id,
        source_import_id=imp.id,
        source_row_id=source_row.id,
        member_identity_id=identity.id if identity else None,
        numero_ordre_source=str(raw_numero) if raw_numero is not None else None,
        numero_ordre_normalise=numero,
        membre_libelle_source=str(data.get("membre")) if data.get("membre") is not None else None,
        actif_source=str(data.get("actif")) if data.get("actif") is not None else None,
        actif_normalise=actif,
        annee=annee,
        devise_source=str(data.get("devise")) if data.get("devise") is not None else None,
        devise_normalisee=devise,
        ca_facture_source=str(data.get("ca_facture")) if data.get("ca_facture") is not None else None,
        ca_facture=facture,
        ca_collecte_source=str(data.get("ca_collecte")) if data.get("ca_collecte") is not None else None,
        ca_collecte=collecte,
        date_mise_a_jour_source=str(data.get("date_mise_a_jour")) if data.get("date_mise_a_jour") is not None else None,
        date_mise_a_jour=date_maj,
        date_situation=imp.date_situation,
        row_hash=source_row.row_hash,
        ca_present=facture is not None or collecte is not None,
    ))


async def get_ca_declarations_at_date(
    db: AsyncSession, organisation_id: int, numero_ordre: str | None, situation_date: date
) -> list[TableauCaDeclaration]:
    """Retourne toutes les observations CA connues à une date donnée.

    Cette fonction ne sélectionne pas une « ligne courante » : plusieurs déclarations
    pour une même année ou devise restent visibles. La projection métier sera définie
    ultérieurement.
    """
    numero = _norm_numero_ordre(numero_ordre)
    query = select(TableauCaDeclaration).where(
        TableauCaDeclaration.organisation_id == organisation_id,
        TableauCaDeclaration.date_situation <= situation_date,
    )
    if numero:
        query = query.where(TableauCaDeclaration.numero_ordre_normalise == numero)
    return list((await db.execute(query.order_by(
        TableauCaDeclaration.date_situation.asc(), TableauCaDeclaration.created_at.asc(), TableauCaDeclaration.id.asc()
    ))).scalars().all())


async def ca_present_at_date(
    db: AsyncSession, organisation_id: int, numero_ordre: str, situation_date: date
) -> bool:
    declarations = await get_ca_declarations_at_date(db, organisation_id, numero_ordre, situation_date)
    return any(row.ca_present for row in declarations)


def _ajouter_anomalie(errors: list[dict[str, Any]], *, ligne: int, champ: str, message: str, severity: str) -> None:
    errors.append({"ligne": ligne, "champ": champ, "message": message, "severity": severity})


async def _materialize_member_snapshot(
    db: AsyncSession,
    *,
    imp: TableauImport,
    source_type: str,
    parsed_row: Any,
    source_row: TableauSourceRow,
    official_rows: list[OfficialExpertRecord],
) -> None:
    """Crée une identité/snapshot PP ou PM sans jamais corriger la source."""
    data = dict(parsed_row.normalized_data or {})
    errors = list(source_row.normalization_errors or [])
    line = parsed_row.line_number
    raw_numero = data.get("numero_ordre")
    numero = _norm_numero_ordre(raw_numero)
    member_kind, _expected_person_kind = _classification_from_order(numero)

    if not numero:
        _ajouter_anomalie(errors, ligne=line, champ="numero_ordre", message="N° d'ordre absent ou invalide", severity="BLOCKING")
    expected_kind = "EC" if source_type == "personnes_physiques" else "SEC"
    expected_person = "PHYSIQUE" if source_type == "personnes_physiques" else "MORALE"
    if member_kind and member_kind != expected_kind:
        _ajouter_anomalie(
            errors,
            ligne=line,
            champ="numero_ordre",
            message=f"Préfixe {member_kind} incompatible avec la source {source_type}",
            severity="WARNING",
        )
    if numero and member_kind is None:
        _ajouter_anomalie(
            errors,
            ligne=line,
            champ="numero_ordre",
            message="Format historique/non standard accepté ; type déterminé par la source",
            severity="WARNING",
        )
    if not data.get("membre") or not str(data.get("membre")).strip():
        _ajouter_anomalie(errors, ligne=line, champ="nom" if expected_person == "PHYSIQUE" else "societe", message="Identité absente", severity="BLOCKING")

    identity: TableauMemberIdentity | None = None
    if numero and not any(e.get("severity") == "BLOCKING" for e in errors):
        exact_matches = [row for row in official_rows if row.numero_ordre_normalise == numero]
        reference_status = "UNRESOLVED"
        reference_match_method = None
        expert_comptable_id = None
        match_metadata: dict[str, Any] = {}
        if len(exact_matches) == 1:
            reference_status = "MATCHED_OFFICIAL"
            reference_match_method = "EXACT_ORDER"
            expert_comptable_id = exact_matches[0].id
        elif len(exact_matches) > 1:
            reference_status = "AMBIGUOUS"
            match_metadata["candidate_official_ids"] = [str(row.id) for row in exact_matches]
            match_metadata["reason"] = "DUPLICATE_NORMALIZED_ORDER"
        else:
            reference_status = "ABSENT_DU_REFERENTIEL"
            candidate_ids: dict[str, set[str]] = {"name": set(), "email": set(), "phone": set()}
            source_name = " ".join(str(data.get("membre") or "").casefold().split())
            source_email = str(data.get("email") or "").strip().casefold()
            source_phone = "".join(ch for ch in str(data.get("telephone") or "") if ch.isdigit())
            for official in official_rows:
                official_name = " ".join(str(official.values.get("nom_denomination") or "").casefold().split())
                official_email = str(official.values.get("email") or "").strip().casefold()
                official_phone = "".join(ch for ch in str(official.values.get("telephone") or "") if ch.isdigit())
                if source_name and source_name == official_name:
                    candidate_ids["name"].add(str(official.id))
                if source_email and source_email == official_email:
                    candidate_ids["email"].add(str(official.id))
                if source_phone and source_phone == official_phone:
                    candidate_ids["phone"].add(str(official.id))
            match_metadata["suggested_candidates"] = {
                signal: sorted(values) for signal, values in candidate_ids.items() if values
            }
            candidate_union = set().union(*candidate_ids.values())
            if len(candidate_union) > 1:
                reference_status = "AMBIGUOUS"
                match_metadata["reason"] = "MULTIPLE_WEAK_CANDIDATES"
            elif len(candidate_union) == 1:
                reference_status = "UNRESOLVED"
                match_metadata["reason"] = "WEAK_CANDIDATE_REQUIRES_REVIEW"
        identity_res = await db.execute(
            select(TableauMemberIdentity).where(
                TableauMemberIdentity.organisation_id == imp.organisation_id,
                TableauMemberIdentity.numero_ordre_normalise == numero,
            ).order_by(TableauMemberIdentity.id.asc()).limit(1)
        )
        identity = identity_res.scalars().first()
        if identity is None:
            identity = TableauMemberIdentity(
                organisation_id=imp.organisation_id,
                numero_ordre=numero,
                numero_ordre_normalise=numero,
                expert_comptable_id=expert_comptable_id,
                member_kind=member_kind or expected_kind,
                person_kind=expected_person,
                classification_status="classified" if member_kind else "legacy_order",
                reference_status=reference_status,
                reference_match_method=reference_match_method,
                reference_match_metadata=match_metadata or None,
                origin_type="PP" if source_type == "personnes_physiques" else "PM",
                first_seen_at=imp.created_at,
                first_seen_import_id=imp.id,
                last_seen_at=imp.created_at,
                last_seen_import_id=imp.id,
            )
            db.add(identity)
            await db.flush()
        else:
            if identity.member_kind != (member_kind or expected_kind) or identity.person_kind != expected_person:
                _ajouter_anomalie(errors, ligne=line, champ="numero_ordre", message="Collision de classification PP/PM", severity="BLOCKING")
                identity = None
            else:
                if (
                    identity.expert_comptable_id is not None
                    and expert_comptable_id is not None
                    and identity.expert_comptable_id != expert_comptable_id
                ):
                    # Une nouvelle ligne ne déplace jamais silencieusement une
                    # liaison officielle déjà établie vers un autre expert.
                    identity.reference_status = "AMBIGUOUS"
                    identity.reference_match_method = None
                    identity.reference_match_metadata = {
                        "reason": "EXISTING_OFFICIAL_LINK_CONFLICT",
                        "existing_official_id": str(identity.expert_comptable_id),
                        "candidate_official_id": str(expert_comptable_id),
                    }
                elif identity.expert_comptable_id is not None and expert_comptable_id is None:
                    # Conserver la liaison, mais exiger une revue si le numéro
                    # importé ne retrouve plus exactement l'expert courant.
                    identity.reference_status = "UNRESOLVED"
                    identity.reference_match_method = None
                    identity.reference_match_metadata = {
                        **match_metadata,
                        "reason": "EXISTING_LINK_ORDER_REQUIRES_REVIEW",
                        "existing_official_id": str(identity.expert_comptable_id),
                    }
                else:
                    identity.expert_comptable_id = expert_comptable_id
                    identity.reference_status = reference_status
                    identity.reference_match_method = reference_match_method
                    identity.reference_match_metadata = match_metadata or None
                identity.last_seen_at = imp.created_at
                identity.last_seen_import_id = imp.id

    source_row.business_key_candidate = numero or parsed_row.business_key_candidate
    if errors:
        source_row.normalization_errors = errors
    blocking = any(e.get("severity") == "BLOCKING" for e in errors)
    error = any(e.get("severity") == "ERROR" for e in errors)
    warning = any(e.get("severity") == "WARNING" for e in errors)
    source_row.normalization_status = "blocking" if blocking else ("error" if error else ("warning" if warning else "accepted"))

    if blocking or identity is None:
        return

    if source_type == "personnes_physiques":
        actif, actif_bad = _normaliser_bool_source(data.get("actif"))
        assure, assure_bad = _normaliser_bool_source(data.get("assure"))
        amlco, amlco_bad = _normaliser_bool_source(data.get("amlco"))
        naissance, naissance_bad = _normaliser_date_source(data.get("date_naissance"))
        pct120, pct120_bad = _normaliser_decimal_source(data.get("pourcentage_120_for"))
        pct80, pct80_bad = _normaliser_decimal_source(data.get("pourcentage_80_for"))
        for champ, bad in (("actif", actif_bad), ("assure", assure_bad), ("amlco", amlco_bad), ("date_naissance", naissance_bad), ("pourcentage_120_for", pct120_bad), ("pourcentage_80_for", pct80_bad)):
            if bad:
                _ajouter_anomalie(errors, ligne=line, champ=champ, message="Valeur inconnue ou invalide", severity="WARNING")
        statut_source = str(data.get("statut")) if data.get("statut") is not None else None
        statut_normalise = _normaliser_statut(data.get("statut"))
        if statut_source and statut_normalise is None:
            _ajouter_anomalie(errors, ligne=line, champ="statut", message="Statut professionnel inconnu", severity="WARNING")
        contextual_value = data.get("cabinet_attache") or data.get("nom_employeur") or data.get("nif")
        cabinet_attache = nif = nom_employeur = None
        if statut_normalise == "EN_CABINET":
            cabinet_attache = str(contextual_value).strip() if contextual_value not in (None, "") else None
            if not cabinet_attache:
                _ajouter_anomalie(errors, ligne=line, champ="cabinet_attache", message="EN_CABINET sans cabinet d'attache", severity="WARNING")
        elif statut_normalise == "INDEPENDANT":
            if contextual_value not in (None, "") and _looks_like_sec(contextual_value):
                _ajouter_anomalie(errors, ligne=line, champ="nif", message="Référence SEC dans un champ NIF d'indépendant", severity="WARNING")
            else:
                nif = str(contextual_value).strip() if contextual_value not in (None, "") else None
            if not nif:
                _ajouter_anomalie(errors, ligne=line, champ="nif", message="Indépendant sans NIF", severity="WARNING")
        elif statut_normalise == "SALARIE":
            if contextual_value not in (None, "") and _looks_like_nif(contextual_value):
                _ajouter_anomalie(errors, ligne=line, champ="nom_employeur", message="Valeur ressemblant à un NIF chez un salarié", severity="WARNING")
            else:
                nom_employeur = str(contextual_value).strip() if contextual_value not in (None, "") else None
            if not nom_employeur:
                _ajouter_anomalie(errors, ligne=line, champ="nom_employeur", message="SALARIE sans employeur", severity="WARNING")
        elif statut_source:
            _ajouter_anomalie(errors, ligne=line, champ="statut", message="Statut inconnu : valeur contextuelle non interprétée", severity="WARNING")
        snapshot = TableauPersonnePhysiqueSnapshot(
            organisation_id=imp.organisation_id,
            source_import_id=imp.id,
            source_row_id=source_row.id,
            identity_id=identity.id,
            date_situation=imp.date_situation,
            numero_ordre=numero,
            nom=str(data.get("membre")).strip(),
            sexe=str(data.get("sexe")).strip() if data.get("sexe") is not None else None,
            actif=actif,
            date_naissance=naissance,
            telephone=str(data.get("telephone")).strip() if data.get("telephone") is not None else None,
            email=str(data.get("email")).strip().lower() if data.get("email") is not None else None,
            ville=str(data.get("ville")).strip() if data.get("ville") is not None else None,
            adresse=str(data.get("adresse")).strip() if data.get("adresse") is not None else None,
            statut_source=statut_source,
            statut_normalise=statut_normalise,
            cabinet_attache=cabinet_attache,
            numero_impot=None,
            nif=nif,
            nom_employeur=nom_employeur,
            assure_synthetique=assure,
            amlco=amlco,
            pourcentage_120_for=pct120,
            pourcentage_80_for=pct80,
        )
    else:
        assure, assure_bad = _normaliser_bool_source(data.get("assure"))
        solde, solde_bad = _normaliser_decimal_source(data.get("solde"))
        cotisation_raw = data.get("cotisation")
        cotisation_normalisee: dict | None = None
        cot_bool, cot_bool_bad = _normaliser_bool_source(cotisation_raw)
        if cot_bool_bad:
            cot_decimal, cot_decimal_bad = _normaliser_decimal_source(cotisation_raw)
            if not cot_decimal_bad:
                cotisation_normalisee = {"kind": "decimal", "value": str(cot_decimal)}
            elif cotisation_raw not in (None, ""):
                _ajouter_anomalie(errors, ligne=line, champ="cotisation", message="Interprétation incertaine", severity="WARNING")
        elif cot_bool is not None:
            cotisation_normalisee = {"kind": "boolean", "value": cot_bool}
        for champ, bad in (("assure", assure_bad), ("solde", solde_bad)):
            if bad:
                _ajouter_anomalie(errors, ligne=line, champ=champ, message="Valeur numérique ou booléenne invalide", severity="WARNING")

        def counter(field: str) -> int | None:
            value, bad = _normaliser_decimal_source(data.get(field))
            if bad:
                _ajouter_anomalie(errors, ligne=line, champ=field, message="Compteur non numérique", severity="WARNING")
                return None
            if value is not None and (value != value.to_integral_value() or value < 0):
                _ajouter_anomalie(errors, ligne=line, champ=field, message="Compteur négatif ou non entier", severity="WARNING")
                return None
            return int(value) if value is not None else None

        snapshot = TableauPersonneMoraleSnapshot(
            organisation_id=imp.organisation_id,
            source_import_id=imp.id,
            source_row_id=source_row.id,
            identity_id=identity.id,
            date_situation=imp.date_situation,
            numero_ordre=numero,
            societe=str(data.get("membre")).strip(),
            telephone=str(data.get("telephone")).strip() if data.get("telephone") is not None else None,
            email=str(data.get("email")).strip().lower() if data.get("email") is not None else None,
            ville=str(data.get("ville")).strip() if data.get("ville") is not None else None,
            adresse=str(data.get("adresse")).strip() if data.get("adresse") is not None else None,
            numero_impot=str(data.get("nif")).strip() if data.get("nif") is not None else None,
            cotisation_source=str(cotisation_raw) if cotisation_raw is not None else None,
            cotisation_normalisee=cotisation_normalisee,
            solde=solde,
            assure_synthetique=assure,
            nb_employes=counter("nb_employes"),
            nb_ec=counter("nb_ec"),
            nb_sta=counter("nb_sta"),
        )

    if errors:
        source_row.normalization_errors = errors
        source_row.normalization_status = "warning" if not blocking else "blocking"
    db.add(snapshot)


async def get_personne_physique_at_date(
    db: AsyncSession, organisation_id: int, numero_ordre: str, situation_date: date
) -> TableauPersonnePhysiqueSnapshot | None:
    numero = _norm_numero_ordre(numero_ordre)
    if not numero:
        return None
    result = await db.execute(
        select(TableauPersonnePhysiqueSnapshot)
        .where(
            TableauPersonnePhysiqueSnapshot.organisation_id == organisation_id,
            TableauPersonnePhysiqueSnapshot.numero_ordre == numero,
            TableauPersonnePhysiqueSnapshot.date_situation <= situation_date,
        )
        .order_by(TableauPersonnePhysiqueSnapshot.date_situation.desc(), TableauPersonnePhysiqueSnapshot.created_at.desc(), TableauPersonnePhysiqueSnapshot.id.desc())
        .limit(1)
    )
    return result.scalars().first()


async def get_personne_morale_at_date(
    db: AsyncSession, organisation_id: int, numero_ordre: str, situation_date: date
) -> TableauPersonneMoraleSnapshot | None:
    numero = _norm_numero_ordre(numero_ordre)
    if not numero:
        return None
    result = await db.execute(
        select(TableauPersonneMoraleSnapshot)
        .where(
            TableauPersonneMoraleSnapshot.organisation_id == organisation_id,
            TableauPersonneMoraleSnapshot.numero_ordre == numero,
            TableauPersonneMoraleSnapshot.date_situation <= situation_date,
        )
        .order_by(TableauPersonneMoraleSnapshot.date_situation.desc(), TableauPersonneMoraleSnapshot.created_at.desc(), TableauPersonneMoraleSnapshot.id.desc())
        .limit(1)
    )
    return result.scalars().first()


async def get_base_tableau(
    db: AsyncSession,
    organisation_ids: list[int],
    exercice: str | None = None,
    anomalie_only: bool = False,
    national: bool = False,
    recherche: str | None = None,
    categorie: str | None = None,
    organisation_id: int | None = None,
    limit: int | None = None,
    offset: int = 0,
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
            "analysis_import_id": None,
            "organisation_options": [],
            "limit": limit or 50,
            "offset": offset,
            "dossiers": [],
        }

    if organisation_id is not None and organisation_id not in organisation_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Conseil hors du périmètre autorisé.")

    analyse_import_res = await db.execute(
        select(TableauImport.id)
        .where(
            TableauImport.organisation_id.in_(organisation_ids),
            TableauImport.exercice == exercice,
        )
        .order_by(
            TableauImport.date_situation.desc(),
            TableauImport.created_at.desc(),
            TableauImport.id.desc(),
        )
        .limit(1)
    )
    analysis_import_id = analyse_import_res.scalar_one_or_none()
    dossiers = await list_base_tableau(
        db,
        organisation_ids,
        exercice,
        anomalie_only=anomalie_only,
        recherche=recherche,
        categorie=categorie,
        organisation_id=organisation_id,
        limit=limit,
        offset=offset,
    )
    resume = await get_base_summary(
        db,
        organisation_ids,
        exercice,
        anomalie_only=anomalie_only,
        recherche=recherche,
        categorie=categorie,
        organisation_id=organisation_id,
    )
    org_rows = await db.execute(
        select(Organisation.id, Organisation.nom)
        .where(Organisation.id.in_(organisation_ids))
        .order_by(Organisation.nom)
    )
    organisations = [{"id": org_id, "nom": nom} for org_id, nom in org_rows.all()]
    noms_organisations = {item["id"]: item["nom"] for item in organisations}
    for dossier in dossiers:
        dossier.date_situation = dossier.import_ref.date_situation if dossier.import_ref else None
        dossier.source_file_name = dossier.import_ref.file_name if dossier.import_ref else None
        dossier.organisation_nom = noms_organisations.get(dossier.organisation_id)
    return {
        "exercice": exercice,
        "national": national,
        "organisations": resume["organisations"] or organisation_ids,
        "total_membres": resume["total"],
        "membres_sans_numero": resume["sans_numero"],
        "imports_couverts": resume["imports"],
        "analysis_import_id": analysis_import_id,
        "organisation_options": organisations,
        "limit": limit or max(1, resume["total"]),
        "offset": offset,
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
    return await _analyser_dossiers(db, organisation_id, imp, dossier_rows, scope="import")


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
    return await _analyser_dossiers(db, organisation_id, imp, dossier_rows, scope="base")


async def _analyser_dossiers(
    db: AsyncSession,
    organisation_id: int,
    imp: TableauImport,
    dossier_rows: list[TableauDossier],
    *,
    scope: str,
) -> TableauAnalyse:
    """Verdict, anomalies et statistiques sur un ensemble de dossiers donné."""
    # Sérialise les deux analyses possibles d'un même import et garantit l'unicité
    # (organisation, import, scope) même en cas de double clic concurrent.
    await db.execute(
        select(TableauImport.id)
        .where(TableauImport.id == imp.id, TableauImport.organisation_id == organisation_id)
        .with_for_update()
    )
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

    anomaly_dicts = detect_anomalies(dossier_dicts, exercice_annee, reglages)
    stats = compute_analyse_stats(dossier_dicts, anomaly_dicts, verdicts)

    existing = await get_analyse_for_import(db, organisation_id, import_id, scope=scope)
    if existing:
        for k, v in stats.items():
            setattr(existing, k, v)
        existing.status = "completed"
        existing.updated_at = datetime.now(timezone.utc)
        existing.source_dossier_ids = [d.id for d in dossier_rows]
        existing.source_import_ids = sorted({d.import_id for d in dossier_rows})
        analyse = existing
    else:
        analyse = TableauAnalyse(
            organisation_id=organisation_id,
            import_id=import_id,
            exercice=imp.exercice,
            scope=scope,
            status="completed",
            source_dossier_ids=[d.id for d in dossier_rows],
            source_import_ids=sorted({d.import_id for d in dossier_rows}),
            **stats,
        )
        db.add(analyse)

    await db.flush()

    dossiers_anormaux = {a["dossier_id"] for a in anomaly_dicts}
    for d in dossier_rows:
        d.anomalie_detectee = d.id in dossiers_anormaux
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

    cles_dossiers = [_cle_decision(d.numero_ordre, d.nom, d.prenom) for d in dossier_rows]
    homonymes = _cles_homonymes(cles_dossiers)
    decisions_source = {
        decision.id
        for cle in set(cles_dossiers) - homonymes
        if cle
        for decision in decisions.get(cle, [])
    }
    analyse.source_decision_ids = sorted(decisions_source)

    # Chaque analyse possède ses anomalies : rapports et PV restent cohérents
    # même si un autre périmètre est analysé ensuite.
    res = await db.execute(
        select(TableauAnomalie)
        .where(or_(
            TableauAnomalie.analyse_id == analyse.id,
            (
                TableauAnomalie.analyse_id.is_(None)
                & TableauAnomalie.dossier_id.in_([d.id for d in dossier_rows])
            ),
        ))
    )
    for old in res.scalars().all():
        await db.delete(old)
    await db.flush()

    for a_dict in anomaly_dicts:
        db.add(TableauAnomalie(
            organisation_id=organisation_id,
            analyse_id=analyse.id,
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
    dossiers_a_rows = await list_base_tableau(db, [organisation_id], exercice_a)
    dossiers_b_rows = await list_base_tableau(db, [organisation_id], exercice_b)

    if not dossiers_a_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Aucun dossier pour l'exercice {exercice_a}")
    if not dossiers_b_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Aucun dossier pour l'exercice {exercice_b}")

    def to_dict(d: TableauDossier) -> dict:
        return {
            "id": d.id,
            "numero_ordre": d.numero_ordre,
            "nom": d.nom,
            "prenom": d.prenom,
            "categorie": d.categorie,
        }

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
    dossier_res = await db.execute(
        select(TableauDossier).where(
            TableauDossier.id == payload.dossier_id,
            TableauDossier.organisation_id == organisation_id,
        )
    )
    dossier = dossier_res.scalar_one_or_none()
    if dossier is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dossier introuvable")

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
    await db.flush()
    await record_tableau_audit(
        db,
        organisation_id=organisation_id,
        user_id=user.id,
        action="tableau.decision.create",
        target_type="tableau_dossier",
        target_id=dossier.id,
        metadata_json={
            "decision_id": decision.id,
            "exercice": dossier.exercice,
            "numero_ordre": dossier.numero_ordre,
            "decision": payload.decision,
        },
    )
    await _invalider_analyses(db, organisation_id, dossier.exercice)
    await db.commit()
    return decision


_CHAMPS_CORRIGEABLES = {
    "numero_ordre", "nom", "prenom", "categorie", "statut_membre",
    "cotisation_montant", "cotisation_payee", "heures_forco", "assurance",
    "chiffre_affaires", "sexe", "date_naissance", "nif", "anciennete",
    "email", "telephone", "adresse", "cabinet",
}
_CHAMPS_EFFAÇABLES = _CHAMPS_CORRIGEABLES - {"nom", "categorie"}
_CHAMPS_BOOLEENS = {"cotisation_payee", "assurance", "chiffre_affaires"}
_CHAMPS_NUMERIQUES = {"cotisation_montant", "heures_forco"}
_TAILLES_TEXTE = {
    "numero_ordre": 50,
    "nom": 200,
    "prenom": 200,
    "categorie": 50,
    "statut_membre": 50,
    "sexe": 10,
    "nif": 50,
    "anciennete": 30,
    "email": 200,
    "telephone": 50,
    "cabinet": 200,
}


def _normaliser_correction(champ: str, valeur: Any) -> Any:
    if champ in _CHAMPS_BOOLEENS:
        if not isinstance(valeur, bool):
            raise ValueError("une valeur booléenne est requise")
        return valeur
    if champ in _CHAMPS_NUMERIQUES:
        if isinstance(valeur, bool):
            raise ValueError("un nombre est requis")
        try:
            nombre = Decimal(str(valeur))
        except Exception as exc:
            raise ValueError("un nombre est requis") from exc
        if not nombre.is_finite() or nombre < 0:
            raise ValueError("un nombre positif ou nul est requis")
        return nombre
    if champ == "date_naissance":
        if isinstance(valeur, datetime):
            return valeur.date()
        if isinstance(valeur, date):
            return valeur
        try:
            return date.fromisoformat(str(valeur))
        except (TypeError, ValueError) as exc:
            raise ValueError("une date ISO AAAA-MM-JJ est requise") from exc

    if not isinstance(valeur, str):
        raise ValueError("une valeur texte est requise")
    texte = valeur.strip()
    if not texte:
        raise ValueError("une valeur vide doit être envoyée dans clear_fields")
    if champ == "numero_ordre":
        texte = _norm_numero_ordre(texte) or texte
    if champ == "categorie" and texte not in _CATEGORIES_CONNUES:
        raise ValueError("catégorie inconnue")
    taille = _TAILLES_TEXTE.get(champ)
    if taille and len(texte) > taille:
        raise ValueError(f"{taille} caractères maximum")
    return texte


async def corriger_dossier(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    dossier_id: int,
    payload: TableauDossierCorrection,
) -> TableauDossier:
    """Corrige une situation importée et journalise précisément les champs touchés."""
    res = await db.execute(
        select(TableauDossier).where(
            TableauDossier.id == dossier_id,
            TableauDossier.organisation_id == organisation_id,
        ).with_for_update()
    )
    dossier = res.scalar_one_or_none()
    if dossier is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dossier introuvable")

    champs_inconnus = (set(payload.changes) | set(payload.clear_fields)) - _CHAMPS_CORRIGEABLES
    if champs_inconnus:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Champ(s) non corrigeable(s) : {', '.join(sorted(champs_inconnus))}",
        )
    effacements_interdits = set(payload.clear_fields) - _CHAMPS_EFFAÇABLES
    if effacements_interdits:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Le nom et la catégorie ne peuvent pas être effacés.",
        )
    chevauchement = set(payload.changes) & set(payload.clear_fields)
    if chevauchement:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Un champ ne peut pas être modifié et effacé à la fois : {', '.join(sorted(chevauchement))}.",
        )
    if not payload.changes and not payload.clear_fields:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Aucune correction fournie.")
    motif = payload.motif.strip()
    if len(motif) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Le motif doit contenir au moins 3 caractères.",
        )

    anciens: dict[str, Any] = {}
    numero_original = dossier.numero_ordre
    for champ, valeur in payload.changes.items():
        try:
            valeur = _normaliser_correction(champ, valeur)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Valeur invalide pour {champ} : {exc}.",
            ) from exc
        if champ in {"nom", "categorie"} and not str(valeur or "").strip():
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{champ} est obligatoire.")
        anciens[champ] = _valeur_json(getattr(dossier, champ))
        setattr(dossier, champ, valeur)
    for champ in payload.clear_fields:
        anciens.setdefault(champ, _valeur_json(getattr(dossier, champ)))
        setattr(dossier, champ, None)

    dossier.annee_inscription, dossier.anciennete_annees = _anciennete_annees(
        dossier.numero_ordre,
        dossier.exercice,
    )
    if "date_naissance" in payload.changes or "date_naissance" in payload.clear_fields:
        naissance = dossier.date_naissance
        annee = _exercice_annee(dossier.exercice)
        dossier.age = annee - naissance.year if naissance and annee else None
    dossier.conclusion = None
    dossier.conclusion_motif = None
    dossier.statut_dossier = "corrigé_à_analyser"
    dossier.anomalie_detectee = False
    raw = dict(dossier.raw_data or {})
    historique = list(raw.get("corrections") or [])
    historique.append({
        "corrige_le": datetime.now(timezone.utc).isoformat(),
        "user_id": str(user.id),
        "motif": motif,
        "champs": sorted(anciens),
    })
    raw["corrections"] = historique
    dossier.raw_data = raw
    flag_modified(dossier, "raw_data")

    await record_tableau_audit(
        db,
        organisation_id=organisation_id,
        user_id=user.id,
        action="tableau.dossier.correct",
        target_type="tableau_dossier",
        target_id=dossier.id,
        metadata_json={
            "exercice": dossier.exercice,
            "numero_ordre": dossier.numero_ordre,
            "champs": sorted(anciens),
            "motif": motif,
        },
    )
    await _invalider_analyses(
        db,
        organisation_id,
        dossier.exercice,
        dossier_id=dossier.id,
        import_id=dossier.import_id,
    )
    if _norm_numero_ordre(numero_original) != _norm_numero_ordre(dossier.numero_ordre):
        anciennes_situations = []
        if numero_original:
            anciennes_situations = list((await db.execute(
                select(TableauDossier).where(
                    TableauDossier.organisation_id == organisation_id,
                    TableauDossier.exercice == dossier.exercice,
                    TableauDossier.numero_ordre == numero_original,
                )
            )).scalars().all())
        await _marquer_situations_courantes(db, [dossier, *anciennes_situations])
    await db.commit()
    await db.refresh(dossier)
    return dossier


async def get_reglages(
    db: AsyncSession,
    organisation_id: int,
    import_id: int,
) -> dict:
    """Réglages effectifs de l'exercice : ceux enregistrés, complétés par le barème.

    Sans cette lecture, la page de réglages afficherait les valeurs par défaut du
    code et non celles qui gouvernent réellement les conclusions.
    """
    imp = await get_import(db, organisation_id, import_id)
    if imp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import introuvable")
    return dict(verdict_engine.TableauReglages.from_dict((imp.metadata_json or {}).get("reglages")).__dict__)


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
    reglages_valides = validated.__dict__
    imports_exercice = (await db.execute(
        select(TableauImport).where(
            TableauImport.organisation_id == organisation_id,
            TableauImport.exercice == imp.exercice,
        )
    )).scalars().all()
    for import_exercice in imports_exercice:
        import_meta = dict(import_exercice.metadata_json or {})
        import_meta["reglages"] = reglages_valides
        import_exercice.metadata_json = import_meta
        flag_modified(import_exercice, "metadata_json")
    await _invalider_analyses(db, organisation_id, imp.exercice)
    await db.commit()
    return reglages_valides


async def export_tableau(
    db: AsyncSession,
    organisation_id: int,
    import_id: int,
    organisation_nom: str = "CONSEIL PROVINCIAL",
    scope: str = "import",
) -> tuple[bytes, str]:
    """Génère le tableau provincial de sortie (.xlsx). Renvoie (octets, nom_fichier)."""
    from .exporter import build_workbook

    imp = await get_import(db, organisation_id, import_id)
    if imp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import introuvable")

    analyse = await get_analyse_for_import(db, organisation_id, import_id, scope=scope)
    if analyse is None or analyse.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"L'analyse {scope} doit être exécutée ou relancée avant l'export.",
        )

    exercice_annee = _exercice_annee(imp.exercice)
    reglages = verdict_engine.TableauReglages.from_dict((imp.metadata_json or {}).get("reglages"))

    source_ids = [int(value) for value in (analyse.source_dossier_ids or [])]
    if source_ids:
        dossier_rows = list((await db.execute(
            select(TableauDossier).where(
                TableauDossier.organisation_id == organisation_id,
                TableauDossier.id.in_(source_ids),
            ).order_by(TableauDossier.nom, TableauDossier.id)
        )).scalars().all())
    elif scope == "import":
        # Compatibilité des analyses créées avant l'introduction des instantanés.
        dossier_rows = await list_dossiers(db, organisation_id, import_id=import_id)
    else:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="L'analyse de base doit être relancée avant l'export.",
        )
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
            "conclusion": d.conclusion,
            "conclusion_motif": d.conclusion_motif,
            "raw_data": d.raw_data or {},
        }
        for d in dossier_rows
    ]
    content = build_workbook(dossiers, imp.exercice, reglages, exercice_annee, organisation_nom)
    suffixe = "base" if scope == "base" else str(import_id)
    fname = f"Tableau_{imp.exercice}_{suffixe}.xlsx"
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
    if payload.exercice != imp.exercice:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="L'exercice ne correspond pas à l'import.")

    analyse = await get_analyse_for_import(db, organisation_id, payload.import_id, scope=payload.scope)
    if analyse is None or analyse.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"L'analyse {payload.scope} doit être exécutée avant de générer le rapport.",
        )
    anomaly_rows = await list_anomalies(db, organisation_id, analyse_id=analyse.id)
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

    contenu = generate_analyse_report(
        payload.exercice,
        stats,
        anomaly_dicts,
        payload.instructions,
        scope=payload.scope,
    )

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
        metadata_json={
            "analyse_id": analyse.id,
            "scope": payload.scope,
            "source_import_ids": analyse.source_import_ids or [],
            "source_dossier_ids": analyse.source_dossier_ids or [],
        },
    )
    db.add(report)
    await db.commit()
    return report


def _decision_pv(
    decision: TableauDecision,
    numero_ordre: str | None,
    nom: str | None,
    prenom: str | None,
) -> dict[str, Any]:
    """Décision telle qu'elle doit apparaître au PV : nommée, pas seulement numérotée."""
    return {
        "decision_id": decision.id,
        "dossier_id": decision.dossier_id,
        "numero_ordre": numero_ordre,
        "membre": " ".join(part for part in [(nom or "").strip(), (prenom or "").strip()] if part),
        "type_decision": decision.type_decision,
        "decision": decision.decision,
        "motif": decision.motif,
    }


async def create_pv(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    payload: TableauPVCreate,
) -> TableauReport:
    imp = await get_import(db, organisation_id, payload.import_id)
    if imp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import introuvable")
    if payload.exercice != imp.exercice:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="L'exercice ne correspond pas à l'import.")

    analyse = await get_analyse_for_import(db, organisation_id, payload.import_id, scope=payload.scope)
    if analyse is None or analyse.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"L'analyse {payload.scope} doit être exécutée avant de générer le PV.",
        )
    stats = {
        "total_dossiers": analyse.total_dossiers if analyse else 0,
        "dossiers_complets": analyse.dossiers_complets if analyse else 0,
        "anomalies_count": analyse.anomalies_count if analyse else 0,
    }

    decision_ids = [int(v) for v in (analyse.source_decision_ids or [])]
    res = await db.execute(
        select(TableauDecision, TableauDossier.numero_ordre, TableauDossier.nom, TableauDossier.prenom)
        .join(TableauDossier, TableauDecision.dossier_id == TableauDossier.id)
        .where(
            TableauDecision.organisation_id == organisation_id,
            TableauDecision.id.in_(decision_ids),
        )
        .order_by(TableauDecision.created_at.asc(), TableauDecision.id.asc())
    )
    decisions = [_decision_pv(d, numero, nom, prenom) for d, numero, nom, prenom in res.all()]

    # Une décision de l'exercice qui ne retombe sur aucun dossier analysé — membre
    # sans n° d'ordre écarté de la consolidation, homonymes indistinguables,
    # dossier hors du périmètre choisi — ne doit pas disparaître du PV sans que
    # la commission le sache.
    hors_perimetre = select(TableauDecision, TableauDossier.numero_ordre, TableauDossier.nom, TableauDossier.prenom).join(
        TableauDossier, TableauDecision.dossier_id == TableauDossier.id
    ).where(
        TableauDecision.organisation_id == organisation_id,
        TableauDossier.exercice == imp.exercice,
    ).order_by(TableauDecision.created_at.asc(), TableauDecision.id.asc())
    if decision_ids:
        hors_perimetre = hors_perimetre.where(TableauDecision.id.notin_(decision_ids))
    orphelines = [
        _decision_pv(d, numero, nom, prenom)
        for d, numero, nom, prenom in (await db.execute(hors_perimetre)).all()
    ]

    contenu = generate_pv(
        payload.exercice,
        stats,
        decisions,
        payload.instructions,
        scope=payload.scope,
        decisions_hors_perimetre=orphelines,
    )

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
        metadata_json={
            "analyse_id": analyse.id,
            "scope": payload.scope,
            "source_import_ids": analyse.source_import_ids or [],
            "source_dossier_ids": analyse.source_dossier_ids or [],
            "source_decision_ids": decision_ids,
            "decisions_hors_perimetre": [d["decision_id"] for d in orphelines],
        },
    )
    db.add(report)
    await db.commit()
    return report
