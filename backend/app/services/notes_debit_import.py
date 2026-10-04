"""Import Excel des notes de débit des experts-comptables et des SEC.

La feuille fait foi. Une ligne par membre, une colonne par libellé :

    N° d'ordre | Nom          | Cotisation 2026 | Pénalité AG | Arriérés
    EC-0412    | KABONGO J.   |       600       |     100     |   450

Chaque ligne devient UNE note de débit — un encaissement non payé, rattaché à
l'expert —, et chaque cellule non vide une ligne de cette note, sous le libellé
de sa colonne. Ajouter une colonne au fichier, c'est ajouter un libellé : rien
n'est à régler dans le code.

Les montants viennent du fichier. Les tarifs réglés (Réglages → Tarifs) ne
servent qu'à deux choses : désigner le poste d'un libellé connu, et signaler un
montant qui s'en écarte. L'écart n'est jamais bloquant — la Comptabilité calcule
la cotisation d'une SEC sur son chiffre d'affaires, ce qu'aucun tarif ne sait
faire —, mais il est consigné, comme tout prix forcé.

Deux temps, sur le même code :
  - `analyser` lit le fichier et dit ce qu'il en ferait, sans rien écrire ;
  - `importer` relit le fichier, refait les mêmes contrôles et crée les notes
    dans une seule transaction : tout ou rien.

Relire plutôt que de garder l'aperçu en mémoire : le serveur reste sans état,
et ce qui est créé est exactement ce qui a été contrôlé.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import extract, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.horodatage import est_super_admin
from app.domain.notes_debit import (
    ARRIERE_AUTRE_PENALITE,
    ARRIERE_COTISATION,
    ARRIERE_PENALITE_APO,
    AUTRE_CREANCE,
    AUTRE_PENALITE,
    CATEGORIES_ARRIERE,
    CATEGORIES_IMPORTABLES,
    COTISATION_ANNUELLE,
    LEGACY,
    LIBELLES as LIBELLES_CATEGORIES,
    PENALITE_APO,
    libelle_categorie,
    normaliser_categorie,
)
from app.models.budget import BudgetExercice, BudgetPoste
from app.models.encaissement import Encaissement, EncaissementArticle
from app.models.encaissement_tarif import normaliser_libelle
from app.models.expert_comptable import ExpertComptable
from app.models.note_debit_import import NoteDebitImport
from app.models.service import Service
from app.models.service_rubrique import ServiceRubrique
from app.services.audit_service import log_action
from app.services.document_sequences import generate_document_number
from app.services.encaissement_tarifs import appliquer_tarifs, exercice_courant, succession, tarifs_resolus
from app.services.mouvements_budgetaires import hors_budget_initial_status
from app.services.service_access import get_user_service_ids

CENT = Decimal("0.01")

#: Lignes parcourues pour trouver l'en-tête : un fichier commence souvent par
#: un titre (« Notes de débit 2026 — Conseil provincial de Kinshasa »).
LIGNES_AVANT_ENTETE = 15

#: En-têtes de numérotation de lignes, pas de montants : « N° » vaut 1, 2, 3…
ENTETES_INDEX = {"n", "no", "n°", "nº", "#", "num", "numero", "n° ligne", "ordre"}

#: Catégories d'import, comme les onglets de l'import national des experts :
#: chacune a son modèle et sa validation. Une SEC déposée dans l'onglet des
#: experts-comptables (ou l'inverse) est une erreur de fichier, pas un détail.
CATEGORIES = {
    "toutes": "Toutes catégories",
    "ec": "Cotisations EC",
    "sec": "Cotisations SEC",
    "penalites": "Pénalités",
}

#: Mots qui désignent une colonne d'information même quand elle ne contient
#: que des nombres (un téléphone, une année, un nombre d'experts).
MOTS_INFORMATION = {
    "telephone", "tel", "phone", "gsm", "annee", "exercice", "nif", "code",
    "nombre", "nb", "effectif", "age", "id",
}

#: Les montants d'un encaissement sont tenus en USD ; le CDF n'est qu'une
#: devise de perception, convertie au paiement (`taux_change_applique`). Une
#: note libellée en CDF serait relue comme des dollars : elle est refusée.
DEVISES = {"USD"}
EXERCICE_MIN = 2000
EXERCICE_MAX = 2100

# Ordre stable : il sert uniquement de clé technique à l'écran de choix des
# postes. La catégorie stockée en base reste la donnée métier.
ORDRE_CATEGORIES = [
    COTISATION_ANNUELLE,
    ARRIERE_COTISATION,
    PENALITE_APO,
    ARRIERE_PENALITE_APO,
    AUTRE_PENALITE,
    ARRIERE_AUTRE_PENALITE,
    AUTRE_CREANCE,
]
INDEX_CATEGORIES = {categorie: 100 + index for index, categorie in enumerate(ORDRE_CATEGORIES)}

#: Ce que chaque onglet d'import accepte, comme chaque onglet a son modèle :
#: une pénalité déposée dans « Cotisations EC » (ou l'inverse) est une erreur
#: de fichier. Le fichier mixte accepte tout.
CATEGORIES_PAR_ONGLET = {
    "ec": {COTISATION_ANNUELLE, ARRIERE_COTISATION, AUTRE_CREANCE},
    "sec": {COTISATION_ANNUELLE, ARRIERE_COTISATION, AUTRE_CREANCE},
    "penalites": {PENALITE_APO, ARRIERE_PENALITE_APO, AUTRE_PENALITE, ARRIERE_AUTRE_PENALITE},
    "toutes": set(CATEGORIES_IMPORTABLES),
}


@dataclass
class ProblemeImport:
    feuille: str
    ligne: int
    champ: str
    valeur: Any
    message: str
    code: str
    niveau: str = "ERREUR"

    def dict(self) -> dict[str, Any]:
        return {
            "feuille": self.feuille,
            "ligne": self.ligne,
            "champ": self.champ,
            "valeur": "" if self.valeur is None else str(self.valeur),
            "message": self.message,
            "code": self.code,
            "niveau": self.niveau,
        }


@dataclass
class CreanceAnalysee:
    categorie: str
    exercice: int
    libelle: str
    montant: Decimal
    devise: str
    reference_decision: str | None = None
    observation: str | None = None
    feuille: str = "Cotisations EC"
    ligne: int = 0


@dataclass
class TableStructuree:
    nom: str
    ligne_entete: int
    colonnes: dict[str, int]
    lignes: list[tuple[int, list[Any]]]


@dataclass
class ClasseurStructure:
    principale: TableStructuree
    details: TableStructuree | None


# ---------------------------------------------------------------------------
# Lecture de la feuille
# ---------------------------------------------------------------------------


def _sans_accents(valeur: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", valeur) if not unicodedata.combining(c))


def normaliser_entete(valeur: Any) -> str:
    """« N° d’Ordre » → « n° d'ordre » : la clé de reconnaissance d'un en-tête."""
    texte = str(valeur or "").replace("’", "'").replace("\xa0", " ")
    return " ".join(_sans_accents(texte).lower().split())


def libelle_colonne(valeur: Any) -> str:
    """Le libellé tel qu'il s'imprimera sur la note : l'en-tête, espaces resserrés."""
    return " ".join(str(valeur or "").replace("\xa0", " ").split())[:255]


def _est_entete_numero(entete: str) -> bool:
    return (
        ("ordre" in entete and entete not in ENTETES_INDEX)
        or "matricule" in entete
        or "onec" in entete.split()
    )


def _est_entete_nom(entete: str) -> bool:
    return (
        entete.startswith("nom")
        or "denomination" in entete
        or "raison sociale" in entete
        or entete in {"membre", "expert", "expert-comptable", "expert comptable", "societe"}
    )


def _est_entete_arrieres(entete: str) -> bool:
    return "arriere" in entete


def _est_entete_total(entete: str) -> bool:
    mots = set(re.split(r"[^a-z0-9]+", entete))
    return bool(mots & {"total", "solde", "cumul"})


def lire_montant(valeur: Any) -> Decimal | None:
    """Un montant de cellule, quelle que soit sa forme ; `None` si la cellule est vide.

    Accepte « 1 500 », « 1.500,00 », « 1,500.00 », « $600 », « 600 USD ».
    Lève `ValueError` pour ce qui n'est pas un nombre : une cellule « payé » ou
    « exonéré » n'est pas un zéro, et l'importer comme tel effacerait une dette.
    """
    if valeur is None:
        return None
    if isinstance(valeur, bool):
        raise ValueError(str(valeur))
    if isinstance(valeur, (int, float, Decimal)):
        return Decimal(str(valeur)).quantize(CENT)
    texte = str(valeur).strip()
    if texte in {"", "-", "—", "–"}:
        return None
    texte = re.sub(r"(?i)usd|us\$|\$|fc|cdf", "", texte)
    texte = texte.replace("\xa0", "").replace(" ", "").replace("'", "")
    if "," in texte and "." in texte:
        if texte.rfind(",") > texte.rfind("."):
            texte = texte.replace(".", "").replace(",", ".")
        else:
            texte = texte.replace(",", "")
    elif "," in texte:
        texte = texte.replace(",", "") if re.fullmatch(r"-?\d{1,3}(,\d{3})+", texte) else texte.replace(",", ".")
    try:
        return Decimal(texte).quantize(CENT)
    except InvalidOperation as exc:
        raise ValueError(str(valeur)) from exc


def cle_numero_ordre(valeur: Any) -> str:
    """Clé de rapprochement d'un n° d'ordre : « ec-0412 », « EC 412 » → « EC412 »."""
    if valeur is None:
        return ""
    if isinstance(valeur, float) and valeur.is_integer():
        valeur = int(valeur)
    cle = re.sub(r"[^A-Z0-9]", "", _sans_accents(str(valeur)).upper())
    return re.sub(r"(?<!\d)0+(?=\d)", "", cle)


def cle_nom(valeur: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", _sans_accents(str(valeur or "")).lower()).split())


ENTETES_PRINCIPAUX = {
    "numero_note_externe": {"n° note externe", "no note externe", "numero note externe", "note externe"},
    "date_note": {"date note", "date de la note"},
    "numero_ordre": {"n° d'ordre", "no d'ordre", "numero d'ordre", "numero ordre", "matricule"},
    "nom": {"nom / raison sociale", "nom raison sociale", "nom", "raison sociale", "denomination"},
    "type_membre": {"type membre", "type de membre"},
    "exercice": {"exercice n", "exercice", "annee"},
    COTISATION_ANNUELLE: {"cotisation n", "cotisation annuelle", "cotisation"},
    ARRIERE_COTISATION: {"arrieres cotisations", "arriere cotisation", "arrieres de cotisations"},
    PENALITE_APO: {"penalite apo n", "penalite apo"},
    ARRIERE_PENALITE_APO: {"arrieres penalite apo", "arriere penalite apo"},
    AUTRE_PENALITE: {"autre penalite"},
    ARRIERE_AUTRE_PENALITE: {"arrieres autres penalites", "arriere autre penalite"},
    AUTRE_CREANCE: {"autres creances", "autre creance"},
    "total": {"total note", "montant total", "total"},
    "devise": {"devise", "currency"},
    "date_echeance": {"date echeance", "date d'echeance", "echeance"},
    "reference_decision": {"reference / decision", "reference decision", "reference", "decision"},
    "observation": {"observation", "observations"},
}

ENTETES_DETAILS = {
    "numero_note_externe": ENTETES_PRINCIPAUX["numero_note_externe"],
    "numero_ordre": ENTETES_PRINCIPAUX["numero_ordre"],
    "categorie": {"categorie", "nature", "type creance"},
    "exercice": {"exercice", "annee"},
    "montant": {"montant", "amount"},
    "devise": ENTETES_PRINCIPAUX["devise"],
    "libelle": {"motif / libelle", "motif libelle", "motif", "libelle"},
    "reference_decision": ENTETES_PRINCIPAUX["reference_decision"],
    "observation": ENTETES_PRINCIPAUX["observation"],
}


def _index_entetes(ligne: list[Any], aliases: dict[str, set[str]]) -> dict[str, int]:
    reconnus = {
        normaliser_entete(alias): champ
        for champ, valeurs in aliases.items()
        for alias in valeurs
    }
    resultat: dict[str, int] = {}
    for index, brut in enumerate(ligne):
        champ = reconnus.get(normaliser_entete(brut))
        if champ is not None and champ not in resultat:
            resultat[champ] = index
    return resultat


def _table_structuree(
    feuille: Any,
    aliases: dict[str, set[str]],
    requis: set[str],
    un_parmi: set[str] | None = None,
) -> TableStructuree | None:
    toutes = [list(ligne) for ligne in feuille.iter_rows(values_only=True)]
    for position, ligne in enumerate(toutes[:LIGNES_AVANT_ENTETE]):
        colonnes = _index_entetes(ligne, aliases)
        if requis <= set(colonnes) and (not un_parmi or un_parmi & set(colonnes)):
            donnees = [
                (position + 2 + decalage, valeurs)
                for decalage, valeurs in enumerate(toutes[position + 1 :])
                if any(v not in (None, "") for v in valeurs)
            ]
            return TableStructuree(
                nom=feuille.title,
                ligne_entete=position + 1,
                colonnes=colonnes,
                lignes=donnees,
            )
    return None


def lire_classeur_structure(contenu: bytes) -> ClasseurStructure | None:
    """Lit le nouveau modèle à deux feuilles, ou rend ``None`` pour l'ancien.

    Le format est reconnu par ses colonnes structurantes, pas uniquement par le
    nom de l'onglet : renommer « Cotisations EC » ne doit pas rendre un fichier
    historique inutilisable.
    """

    try:
        from openpyxl import load_workbook
    except Exception:  # pragma: no cover
        raise HTTPException(status_code=500, detail="openpyxl n'est pas installé")
    try:
        classeur = load_workbook(filename=BytesIO(contenu), data_only=True, read_only=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Fichier illisible : déposez un classeur Excel (.xlsx).")
    try:
        principale = None
        detail = None
        for feuille in classeur.worksheets:
            if principale is None:
                # Une colonne de créance suffit : le modèle « Pénalités » n'a
                # pas de colonne « Cotisation N ».
                candidate = _table_structuree(
                    feuille,
                    ENTETES_PRINCIPAUX,
                    {"numero_ordre", "exercice"},
                    set(ORDRE_CATEGORIES),
                )
                # L'ancien modèle « Cotisation 2026 » n'est volontairement pas
                # reconnu ici : il reste traité par le lecteur historique.
                if candidate is not None:
                    principale = candidate
            if detail is None:
                detail = _table_structuree(
                    feuille,
                    ENTETES_DETAILS,
                    {"categorie", "exercice", "montant"},
                )
        if principale is None:
            return None
        return ClasseurStructure(principale=principale, details=detail)
    finally:
        classeur.close()


def lire_date(valeur: Any) -> date | None:
    if valeur in (None, ""):
        return None
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    texte = str(valeur).strip()
    for format_date in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(texte, format_date).date()
        except ValueError:
            pass
    raise ValueError(texte)


def lire_exercice(valeur: Any) -> int:
    if isinstance(valeur, bool) or valeur in (None, ""):
        raise ValueError(str(valeur or ""))
    try:
        exercice = int(float(str(valeur).strip()))
    except (TypeError, ValueError) as exc:
        raise ValueError(str(valeur)) from exc
    if not EXERCICE_MIN <= exercice <= EXERCICE_MAX:
        raise ValueError(str(valeur))
    return exercice


def lire_devise(valeur: Any, *, defaut: str = "USD") -> str:
    devise = str(valeur or defaut).strip().upper()
    if devise not in DEVISES:
        raise ValueError(str(valeur or ""))
    return devise


def _texte_optionnel(valeur: Any, limite: int | None = None) -> str | None:
    texte = " ".join(str(valeur or "").replace("\xa0", " ").split())
    if not texte:
        return None
    return texte[:limite] if limite else texte


@dataclass
class Colonne:
    index: int
    libelle: str
    arrieres: bool = False


@dataclass
class Feuille:
    ligne_entete: int
    col_numero: int | None
    col_nom: int | None
    col_total: int | None
    colonnes: list[Colonne]
    ignorees: list[dict[str, str]]
    #: (n° de ligne Excel, valeurs)
    lignes: list[tuple[int, list[Any]]]


def lire_feuille(contenu: bytes) -> Feuille:
    """Repère l'en-tête et classe les colonnes : identité, montants, le reste."""
    try:
        from openpyxl import load_workbook
    except Exception:  # pragma: no cover - dépendance de l'image
        raise HTTPException(status_code=500, detail="openpyxl n'est pas installé")
    try:
        classeur = load_workbook(filename=BytesIO(contenu), data_only=True, read_only=True)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Fichier illisible : déposez un classeur Excel (.xlsx).",
        )
    feuille = classeur.active
    toutes = [list(ligne) for ligne in feuille.iter_rows(values_only=True)]
    classeur.close()

    ligne_entete = None
    for position, ligne in enumerate(toutes[:LIGNES_AVANT_ENTETE]):
        entetes = [normaliser_entete(v) for v in ligne]
        if any(_est_entete_numero(e) for e in entetes if e) or (
            any(_est_entete_nom(e) for e in entetes if e) and sum(1 for e in entetes if e) >= 2
        ):
            ligne_entete = position
            break
    if ligne_entete is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Aucune ligne d'en-tête reconnue : la feuille doit avoir une colonne « N° d'ordre » ou « Nom ».",
        )

    brutes = toutes[ligne_entete]
    # N° de ligne Excel (1-indexé) compté AVANT d'écarter les lignes vides :
    # c'est celui que l'utilisateur retrouvera dans son fichier.
    donnees = [
        (ligne_entete + 2 + decalage, ligne)
        for decalage, ligne in enumerate(toutes[ligne_entete + 1:])
        if any(v not in (None, "") for v in ligne)
    ]

    col_numero = col_nom = col_total = None
    colonnes: list[Colonne] = []
    ignorees: list[dict[str, str]] = []
    for index, brut in enumerate(brutes):
        entete = normaliser_entete(brut)
        if not entete:
            continue
        libelle = libelle_colonne(brut)
        if col_numero is None and _est_entete_numero(entete):
            col_numero = index
            continue
        if col_nom is None and _est_entete_nom(entete):
            col_nom = index
            continue
        if entete in ENTETES_INDEX:
            ignorees.append({"libelle": libelle, "raison": "Numérotation des lignes"})
            continue
        if _est_entete_total(entete):
            if col_total is None:
                col_total = index
            ignorees.append({"libelle": libelle, "raison": "Total : recalculé, et comparé à la somme des colonnes"})
            continue

        valeurs = [ligne[index] for _, ligne in donnees if index < len(ligne) and ligne[index] not in (None, "")]
        arrieres = _est_entete_arrieres(entete)
        if not valeurs and not arrieres:
            ignorees.append({"libelle": libelle, "raison": "Colonne vide"})
            continue
        if not arrieres and set(re.split(r"[^a-z0-9]+", entete)) & MOTS_INFORMATION:
            ignorees.append({"libelle": libelle, "raison": "Colonne d'information"})
            continue
        numeriques = 0
        for valeur in valeurs:
            try:
                lire_montant(valeur)
                numeriques += 1
            except ValueError:
                pass
        # Une colonne d'information (province, catégorie…) n'a aucun nombre ; une
        # colonne de montants peut en avoir un ou deux mal saisis, que le contrôle
        # signalera ligne par ligne plutôt que de taire la colonne entière.
        if not arrieres and numeriques * 2 < len(valeurs):
            ignorees.append({"libelle": libelle, "raison": "Colonne d'information"})
            continue
        colonnes.append(Colonne(index=index, libelle=libelle, arrieres=arrieres))

    if col_numero is None and col_nom is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La feuille doit avoir une colonne « N° d'ordre » (ou, à défaut, « Nom »).",
        )
    if not colonnes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Aucune colonne de montants : chaque libellé de la note doit avoir sa colonne.",
        )
    return Feuille(
        ligne_entete=ligne_entete + 1,
        col_numero=col_numero,
        col_nom=col_nom,
        col_total=col_total,
        colonnes=colonnes,
        ignorees=ignorees,
        lignes=donnees,
    )


# ---------------------------------------------------------------------------
# Contexte : experts, postes, services, tarifs, notes déjà émises
# ---------------------------------------------------------------------------


async def services_disponibles(db: AsyncSession, user: Any, tenant_id: int) -> list[Service]:
    """Les services sous lesquels cet utilisateur peut émettre une note."""
    requete = select(Service).where(Service.organisation_id == tenant_id, Service.is_active.is_(True))
    if (getattr(user, "role", "") or "").lower() not in {"admin", "super_admin"}:
        ids = await get_user_service_ids(db, user)
        if not ids:
            return []
        requete = requete.where(Service.id.in_(ids))
    return list((await db.execute(requete.order_by(Service.libelle))).scalars().all())


async def resoudre_service(db: AsyncSession, user: Any, tenant_id: int, service_id: int | None) -> int | None:
    """Même règle que la saisie d'un encaissement : un agent émet sous l'un de ses services."""
    role = (getattr(user, "role", "") or "").lower()
    if role in {"admin", "super_admin"}:
        if service_id is None:
            return None
        trouve = (
            await db.execute(
                select(Service.id).where(
                    Service.id == service_id, Service.organisation_id == tenant_id, Service.is_active.is_(True)
                )
            )
        ).scalar_one_or_none()
        if trouve is None:
            raise HTTPException(status_code=400, detail="service_id invalide")
        return service_id
    ids = await get_user_service_ids(db, user)
    if not ids:
        raise HTTPException(status_code=403, detail="Aucun service assigné")
    if service_id is None:
        if len(ids) == 1:
            return ids[0]
        raise HTTPException(status_code=400, detail="Choisissez le service sous lequel émettre les notes.")
    if service_id not in ids:
        raise HTTPException(status_code=403, detail="Accès interdit à ce service")
    return service_id


async def postes_disponibles(
    db: AsyncSession, tenant_id: int, service_id: int | None
) -> tuple[BudgetExercice | None, list[BudgetPoste]]:
    """Les postes de recette de l'exercice courant, bornés aux rubriques du service."""
    exercice = await exercice_courant(db, tenant_id)
    if exercice is None:
        return None, []
    requete = select(BudgetPoste).where(
        BudgetPoste.organisation_id == tenant_id,
        BudgetPoste.exercice_id == exercice.id,
        BudgetPoste.is_deleted.is_(False),
        BudgetPoste.active.is_(True),
        func.upper(BudgetPoste.type) == "RECETTE",
    )
    if service_id is not None:
        requete = requete.where(
            BudgetPoste.id.in_(
                select(ServiceRubrique.budget_poste_id).where(ServiceRubrique.service_id == service_id)
            )
        )
    return exercice, list((await db.execute(requete.order_by(BudgetPoste.code))).scalars().all())


async def _codes_arrieres(db: AsyncSession, tenant_id: int, exercice: BudgetExercice) -> set[str]:
    """Les codes que l'exercice précédent désigne comme ses postes d'arriérés."""
    lignes = (
        await db.execute(
            select(BudgetPoste.code_poste_arrieres)
            .join(BudgetExercice, BudgetExercice.id == BudgetPoste.exercice_id)
            .where(
                BudgetPoste.organisation_id == tenant_id,
                BudgetExercice.annee == exercice.annee - 1,
                BudgetPoste.is_deleted.is_(False),
                BudgetPoste.code_poste_arrieres.is_not(None),
            )
        )
    ).scalars().all()
    return {code.strip().upper() for code in lignes if code and code.strip()}


async def _experts(db: AsyncSession) -> tuple[dict[str, ExpertComptable], dict[str, list[ExpertComptable]]]:
    """Le référentiel, indexé par n° d'ordre et par nom."""
    experts = (await db.execute(select(ExpertComptable))).scalars().all()
    par_numero: dict[str, ExpertComptable] = {}
    par_nom: dict[str, list[ExpertComptable]] = {}
    for expert in experts:
        cle = cle_numero_ordre(expert.numero_ordre)
        if cle:
            par_numero.setdefault(cle, expert)
        par_nom.setdefault(cle_nom(expert.nom_denomination), []).append(expert)
    return par_numero, par_nom


async def _deja_emises(
    db: AsyncSession, tenant_id: int, expert_ids: set[uuid.UUID], annee: int
) -> dict[tuple[uuid.UUID, str], str]:
    """(expert, libellé) → n° de la note qui le porte déjà cette année."""
    if not expert_ids:
        return {}
    lignes = (
        await db.execute(
            select(Encaissement.expert_comptable_id, EncaissementArticle.libelle, Encaissement.numero_recu)
            .join(EncaissementArticle, EncaissementArticle.encaissement_id == Encaissement.id)
            .where(
                Encaissement.organisation_id == tenant_id,
                Encaissement.expert_comptable_id.in_(expert_ids),
                Encaissement.is_deleted.is_(False),
                Encaissement.est_proforma.is_(False),
                Encaissement.statut_operation != "ANNULEE",
                func.coalesce(Encaissement.exercice, extract("year", Encaissement.date_encaissement)) == annee,
            )
        )
    ).all()
    return {(ligne[0], normaliser_libelle(ligne[1])): ligne[2] or "—" for ligne in lignes}


# ---------------------------------------------------------------------------
# Analyse
# ---------------------------------------------------------------------------


@dataclass
class LigneAnalysee:
    ligne: int
    numero_ordre: str
    nom: str
    expert: ExpertComptable | None = None
    montants: dict[int, Decimal] = field(default_factory=dict)
    erreurs: list[str] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)
    doublon: bool = False
    numero_note_externe: str | None = None
    date_note: date | None = None
    exercice: int | None = None
    devise: str = "USD"
    date_echeance: date | None = None
    reference_decision: str | None = None
    observation: str | None = None
    total_attendu: Decimal | None = None
    creances: list[CreanceAnalysee] = field(default_factory=list)
    resume_montants: dict[str, Decimal] = field(default_factory=dict)
    problemes: list[ProblemeImport] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return sum(self.montants.values(), Decimal("0.00"))

    @property
    def statut(self) -> str:
        if self.erreurs:
            return "erreur"
        if self.avertissements or self.doublon:
            return "avertissement"
        return "ok"


@dataclass
class Analyse:
    feuille: Feuille
    exercice: BudgetExercice | None
    annee: int
    lignes: list[LigneAnalysee]
    colonnes: list[dict[str, Any]]
    postes: list[BudgetPoste]
    services: list[Service]
    service_id: int | None
    #: index de colonne → (tarif, poste du tarif)
    tarifs: dict[int, tuple[Any, BudgetPoste | None]]
    categorie: str = "toutes"
    format_import: str = "historique"
    problemes: list[ProblemeImport] = field(default_factory=list)


def _montant_texte(valeur: Decimal) -> str:
    return f"{valeur:,.2f}".replace(",", " ")


def _categorie_legacy(libelle: str) -> str:
    normalise = normaliser_entete(libelle)
    if "arriere" in normalise:
        # Sans feuille de détail, l'exercice réel est inconnu : LEGACY est plus
        # honnête qu'une ventilation inventée.
        return LEGACY
    if "cotis" in normalise:
        return COTISATION_ANNUELLE
    if "penalit" in normalise and "apo" in normalise:
        return PENALITE_APO
    if "penalit" in normalise:
        return AUTRE_PENALITE
    return AUTRE_CREANCE


def _exercice_legacy(libelle: str, defaut: int) -> int:
    trouve = re.search(r"\b(20\d{2}|2100)\b", libelle or "")
    return int(trouve.group(1)) if trouve else defaut


def _cellule(table: TableStructuree, valeurs: list[Any], champ: str) -> Any:
    index = table.colonnes.get(champ)
    return valeurs[index] if index is not None and index < len(valeurs) else None


def _signaler(
    ligne: LigneAnalysee | None,
    problemes: list[ProblemeImport],
    *,
    feuille: str,
    numero_ligne: int,
    champ: str,
    valeur: Any,
    message: str,
    code: str,
    niveau: str = "ERREUR",
) -> None:
    probleme = ProblemeImport(
        feuille=feuille,
        ligne=numero_ligne,
        champ=champ,
        valeur=valeur,
        message=message,
        code=code,
        niveau=niveau,
    )
    problemes.append(probleme)
    if ligne is not None:
        ligne.problemes.append(probleme)
        texte = f"{champ} : {message}"
        if niveau == "ERREUR":
            ligne.erreurs.append(texte)
        else:
            ligne.avertissements.append(texte)


def _libelle_ligne_principale(categorie: str, exercice: int, observation: str | None) -> str:
    if categorie in {AUTRE_PENALITE, AUTRE_CREANCE} and observation:
        return observation[:255]
    return f"{libelle_categorie(categorie)} {exercice}"[:255]


async def _analyser_structure(
    db: AsyncSession,
    *,
    tenant_id: int,
    user: Any,
    classeur: ClasseurStructure,
    service_id: int | None,
    categorie_import: str,
) -> Analyse:
    """Analyse le classeur métier sans écrire en base."""

    services = await services_disponibles(db, user, tenant_id)
    if service_id is not None:
        service_retenu = await resoudre_service(db, user, tenant_id, service_id)
    elif (getattr(user, "role", "") or "").lower() not in {"admin", "super_admin"} and len(services) == 1:
        service_retenu = services[0].id
    else:
        service_retenu = None
    exercice_budget, postes = await postes_disponibles(db, tenant_id, service_retenu)

    principale = classeur.principale
    par_numero, par_nom = await _experts(db)
    problemes: list[ProblemeImport] = []
    lignes: list[LigneAnalysee] = []
    par_externe: dict[str, list[LigneAnalysee]] = {}
    par_ordre: dict[str, list[LigneAnalysee]] = {}

    for numero_ligne, valeurs in principale.lignes:
        numero_brut = _cellule(principale, valeurs, "numero_ordre")
        numero = _texte_optionnel(numero_brut, 100) or ""
        nom = _texte_optionnel(_cellule(principale, valeurs, "nom"), 300) or ""
        externe = _texte_optionnel(_cellule(principale, valeurs, "numero_note_externe"), 100)
        ligne = LigneAnalysee(
            ligne=numero_ligne,
            numero_ordre=numero,
            nom=nom,
            numero_note_externe=externe,
        )

        cle_ordre = cle_numero_ordre(numero)
        if not cle_ordre:
            _signaler(
                ligne,
                problemes,
                feuille=principale.nom,
                numero_ligne=numero_ligne,
                champ="N° d'ordre",
                valeur=numero_brut,
                message="numéro d'ordre absent ou invalide",
                code="NUMERO_ORDRE_INVALIDE",
            )
        else:
            ligne.expert = par_numero.get(cle_ordre)
            if ligne.expert is None:
                _signaler(
                    ligne,
                    problemes,
                    feuille=principale.nom,
                    numero_ligne=numero_ligne,
                    champ="N° d'ordre",
                    valeur=numero_brut,
                    message="membre introuvable dans le référentiel des experts",
                    code="MEMBRE_INTROUVABLE",
                )
            par_ordre.setdefault(cle_ordre, []).append(ligne)

        if externe:
            par_externe.setdefault(externe.casefold(), []).append(ligne)

        try:
            ligne.exercice = lire_exercice(_cellule(principale, valeurs, "exercice"))
        except ValueError:
            _signaler(
                ligne,
                problemes,
                feuille=principale.nom,
                numero_ligne=numero_ligne,
                champ="Exercice N",
                valeur=_cellule(principale, valeurs, "exercice"),
                message=f"année invalide ({EXERCICE_MIN} à {EXERCICE_MAX} attendue)",
                code="EXERCICE_INVALIDE",
            )

        try:
            ligne.devise = lire_devise(_cellule(principale, valeurs, "devise"))
        except ValueError:
            _signaler(
                ligne,
                problemes,
                feuille=principale.nom,
                numero_ligne=numero_ligne,
                champ="Devise",
                valeur=_cellule(principale, valeurs, "devise"),
                message="devise non gérée : les notes de débit sont tenues en USD",
                code="DEVISE_INVALIDE",
            )

        try:
            ligne.date_note = lire_date(_cellule(principale, valeurs, "date_note"))
        except ValueError:
            _signaler(
                ligne,
                problemes,
                feuille=principale.nom,
                numero_ligne=numero_ligne,
                champ="Date note",
                valeur=_cellule(principale, valeurs, "date_note"),
                message="date invalide",
                code="DATE_INVALIDE",
            )
        if ligne.date_note is None:
            ligne.date_note = datetime.now(timezone.utc).date()
            _signaler(
                ligne,
                problemes,
                feuille=principale.nom,
                numero_ligne=numero_ligne,
                champ="Date note",
                valeur=None,
                message="date absente : la date du jour sera utilisée",
                code="DATE_ABSENTE",
                niveau="AVERTISSEMENT",
            )
        elif ligne.date_note > datetime.now(timezone.utc).date():
            _signaler(
                ligne,
                problemes,
                feuille=principale.nom,
                numero_ligne=numero_ligne,
                champ="Date note",
                valeur=ligne.date_note,
                message="la date de note ne peut pas être future",
                code="DATE_INVALIDE",
            )
        elif ligne.date_note < datetime.now(timezone.utc).date() and not est_super_admin(user):
            # Même règle que la saisie (`resoudre_date_operation`) : seul un
            # super administrateur antidate une opération financière.
            _signaler(
                ligne,
                problemes,
                feuille=principale.nom,
                numero_ligne=numero_ligne,
                champ="Date note",
                valeur=ligne.date_note,
                message="seul un super administrateur peut dater une note d'un autre jour",
                code="DATE_ANTERIEURE",
            )

        try:
            ligne.date_echeance = lire_date(_cellule(principale, valeurs, "date_echeance"))
        except ValueError:
            _signaler(
                ligne,
                problemes,
                feuille=principale.nom,
                numero_ligne=numero_ligne,
                champ="Date échéance",
                valeur=_cellule(principale, valeurs, "date_echeance"),
                message="date invalide",
                code="DATE_INVALIDE",
            )
        if ligne.date_echeance and ligne.date_note and ligne.date_echeance < ligne.date_note:
            _signaler(
                ligne,
                problemes,
                feuille=principale.nom,
                numero_ligne=numero_ligne,
                champ="Date échéance",
                valeur=ligne.date_echeance,
                message="l'échéance est antérieure à la date de la note",
                code="DATE_INVALIDE",
            )

        ligne.reference_decision = _texte_optionnel(
            _cellule(principale, valeurs, "reference_decision"), 255
        )
        ligne.observation = _texte_optionnel(_cellule(principale, valeurs, "observation"))

        if ligne.expert is not None:
            type_brut = _texte_optionnel(_cellule(principale, valeurs, "type_membre"))
            if type_brut:
                type_normalise = re.sub(r"[^a-z]", "", _sans_accents(type_brut).lower())
                attendu_sec = ligne.expert.type_ec == "SEC"
                fourni_sec = type_normalise in {"sec", "societe", "societedexpertisecomptable"}
                fourni_ec = type_normalise in {"ec", "expertcomptable", "expert"}
                if not (fourni_sec or fourni_ec) or fourni_sec != attendu_sec:
                    _signaler(
                        ligne,
                        problemes,
                        feuille=principale.nom,
                        numero_ligne=numero_ligne,
                        champ="Type membre",
                        valeur=type_brut,
                        message=f"type incompatible avec le référentiel ({'SEC' if attendu_sec else 'EC'} attendu)",
                        code="TYPE_MEMBRE_INVALIDE",
                    )
            attendu_sec = ligne.expert.type_ec == "SEC"
            if categorie_import == "ec" and attendu_sec:
                _signaler(
                    ligne,
                    problemes,
                    feuille=principale.nom,
                    numero_ligne=numero_ligne,
                    champ="Type membre",
                    valeur=ligne.expert.type_ec,
                    message="une SEC doit être importée dans l'onglet « Cotisations SEC »",
                    code="TYPE_MEMBRE_INVALIDE",
                )
            elif categorie_import == "sec" and not attendu_sec:
                _signaler(
                    ligne,
                    problemes,
                    feuille=principale.nom,
                    numero_ligne=numero_ligne,
                    champ="Type membre",
                    valeur=ligne.expert.type_ec,
                    message="un expert-comptable doit être importé dans l'onglet « Cotisations EC »",
                    code="TYPE_MEMBRE_INVALIDE",
                )
            if nom and cle_nom(nom) != cle_nom(ligne.expert.nom_denomination):
                _signaler(
                    ligne,
                    problemes,
                    feuille=principale.nom,
                    numero_ligne=numero_ligne,
                    champ="Nom / Raison sociale",
                    valeur=nom,
                    message=f"le référentiel contient « {ligne.expert.nom_denomination} » ; le n° d'ordre fait foi",
                    code="NOM_DIFFERENT",
                    niveau="AVERTISSEMENT",
                )

        for categorie_ligne in ORDRE_CATEGORIES:
            brut = _cellule(principale, valeurs, categorie_ligne)
            try:
                montant = lire_montant(brut)
            except ValueError:
                _signaler(
                    ligne,
                    problemes,
                    feuille=principale.nom,
                    numero_ligne=numero_ligne,
                    champ=libelle_categorie(categorie_ligne),
                    valeur=brut,
                    message="montant invalide",
                    code="MONTANT_INVALIDE",
                )
                continue
            if montant is None:
                continue
            if montant < 0:
                _signaler(
                    ligne,
                    problemes,
                    feuille=principale.nom,
                    numero_ligne=numero_ligne,
                    champ=libelle_categorie(categorie_ligne),
                    valeur=brut,
                    message="le montant doit être positif ou nul",
                    code="MONTANT_INVALIDE",
                )
                continue
            if montant > 0 and categorie_ligne not in CATEGORIES_PAR_ONGLET[categorie_import]:
                _signaler(
                    ligne,
                    problemes,
                    feuille=principale.nom,
                    numero_ligne=numero_ligne,
                    champ=libelle_categorie(categorie_ligne),
                    valeur=brut,
                    message=f"cette créance ne s'importe pas dans l'onglet « {CATEGORIES[categorie_import]} »",
                    code="CATEGORIE_HORS_ONGLET",
                )
                continue
            ligne.resume_montants[categorie_ligne] = montant

        total_brut = _cellule(principale, valeurs, "total")
        try:
            ligne.total_attendu = lire_montant(total_brut)
        except ValueError:
            _signaler(
                ligne,
                problemes,
                feuille=principale.nom,
                numero_ligne=numero_ligne,
                champ="Total note",
                valeur=total_brut,
                message="montant total invalide",
                code="MONTANT_INVALIDE",
            )
        lignes.append(ligne)

    # Un numéro externe identifie une note sans ambiguïté. Sans numéro externe,
    # le n° d'ordre est une clé technique sûre seulement s'il n'apparaît qu'une
    # fois dans le fichier.
    for externe, groupe in par_externe.items():
        if len(groupe) > 1:
            for ligne in groupe:
                _signaler(
                    ligne,
                    problemes,
                    feuille=principale.nom,
                    numero_ligne=ligne.ligne,
                    champ="N° note externe",
                    valeur=ligne.numero_note_externe,
                    message="numéro externe présent plusieurs fois dans le fichier",
                    code="DOUBLON_NUMERO_EXTERNE",
                )
    for cle_ordre, groupe in par_ordre.items():
        sans_externe = [ligne for ligne in groupe if not ligne.numero_note_externe]
        if len(sans_externe) > 1:
            for ligne in sans_externe:
                _signaler(
                    ligne,
                    problemes,
                    feuille=principale.nom,
                    numero_ligne=ligne.ligne,
                    champ="N° d'ordre",
                    valeur=ligne.numero_ordre,
                    message="plusieurs notes sans numéro externe rendent le rattachement du détail ambigu",
                    code="DOUBLON",
                )

    # Ventilation de la deuxième feuille.
    detail = classeur.details
    if detail is not None:
        for numero_ligne, valeurs in detail.lignes:
            externe = _texte_optionnel(_cellule(detail, valeurs, "numero_note_externe"), 100)
            numero_ordre = _texte_optionnel(_cellule(detail, valeurs, "numero_ordre"), 100) or ""
            cible: LigneAnalysee | None = None
            if externe:
                groupe = par_externe.get(externe.casefold(), [])
                cible = groupe[0] if len(groupe) == 1 else None
            elif numero_ordre:
                groupe = par_ordre.get(cle_numero_ordre(numero_ordre), [])
                cible = groupe[0] if len(groupe) == 1 else None
            if cible is None:
                _signaler(
                    None,
                    problemes,
                    feuille=detail.nom,
                    numero_ligne=numero_ligne,
                    champ="N° note externe / N° d'ordre",
                    valeur=externe or numero_ordre,
                    message="aucune note d'en-tête ne correspond de façon unique",
                    code="RATTACHEMENT_INTROUVABLE",
                )
                continue
            if numero_ordre and cle_numero_ordre(numero_ordre) != cle_numero_ordre(cible.numero_ordre):
                _signaler(
                    cible,
                    problemes,
                    feuille=detail.nom,
                    numero_ligne=numero_ligne,
                    champ="N° d'ordre",
                    valeur=numero_ordre,
                    message="le numéro d'ordre ne correspond pas à l'en-tête de la note",
                    code="NUMERO_ORDRE_INVALIDE",
                )
                continue

            categorie_brute = _cellule(detail, valeurs, "categorie")
            categorie_ligne = normaliser_categorie(_texte_optionnel(categorie_brute))
            if categorie_ligne not in CATEGORIES_IMPORTABLES:
                _signaler(
                    cible,
                    problemes,
                    feuille=detail.nom,
                    numero_ligne=numero_ligne,
                    champ="Catégorie",
                    valeur=categorie_brute,
                    message="catégorie de créance inconnue",
                    code="CATEGORIE_INCONNUE",
                )
                continue
            if categorie_ligne not in CATEGORIES_PAR_ONGLET[categorie_import]:
                _signaler(
                    cible,
                    problemes,
                    feuille=detail.nom,
                    numero_ligne=numero_ligne,
                    champ="Catégorie",
                    valeur=categorie_brute,
                    message=f"cette créance ne s'importe pas dans l'onglet « {CATEGORIES[categorie_import]} »",
                    code="CATEGORIE_HORS_ONGLET",
                )
                continue
            try:
                exercice_ligne = lire_exercice(_cellule(detail, valeurs, "exercice"))
            except ValueError:
                _signaler(
                    cible,
                    problemes,
                    feuille=detail.nom,
                    numero_ligne=numero_ligne,
                    champ="Exercice",
                    valeur=_cellule(detail, valeurs, "exercice"),
                    message=f"année invalide ({EXERCICE_MIN} à {EXERCICE_MAX} attendue)",
                    code="EXERCICE_INVALIDE",
                )
                continue
            try:
                montant_ligne = lire_montant(_cellule(detail, valeurs, "montant"))
            except ValueError:
                montant_ligne = None
            if montant_ligne is None or montant_ligne <= 0:
                _signaler(
                    cible,
                    problemes,
                    feuille=detail.nom,
                    numero_ligne=numero_ligne,
                    champ="Montant",
                    valeur=_cellule(detail, valeurs, "montant"),
                    message="un montant strictement positif est requis pour une ligne de détail",
                    code="MONTANT_INVALIDE",
                )
                continue
            try:
                devise_ligne = lire_devise(_cellule(detail, valeurs, "devise"), defaut=cible.devise)
            except ValueError:
                _signaler(
                    cible,
                    problemes,
                    feuille=detail.nom,
                    numero_ligne=numero_ligne,
                    champ="Devise",
                    valeur=_cellule(detail, valeurs, "devise"),
                    message="devise non gérée : les notes de débit sont tenues en USD",
                    code="DEVISE_INVALIDE",
                )
                continue
            libelle = _texte_optionnel(_cellule(detail, valeurs, "libelle"), 255)
            if categorie_ligne in {AUTRE_PENALITE, ARRIERE_AUTRE_PENALITE} and not libelle:
                _signaler(
                    cible,
                    problemes,
                    feuille=detail.nom,
                    numero_ligne=numero_ligne,
                    champ="Motif / Libellé",
                    valeur=None,
                    message="un motif est obligatoire pour une autre pénalité",
                    code="LIBELLE_REQUIS",
                )
                continue
            if categorie_ligne in CATEGORIES_ARRIERE and cible.exercice and exercice_ligne >= cible.exercice:
                _signaler(
                    cible,
                    problemes,
                    feuille=detail.nom,
                    numero_ligne=numero_ligne,
                    champ="Exercice",
                    valeur=exercice_ligne,
                    message=f"un arriéré doit être antérieur à l'exercice de la note ({cible.exercice})",
                    code="EXERCICE_INVALIDE",
                )
                continue
            if categorie_ligne == COTISATION_ANNUELLE and cible.exercice and exercice_ligne != cible.exercice:
                _signaler(
                    cible,
                    problemes,
                    feuille=detail.nom,
                    numero_ligne=numero_ligne,
                    champ="Catégorie",
                    valeur=categorie_brute,
                    message="une cotisation d'un exercice antérieur doit être ARRIERE_COTISATION",
                    code="CATEGORIE_INCOHERENTE",
                )
                continue
            cible.creances.append(
                CreanceAnalysee(
                    categorie=categorie_ligne,
                    exercice=exercice_ligne,
                    libelle=libelle or f"{libelle_categorie(categorie_ligne)} {exercice_ligne}",
                    montant=montant_ligne,
                    devise=devise_ligne,
                    reference_decision=_texte_optionnel(
                        _cellule(detail, valeurs, "reference_decision"), 255
                    ),
                    observation=_texte_optionnel(_cellule(detail, valeurs, "observation")),
                    feuille=detail.nom,
                    ligne=numero_ligne,
                )
            )

    # Les colonnes de l'en-tête sont soit des lignes courantes, soit des totaux
    # de contrôle remplacés par la ventilation détaillée.
    for ligne in lignes:
        if ligne.exercice is None:
            continue
        for categorie_ligne, montant_resume in ligne.resume_montants.items():
            details_categorie = [c for c in ligne.creances if c.categorie == categorie_ligne]
            if categorie_ligne in CATEGORIES_ARRIERE:
                total_detail = sum((c.montant for c in details_categorie), Decimal("0.00"))
                if montant_resume > 0 and not details_categorie:
                    _signaler(
                        ligne,
                        problemes,
                        feuille=principale.nom,
                        numero_ligne=ligne.ligne,
                        champ=libelle_categorie(categorie_ligne),
                        valeur=montant_resume,
                        message="arriéré non ventilé dans la feuille « Détail créances »",
                        code="ARRIERE_NON_VENTILE",
                    )
                elif montant_resume != total_detail:
                    _signaler(
                        ligne,
                        problemes,
                        feuille=principale.nom,
                        numero_ligne=ligne.ligne,
                        champ=libelle_categorie(categorie_ligne),
                        valeur=montant_resume,
                        message=f"le total détaillé vaut {_montant_texte(total_detail)} {ligne.devise}",
                        code="MONTANT_INCOHERENT",
                    )
                continue

            details_exercice = [
                c for c in details_categorie if c.exercice == ligne.exercice
            ]
            if details_exercice:
                total_detail = sum((c.montant for c in details_exercice), Decimal("0.00"))
                if montant_resume != total_detail:
                    _signaler(
                        ligne,
                        problemes,
                        feuille=principale.nom,
                        numero_ligne=ligne.ligne,
                        champ=libelle_categorie(categorie_ligne),
                        valeur=montant_resume,
                        message=f"le total détaillé de l'exercice vaut {_montant_texte(total_detail)} {ligne.devise}",
                        code="MONTANT_INCOHERENT",
                    )
                continue
            if montant_resume <= 0:
                continue
            if categorie_ligne == AUTRE_PENALITE and not ligne.observation:
                _signaler(
                    ligne,
                    problemes,
                    feuille=principale.nom,
                    numero_ligne=ligne.ligne,
                    champ="Observation",
                    valeur=None,
                    message="un motif est obligatoire lorsque « Autre pénalité » est renseignée",
                    code="LIBELLE_REQUIS",
                )
                continue
            ligne.creances.append(
                CreanceAnalysee(
                    categorie=categorie_ligne,
                    exercice=ligne.exercice,
                    libelle=_libelle_ligne_principale(categorie_ligne, ligne.exercice, ligne.observation),
                    montant=montant_resume,
                    devise=ligne.devise,
                    reference_decision=ligne.reference_decision,
                    observation=ligne.observation,
                    feuille=principale.nom,
                    ligne=ligne.ligne,
                )
            )

        if not ligne.creances and not ligne.erreurs:
            _signaler(
                ligne,
                problemes,
                feuille=principale.nom,
                numero_ligne=ligne.ligne,
                champ="Montants",
                valeur=None,
                message="aucune créance à importer",
                code="MONTANT_INVALIDE",
            )
        total_calcule = sum((c.montant for c in ligne.creances), Decimal("0.00"))
        if ligne.total_attendu is not None and ligne.total_attendu != total_calcule:
            _signaler(
                ligne,
                problemes,
                feuille=principale.nom,
                numero_ligne=ligne.ligne,
                champ="Total note",
                valeur=ligne.total_attendu,
                message=f"la somme des lignes vaut {_montant_texte(total_calcule)} {ligne.devise}",
                code="TOTAL_INCOHERENT",
            )

        # Contrat historique avec l'écran : `montants` contient les agrégats par
        # colonne virtuelle, tandis que `creances` garde chaque exercice.
        par_categorie: dict[str, Decimal] = {}
        for creance in ligne.creances:
            par_categorie[creance.categorie] = par_categorie.get(creance.categorie, Decimal("0")) + creance.montant
        ligne.montants = {
            INDEX_CATEGORIES[categorie_ligne]: montant
            for categorie_ligne, montant in par_categorie.items()
        }

    # Numéros externes déjà présents dans ce conseil.
    externes = {ligne.numero_note_externe.casefold() for ligne in lignes if ligne.numero_note_externe}
    if externes:
        existants = (
            await db.execute(
                select(Encaissement.numero_note_externe, Encaissement.numero_recu).where(
                    Encaissement.organisation_id == tenant_id,
                    Encaissement.numero_note_externe.is_not(None),
                    func.lower(Encaissement.numero_note_externe).in_(externes),
                )
            )
        ).all()
        par_numero_existant = {(numero or "").casefold(): interne for numero, interne in existants}
        for ligne in lignes:
            interne = par_numero_existant.get((ligne.numero_note_externe or "").casefold())
            if interne:
                ligne.doublon = True
                _signaler(
                    ligne,
                    problemes,
                    feuille=principale.nom,
                    numero_ligne=ligne.ligne,
                    champ="N° note externe",
                    valeur=ligne.numero_note_externe,
                    message=f"ce numéro existe déjà (référence ONEC Smart {interne})",
                    code="NUMERO_EXTERNE_EXISTANT",
                )

    # Une cotisation annuelle ne peut pas être appelée deux fois au même membre
    # et au même exercice. Les pénalités restent répétables : deux décisions
    # distinctes peuvent légitimement porter la même catégorie.
    experts_ids = {ligne.expert.id for ligne in lignes if ligne.expert is not None}
    cotisations_existantes: dict[tuple[uuid.UUID, int], str] = {}
    if experts_ids:
        donnees = (
            await db.execute(
                select(
                    Encaissement.expert_comptable_id,
                    EncaissementArticle.exercice,
                    Encaissement.numero_recu,
                )
                .join(EncaissementArticle, EncaissementArticle.encaissement_id == Encaissement.id)
                .where(
                    Encaissement.organisation_id == tenant_id,
                    Encaissement.expert_comptable_id.in_(experts_ids),
                    Encaissement.is_deleted.is_(False),
                    Encaissement.est_proforma.is_(False),
                    Encaissement.statut_operation != "ANNULEE",
                    EncaissementArticle.categorie == COTISATION_ANNUELLE,
                )
            )
        ).all()
        cotisations_existantes = {
            (expert_id, exercice): numero or "—"
            for expert_id, exercice, numero in donnees
            if expert_id is not None and exercice is not None
        }
    cotisations_fichier: dict[tuple[uuid.UUID, int], LigneAnalysee] = {}
    for ligne in lignes:
        if ligne.expert is None:
            continue
        for creance in ligne.creances:
            if creance.categorie != COTISATION_ANNUELLE:
                continue
            cle = (ligne.expert.id, creance.exercice)
            if cle in cotisations_existantes:
                ligne.doublon = True
                _signaler(
                    ligne,
                    problemes,
                    feuille=principale.nom,
                    numero_ligne=ligne.ligne,
                    champ="Cotisation N",
                    valeur=creance.exercice,
                    message=f"cotisation déjà émise sur la note {cotisations_existantes[cle]}",
                    code="DOUBLON_COTISATION",
                )
            elif cle in cotisations_fichier:
                autre = cotisations_fichier[cle]
                for concernee in (autre, ligne):
                    concernee.doublon = True
                    if not any(p.code == "DOUBLON_COTISATION" for p in concernee.problemes):
                        _signaler(
                            concernee,
                            problemes,
                            feuille=principale.nom,
                            numero_ligne=concernee.ligne,
                            champ="Cotisation N",
                            valeur=creance.exercice,
                            message="cotisation dupliquée dans le fichier pour ce membre et cet exercice",
                            code="DOUBLON_COTISATION",
                        )
            else:
                cotisations_fichier[cle] = ligne

    # Colonnes virtuelles et suggestions de postes, compatibles avec le même
    # écran de confirmation que l'import historique.
    codes_arrieres = await _codes_arrieres(db, tenant_id, exercice_budget) if exercice_budget else set()
    postes_arrieres = [p for p in postes if (p.code or "").strip().upper() in codes_arrieres]
    aujourdhui = datetime.now().date()
    tarifs_par_libelle = {
        tarif.libelle_normalise: (tarif, poste)
        for tarif, poste in await tarifs_resolus(db, tenant_id, actifs_seulement=True, a_la_date=aujourdhui)
    }
    tarifs: dict[int, tuple[Any, BudgetPoste | None]] = {}
    colonnes: list[dict[str, Any]] = []
    presentes = {
        creance.categorie
        for ligne in lignes
        for creance in ligne.creances
    } | {
        categorie_ligne
        for ligne in lignes
        for categorie_ligne, montant in ligne.resume_montants.items()
        if montant > 0
    }
    for categorie_ligne in ORDRE_CATEGORIES:
        if categorie_ligne not in presentes:
            continue
        index = INDEX_CATEGORIES[categorie_ligne]
        libelle = LIBELLES_CATEGORIES[categorie_ligne]
        trouve = tarifs_par_libelle.get(normaliser_libelle(libelle))
        tarif, poste_tarif = trouve if trouve is not None else (None, None)
        if tarif is not None:
            tarifs[index] = (tarif, poste_tarif)
        suggere = poste_tarif
        if suggere is None and categorie_ligne in CATEGORIES_ARRIERE:
            suggere = postes_arrieres[0] if len(postes_arrieres) == 1 else next(
                (p for p in postes if "arri" in normaliser_entete(p.libelle)), None
            )
        if suggere is None:
            mot = "cotis" if categorie_ligne in {COTISATION_ANNUELLE, ARRIERE_COTISATION} else (
                "penal" if "PENALITE" in categorie_ligne else "creance"
            )
            suggere = next((p for p in postes if mot in normaliser_entete(p.libelle)), None)
        total_categorie = sum(
            (c.montant for ligne in lignes for c in ligne.creances if c.categorie == categorie_ligne),
            Decimal("0.00"),
        )
        colonnes.append(
            {
                "avertissement": None,
                "cle": str(index),
                "categorie": categorie_ligne,
                "libelle": libelle,
                "arrieres": categorie_ligne in CATEGORIES_ARRIERE,
                "tarif": (
                    {
                        "id": tarif.id,
                        "libelle": tarif.libelle,
                        "montant": str(tarif.montant) if tarif.montant is not None else None,
                        "poste_code": tarif.budget_poste_code,
                    }
                    if tarif is not None
                    else None
                ),
                "poste_impose": poste_tarif is not None,
                "poste_suggere_id": suggere.id if suggere is not None else None,
                "erreur": None,
                "total": str(total_categorie),
                "nb_lignes": sum(
                    1
                    for ligne in lignes
                    if any(c.categorie == categorie_ligne for c in ligne.creances)
                ),
            }
        )

    feuille_compat = Feuille(
        ligne_entete=principale.ligne_entete,
        col_numero=principale.colonnes.get("numero_ordre"),
        col_nom=principale.colonnes.get("nom"),
        col_total=principale.colonnes.get("total"),
        colonnes=[],
        ignorees=[],
        lignes=principale.lignes,
    )
    return Analyse(
        feuille=feuille_compat,
        exercice=exercice_budget,
        annee=exercice_budget.annee if exercice_budget else datetime.now().year,
        lignes=lignes,
        colonnes=colonnes,
        postes=postes,
        services=services,
        service_id=service_retenu,
        tarifs=tarifs,
        categorie=categorie_import,
        format_import="structure",
        problemes=problemes,
    )


async def analyser(
    db: AsyncSession,
    *,
    tenant_id: int,
    user: Any,
    contenu: bytes,
    service_id: int | None,
    categorie: str = "toutes",
) -> Analyse:
    if categorie not in CATEGORIES:
        raise HTTPException(status_code=400, detail="Catégorie d'import inconnue")
    classeur_structure = lire_classeur_structure(contenu)
    if classeur_structure is not None:
        return await _analyser_structure(
            db,
            tenant_id=tenant_id,
            user=user,
            classeur=classeur_structure,
            service_id=service_id,
            categorie_import=categorie,
        )
    feuille = lire_feuille(contenu)
    services = await services_disponibles(db, user, tenant_id)
    # L'aperçu ne bloque pas sur le service : un agent de plusieurs services le
    # choisira à l'écran, et c'est l'import qui l'exigera (`resoudre_service`).
    if service_id is not None:
        service_retenu = await resoudre_service(db, user, tenant_id, service_id)
    elif (getattr(user, "role", "") or "").lower() not in {"admin", "super_admin"} and len(services) == 1:
        service_retenu = services[0].id
    else:
        service_retenu = None
    exercice, postes = await postes_disponibles(db, tenant_id, service_retenu)
    annee = exercice.annee if exercice is not None else datetime.now().year
    postes_par_code = {(p.code or "").strip().upper(): p for p in postes}

    aujourdhui = datetime.now().date()
    par_libelle = {
        tarif.libelle_normalise: (tarif, poste)
        for tarif, poste in await tarifs_resolus(db, tenant_id, actifs_seulement=True, a_la_date=aujourdhui)
    }
    codes_arrieres = await _codes_arrieres(db, tenant_id, exercice) if exercice is not None else set()
    postes_arrieres = [p for code, p in postes_par_code.items() if code in codes_arrieres]

    tarifs: dict[int, tuple[Any, BudgetPoste | None]] = {}
    colonnes: list[dict[str, Any]] = []
    for colonne in feuille.colonnes:
        cle = normaliser_libelle(colonne.libelle)
        erreur = None
        trouve = par_libelle.get(cle)
        if trouve is not None:
            tarifs[colonne.index] = trouve
        else:
            remplacant = await succession(db, tenant_id, cle)
            if remplacant is not None:
                erreur = (
                    f"« {colonne.libelle} » est devenu « {remplacant.libelle} » : "
                    f"renommez la colonne du fichier."
                )
        tarif, poste_tarif = trouve if trouve is not None else (None, None)
        suggere = poste_tarif
        if suggere is None and colonne.arrieres:
            if len(postes_arrieres) == 1:
                suggere = postes_arrieres[0]
            else:
                suggere = next((p for p in postes if "arri" in normaliser_entete(p.libelle)), None)
        if categorie == "penalites" and not colonne.arrieres and "penalit" not in normaliser_entete(colonne.libelle):
            avertissement = f"« {colonne.libelle} » ne ressemble pas à une pénalité : vérifiez l'onglet choisi."
        else:
            avertissement = None
        colonnes.append(
            {
                "avertissement": avertissement,
                "cle": str(colonne.index),
                "libelle": colonne.libelle,
                "arrieres": colonne.arrieres,
                "tarif": (
                    {
                        "id": tarif.id,
                        "libelle": tarif.libelle,
                        "montant": str(tarif.montant) if tarif.montant is not None else None,
                        "poste_code": tarif.budget_poste_code,
                    }
                    if tarif is not None
                    else None
                ),
                # Un tarif qui fixe le poste l'impose : le choisir ailleurs serait
                # un forçage, que l'import n'a pas à faire en silence.
                "poste_impose": poste_tarif is not None,
                "poste_suggere_id": suggere.id if suggere is not None else None,
                "erreur": erreur,
                "total": "0.00",
                "nb_lignes": 0,
            }
        )

    par_numero, par_nom = await _experts(db)
    lignes: list[LigneAnalysee] = []
    numeros_vus: dict[str, int] = {}
    for numero_ligne, valeurs in feuille.lignes:
        def cellule(index: int | None) -> Any:
            return valeurs[index] if index is not None and index < len(valeurs) else None

        brut_numero = cellule(feuille.col_numero)
        numero = "" if brut_numero is None else str(int(brut_numero) if isinstance(brut_numero, float) and brut_numero.is_integer() else brut_numero).strip()
        nom = libelle_colonne(cellule(feuille.col_nom))
        ligne = LigneAnalysee(ligne=numero_ligne, numero_ordre=numero, nom=nom)

        cle = cle_numero_ordre(numero)
        if cle:
            ligne.expert = par_numero.get(cle)
            if ligne.expert is None:
                ligne.erreurs.append(f"N° d'ordre « {numero} » introuvable dans la liste des experts")
            elif cle in numeros_vus:
                ligne.erreurs.append(f"Membre déjà présent à la ligne {numeros_vus[cle]} du fichier")
            else:
                numeros_vus[cle] = numero_ligne
        elif nom:
            candidats = par_nom.get(cle_nom(nom), [])
            if len(candidats) == 1:
                ligne.expert = candidats[0]
                ligne.avertissements.append("Rapproché par le nom, faute de n° d'ordre")
            elif candidats:
                ligne.erreurs.append(f"Plusieurs experts s'appellent « {nom} » : indiquez le n° d'ordre")
            else:
                ligne.erreurs.append(f"« {nom} » introuvable dans la liste des experts")
        else:
            ligne.erreurs.append("Ni n° d'ordre ni nom")

        for colonne in feuille.colonnes:
            try:
                montant = lire_montant(cellule(colonne.index))
            except ValueError:
                ligne.erreurs.append(f"« {colonne.libelle} » : « {cellule(colonne.index)} » n'est pas un montant")
                continue
            if montant is None or montant == 0:
                continue
            if montant < 0:
                ligne.erreurs.append(f"« {colonne.libelle} » : montant négatif")
                continue
            ligne.montants[colonne.index] = montant
            tarif = tarifs.get(colonne.index, (None, None))[0]
            if tarif is not None and tarif.montant is not None:
                prix = Decimal(str(tarif.montant))
                if (montant % prix) != 0:
                    ligne.avertissements.append(
                        f"« {colonne.libelle} » : {_montant_texte(montant)} au lieu du tarif "
                        f"{_montant_texte(prix)} — le montant du fichier est retenu"
                    )

        if not ligne.montants and not ligne.erreurs:
            ligne.erreurs.append("Aucun montant sur la ligne")

        if feuille.col_total is not None and ligne.montants:
            try:
                total_fichier = lire_montant(cellule(feuille.col_total))
            except ValueError:
                total_fichier = None
            if total_fichier is not None and total_fichier != ligne.total:
                ligne.avertissements.append(
                    f"Total du fichier {_montant_texte(total_fichier)} ≠ somme des colonnes "
                    f"{_montant_texte(ligne.total)} — la somme est retenue"
                )

        if ligne.expert is not None and categorie in {"ec", "sec"}:
            est_sec = ligne.expert.type_ec == "SEC"
            if categorie == "ec" and est_sec:
                ligne.erreurs.append(
                    f"{ligne.expert.nom_denomination} est une SEC : importez-la dans l'onglet « Cotisations SEC »"
                )
            elif categorie == "sec" and not est_sec:
                ligne.erreurs.append(
                    f"{ligne.expert.nom_denomination} n'est pas une SEC : importez-le dans l'onglet « Cotisations EC »"
                )

        if ligne.expert is not None and not ligne.expert.active:
            ligne.avertissements.append("Expert inactif dans la liste")
        lignes.append(ligne)

    deja = await _deja_emises(db, tenant_id, {l.expert.id for l in lignes if l.expert is not None}, annee)
    libelles = {c.index: c.libelle for c in feuille.colonnes}
    for ligne in lignes:
        if ligne.expert is None or ligne.erreurs:
            continue
        for index in ligne.montants:
            numero = deja.get((ligne.expert.id, normaliser_libelle(libelles[index])))
            if numero:
                ligne.doublon = True
                ligne.avertissements.append(f"« {libelles[index]} » déjà émis en {annee} (note {numero})")

    par_cle = {c["cle"]: c for c in colonnes}
    for ligne in lignes:
        if ligne.erreurs:
            continue
        for index, montant in ligne.montants.items():
            info = par_cle[str(index)]
            info["total"] = str(Decimal(info["total"]) + montant)
            info["nb_lignes"] += 1

    return Analyse(
        feuille=feuille,
        exercice=exercice,
        annee=annee,
        lignes=lignes,
        colonnes=colonnes,
        postes=postes,
        services=services,
        service_id=service_retenu,
        tarifs=tarifs,
        categorie=categorie,
    )


def analyse_en_reponse(analyse: Analyse) -> dict[str, Any]:
    valides = [l for l in analyse.lignes if not l.erreurs]
    arrieres = {c.index for c in analyse.feuille.colonnes if c.arrieres}
    if analyse.format_import == "structure":
        total_arrieres = sum(
            (
                creance.montant
                for ligne in valides
                for creance in ligne.creances
                if creance.categorie in CATEGORIES_ARRIERE
            ),
            Decimal("0.00"),
        )
    else:
        total_arrieres = sum(
            (m for l in valides for i, m in l.montants.items() if i in arrieres), Decimal("0.00")
        )
    problemes = analyse.problemes
    return {
        "format_import": analyse.format_import,
        "categorie": analyse.categorie,
        "ligne_entete": analyse.feuille.ligne_entete,
        "exercice": analyse.annee,
        "exercice_ouvert": analyse.exercice is not None,
        "service_id": analyse.service_id,
        "services": [{"id": s.id, "code": s.code, "libelle": s.libelle} for s in analyse.services],
        "postes": [{"id": p.id, "code": p.code, "libelle": p.libelle} for p in analyse.postes],
        "colonnes": analyse.colonnes,
        "colonnes_ignorees": analyse.feuille.ignorees,
        "colonne_numero": analyse.feuille.col_numero is not None,
        "problemes": [probleme.dict() for probleme in problemes],
        "lignes": [
            {
                "ligne": l.ligne,
                "numero_ordre": l.numero_ordre,
                "nom": l.nom,
                "numero_note_externe": l.numero_note_externe,
                "date_note": l.date_note.isoformat() if l.date_note else None,
                "exercice": l.exercice,
                "devise": l.devise,
                "date_echeance": l.date_echeance.isoformat() if l.date_echeance else None,
                "reference_decision": l.reference_decision,
                "observation": l.observation,
                "expert": (
                    {
                        "id": str(l.expert.id),
                        "numero_ordre": l.expert.numero_ordre,
                        "nom": l.expert.nom_denomination,
                        "type_ec": l.expert.type_ec,
                    }
                    if l.expert is not None
                    else None
                ),
                "montants": {str(k): str(v) for k, v in l.montants.items()},
                "total": str(l.total),
                "statut": l.statut,
                "doublon": l.doublon,
                "erreurs": l.erreurs,
                "avertissements": l.avertissements,
                "problemes": [probleme.dict() for probleme in l.problemes],
                "creances": [
                    {
                        "categorie": creance.categorie,
                        "exercice": creance.exercice,
                        "libelle": creance.libelle,
                        "montant": str(creance.montant),
                        "devise": creance.devise,
                        "reference_decision": creance.reference_decision,
                        "observation": creance.observation,
                        "feuille": creance.feuille,
                        "ligne": creance.ligne,
                    }
                    for creance in l.creances
                ],
            }
            for l in analyse.lignes
        ],
        "resume": {
            "nb_lignes": len(analyse.lignes),
            "nb_ok": sum(1 for l in analyse.lignes if l.statut == "ok"),
            "nb_avertissements": sum(1 for l in analyse.lignes if l.statut == "avertissement"),
            "nb_erreurs": sum(1 for l in analyse.lignes if l.statut == "erreur"),
            "nb_doublons": sum(1 for l in analyse.lignes if l.doublon),
            "total": str(sum((l.total for l in valides), Decimal("0.00"))),
            "total_arrieres": str(total_arrieres),
            "membres_introuvables": sum(1 for p in problemes if p.code == "MEMBRE_INTROUVABLE"),
            "numeros_existants": sum(1 for p in problemes if p.code == "NUMERO_EXTERNE_EXISTANT"),
            "montants_incoherents": sum(
                1 for p in problemes if p.code in {"MONTANT_INCOHERENT", "TOTAL_INCOHERENT"}
            ),
            "arrieres_non_ventiles": sum(1 for p in problemes if p.code == "ARRIERE_NON_VENTILE"),
        },
    }


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


async def importer(
    db: AsyncSession,
    *,
    tenant_id: int,
    user: Any,
    fichier: str,
    contenu: bytes,
    service_id: int | None,
    postes: dict[str, int],
    importer_doublons: bool = False,
    categorie: str = "toutes",
) -> dict[str, Any]:
    """Crée les notes du fichier, toutes ou aucune."""
    # Importé ici : l'endpoint des encaissements importe déjà ce module-ci par
    # le routeur, et ces deux fonctions sont celles de la saisie — les recopier
    # serait laisser l'import diverger du formulaire au premier correctif.
    from app.api.v1.endpoints.encaissements import _add_encaissement_articles, _valider_postes_articles
    from app.core.horodatage import resoudre_date_operation

    user_id = getattr(user, "id", None)
    analyse = await analyser(
        db, tenant_id=tenant_id, user=user, contenu=contenu, service_id=service_id, categorie=categorie
    )
    service_retenu = await resoudre_service(db, user, tenant_id, service_id)
    if analyse.exercice is None:
        raise HTTPException(status_code=400, detail="Aucun exercice budgétaire : ouvrez l'exercice avant d'importer.")

    erreurs_colonnes = [c["erreur"] for c in analyse.colonnes if c["erreur"]]
    if erreurs_colonnes:
        raise HTTPException(status_code=400, detail=" ".join(erreurs_colonnes))
    if analyse.format_import == "structure" and any(
        probleme.niveau == "ERREUR" and probleme.code == "RATTACHEMENT_INTROUVABLE"
        for probleme in analyse.problemes
    ):
        raise HTTPException(
            status_code=400,
            detail="La feuille « Détail créances » contient des lignes qui ne peuvent être rattachées à aucune note.",
        )

    postes_valides = {p.id for p in analyse.postes}
    poste_par_colonne: dict[int, int] = {}
    manquants: list[str] = []
    for info in analyse.colonnes:
        index = int(info["cle"])
        if not info["nb_lignes"]:
            continue
        choisi = postes.get(info["cle"]) or info["poste_suggere_id"]
        if info["poste_impose"]:
            choisi = info["poste_suggere_id"]
        if choisi is None:
            manquants.append(info["libelle"])
            continue
        if int(choisi) not in postes_valides:
            raise HTTPException(
                status_code=400,
                detail=f"« {info['libelle']} » : poste non autorisé pour ce service ou hors de l'exercice {analyse.annee}.",
            )
        poste_par_colonne[index] = int(choisi)
    if manquants:
        raise HTTPException(
            status_code=400,
            detail="Choisissez le poste budgétaire de : " + ", ".join(f"« {m} »" for m in manquants),
        )

    a_creer = [l for l in analyse.lignes if not l.erreurs and (importer_doublons or not l.doublon)]
    if not a_creer:
        raise HTTPException(status_code=400, detail="Aucune note à créer : toutes les lignes sont en erreur ou déjà émises.")

    if analyse.format_import == "structure":
        # Sérialise deux imports concurrents visant le même membre. Après le
        # verrou, on recontrôle la cotisation : la prévisualisation n'est pas
        # une garantie si un autre utilisateur confirme en même temps.
        experts_ids = sorted({ligne.expert.id for ligne in a_creer if ligne.expert is not None}, key=str)
        if experts_ids:
            await db.execute(
                select(ExpertComptable.id)
                .where(ExpertComptable.id.in_(experts_ids))
                .order_by(ExpertComptable.id)
                .with_for_update()
            )
        cles_cotisations = {
            (ligne.expert.id, creance.exercice)
            for ligne in a_creer
            if ligne.expert is not None
            for creance in ligne.creances
            if creance.categorie == COTISATION_ANNUELLE
        }
        if cles_cotisations:
            deja = (
                await db.execute(
                    select(
                        Encaissement.expert_comptable_id,
                        EncaissementArticle.exercice,
                        Encaissement.numero_recu,
                    )
                    .join(EncaissementArticle, EncaissementArticle.encaissement_id == Encaissement.id)
                    .where(
                        Encaissement.organisation_id == tenant_id,
                        Encaissement.expert_comptable_id.in_({cle[0] for cle in cles_cotisations}),
                        Encaissement.is_deleted.is_(False),
                        Encaissement.est_proforma.is_(False),
                        Encaissement.statut_operation != "ANNULEE",
                        EncaissementArticle.categorie == COTISATION_ANNUELLE,
                    )
                )
            ).all()
            conflit = next(
                (
                    numero
                    for expert_id, exercice_ligne, numero in deja
                    if (expert_id, exercice_ligne) in cles_cotisations
                ),
                None,
            )
            if conflit:
                raise HTTPException(
                    status_code=409,
                    detail=f"Une cotisation a été émise depuis la prévisualisation (note {conflit}). Relancez l'analyse.",
                )

    await _valider_postes_articles(
        db,
        tenant_id=tenant_id,
        service_id=service_retenu,
        articles=[{"budget_poste_id": pid} for pid in set(poste_par_colonne.values())],
        impact_budgetaire=True,
    )
    postes_par_id = {p.id: p for p in analyse.postes}
    libelles = (
        {int(info["cle"]): info["libelle"] for info in analyse.colonnes}
        if analyse.format_import == "structure"
        else {c.index: c.libelle for c in analyse.feuille.colonnes}
    )
    categories_par_index = {
        int(info["cle"]): info.get("categorie")
        for info in analyse.colonnes
    }
    arrieres = (
        {int(info["cle"]) for info in analyse.colonnes if info["arrieres"]}
        if analyse.format_import == "structure"
        else {c.index for c in analyse.feuille.colonnes if c.arrieres}
    )
    date_note = resoudre_date_operation(None, user=user, champ="date_encaissement")

    total = Decimal("0.00")
    total_arrieres = Decimal("0.00")
    enregistrement = NoteDebitImport(
        organisation_id=tenant_id,
        fichier=(fichier or "notes_de_debit.xlsx")[:300],
        service_id=service_retenu,
        created_by=user_id,
        colonnes=[
            {
                "libelle": libelles[index],
                "categorie": categories_par_index.get(index),
                "arrieres": index in arrieres,
                "poste_id": poste_id,
                "poste_code": postes_par_id[poste_id].code,
            }
            for index, poste_id in poste_par_colonne.items()
        ],
    )
    db.add(enregistrement)
    await db.flush()

    notes: list[dict[str, Any]] = []
    for ligne in a_creer:
        expert = ligne.expert
        assert expert is not None
        articles: list[dict[str, Any]] = []
        sources_articles = (
            [
                (INDEX_CATEGORIES[creance.categorie], creance.montant, creance)
                for creance in ligne.creances
            ]
            if analyse.format_import == "structure"
            else [(index, montant, None) for index, montant in ligne.montants.items()]
        )
        for ordre, (index, montant, creance) in enumerate(sources_articles):
            quantite, prix = Decimal("1.00"), montant
            tarif = analyse.tarifs.get(index, (None, None))[0]
            # Trois pénalités à 100, c'est 3 × 100 et non une ligne de 300 qui
            # s'écarterait du tarif : la quantité se déduit quand elle tombe juste.
            if tarif is not None and tarif.montant is not None:
                tarife = Decimal(str(tarif.montant))
                if tarife > 0 and montant % tarife == 0:
                    quantite, prix = (montant / tarife).quantize(CENT), tarife
            articles.append(
                {
                    "libelle": creance.libelle if creance is not None else libelles[index],
                    "description": creance.observation if creance is not None else None,
                    "quantite": quantite,
                    "prix_unitaire": prix,
                    "montant": montant,
                    "budget_poste_id": poste_par_colonne[index],
                    "categorie": (
                        creance.categorie if creance is not None else _categorie_legacy(libelles[index])
                    ),
                    "exercice": (
                        creance.exercice
                        if creance is not None
                        else _exercice_legacy(libelles[index], analyse.annee)
                    ),
                    "reference_decision": creance.reference_decision if creance is not None else None,
                    "sort_order": ordre,
                }
            )
        date_note_ligne = date_note
        if (
            analyse.format_import == "structure"
            and ligne.date_note is not None
            and ligne.date_note != date_note.date()
        ):
            date_note_ligne = resoudre_date_operation(
                datetime.combine(ligne.date_note, time.min, tzinfo=timezone.utc), user=user, champ="Date note"
            )
        ecarts = await appliquer_tarifs(
            db, tenant_id, articles, peut_forcer=True, date_encaissement=date_note_ligne.date()
        )
        montant_note = ligne.total
        poste_entete = postes_par_id[articles[0]["budget_poste_id"]]
        note = Encaissement(
            numero_recu=await generate_document_number(db, doc_type="ND", tenant_id=tenant_id, service_id=None),
            numero_note_externe=ligne.numero_note_externe,
            numero_proforma=None,
            est_proforma=False,
            organisation_id=tenant_id,
            type_client="sec" if expert.type_ec == "SEC" else "expert_comptable",
            expert_comptable_id=expert.id,
            client_nom=None,
            client_id=None,
            libelle=", ".join(a["libelle"] for a in articles)[:255],
            description=(
                ligne.observation
                if analyse.format_import == "structure"
                else f"Import « {enregistrement.fichier} », ligne {ligne.ligne}"
            ),
            exercice=ligne.exercice if analyse.format_import == "structure" else analyse.annee,
            date_echeance=ligne.date_echeance,
            reference_decision=ligne.reference_decision,
            montant=montant_note,
            montant_total=montant_note,
            montant_paye=Decimal("0.00"),
            montant_percu=Decimal("0.00"),
            devise_perception="USD",
            taux_change_applique=Decimal("1.00"),
            budget_poste_id=poste_entete.id,
            budget_poste_code=poste_entete.code,
            budget_poste_libelle=poste_entete.libelle,
            service_id=service_retenu,
            statut_paiement="non_paye",
            mode_paiement="cash",
            nature_mouvement="BUDGETAIRE",
            impact_budgetaire=True,
            hors_budget_status=hors_budget_initial_status("BUDGETAIRE"),
            canal="CAISSE",
            date_encaissement=date_note_ligne,
            date_paiement=None,
            created_by=user_id,
            note_debit_import_id=enregistrement.id,
        )
        db.add(note)
        try:
            await db.flush()
        except IntegrityError as exc:
            await db.rollback()
            contrainte = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            if contrainte == "uq_enc_org_num_note_externe":
                raise HTTPException(
                    status_code=409,
                    detail=f"Le numéro externe « {ligne.numero_note_externe} » vient d'être importé. Relancez l'analyse.",
                ) from exc
            raise
        _add_encaissement_articles(db, note, tenant_id, articles)
        if ecarts:
            await log_action(
                db,
                user_id=user_id,
                action="ENCAISSEMENT_TARIF_FORCE",
                target_table="encaissements",
                target_id=str(note.id),
                new_value={"ecarts": ecarts, "import": str(enregistrement.id)},
            )
        total += montant_note
        total_arrieres += (
            sum(
                (creance.montant for creance in ligne.creances if creance.categorie in CATEGORIES_ARRIERE),
                Decimal("0.00"),
            )
            if analyse.format_import == "structure"
            else sum((m for i, m in ligne.montants.items() if i in arrieres), Decimal("0.00"))
        )
        notes.append(
            {
                "id": str(note.id),
                "numero_recu": note.numero_recu,
                "numero_note_externe": note.numero_note_externe,
                "numero_ordre": expert.numero_ordre,
                "nom": expert.nom_denomination,
                "montant_total": str(montant_note),
            }
        )

    enregistrement.nb_notes = len(notes)
    enregistrement.nb_lignes_ecartees = len(analyse.lignes) - len(notes)
    enregistrement.montant_total = total
    enregistrement.montant_arrieres = total_arrieres
    await log_action(
        db,
        user_id=user_id,
        action="NOTES_DEBIT_IMPORT",
        target_table="notes_debit_imports",
        target_id=str(enregistrement.id),
        new_value={
            "categorie": categorie,
            "fichier": enregistrement.fichier,
            "nb_notes": len(notes),
            "montant_total": str(total),
            "montant_arrieres": str(total_arrieres),
        },
    )
    await db.commit()
    return {
        "categorie": categorie,
        "import_id": str(enregistrement.id),
        "fichier": enregistrement.fichier,
        "nb_notes": len(notes),
        "nb_lignes_ecartees": enregistrement.nb_lignes_ecartees,
        "montant_total": str(total),
        "montant_arrieres": str(total_arrieres),
        "notes": notes,
    }
