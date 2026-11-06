"""Moteur de verdict Tableau — En règle / Non en règle / À délibérer.

Les valeurs enregistrées restent INSCRIT / NON INSCRIT / À DÉLIBÉRER (historique,
décisions de commission) ; `libelle_conclusion` donne le libellé affiché.

Pour être en règle (barème `BAREME`, réglable par catégorie et par critère),
il faut remplir les colonnes de situation affichées pour la catégorie :
- Société        : cotisation, chiffre d'affaires déclaré, assurance valide
- EC Indépendant : cotisation, formation (NHV), assurance, chiffre d'affaires
- EC Cabinet     : cotisation, formation
- EC Salarié     : cotisation, formation (NHV)
- Stagiaire      : cotisation
Une cotisation partiellement réglée renvoie au conseil (À délibérer), comme
toute donnée manquante.

Exemptions de la formation continue :
- Nouveau membre : inscrit depuis moins de N ans (année du N° d'ordre >=
  exercice - (N-1)) ou ancienneté « Nouveau » -> formation NON REQUISE.
- Âge supérieur au seuil réglable -> action configurable (par défaut
  « À DÉLIBÉRER », ou validation directe en INSCRIT selon les réglages).

TOUS les paramètres (seuil d'heures, seuil d'âge, action liée à l'âge, durée
« nouveau membre ») sont réglables via `TableauReglages` — configurables dans
l'application, sans valeur figée dans le code.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ---- Valeurs par défaut (surchargées par les réglages de l'organisation) ----
DEFAULT_HEURES_FORMATION_MIN = 120.0
DEFAULT_AGE_SEUIL = 60
DEFAULT_AGE_ACTION = "a_deliberer"   # "a_deliberer" | "inscrit" | "aucune"
DEFAULT_NOUVEAU_ANS = 3

# Rétro-compatibilité (constantes lues ailleurs)
HEURES_FORMATION_MIN = DEFAULT_HEURES_FORMATION_MIN
AGE_EXEMPTION = DEFAULT_AGE_SEUIL

# Valeurs enregistrées (inchangées pour l'historique) ; l'interface et les
# exports les affichent par `libelle_conclusion`.
INSCRIT = "INSCRIT"
NON_INSCRIT = "NON INSCRIT"
A_DELIBERER = "À DÉLIBÉRER"

LIBELLES_CONCLUSION = {
    INSCRIT: "En règle",
    NON_INSCRIT: "Non en règle",
    A_DELIBERER: "À délibérer",
}


def libelle_conclusion(conclusion: str | None) -> str | None:
    """« INSCRIT » → « En règle » : ce que lit l'utilisateur."""
    if conclusion is None:
        return None
    return LIBELLES_CONCLUSION.get(str(conclusion).strip().upper(), conclusion)
INCOMPLET = "INCOMPLET"
NON_APPLICABLE = "N/A"

# Critères requis par catégorie. La formation est traitée à part (exemptions).
CATEGORIE_CRITERES: dict[str, list[str]] = {
    "Société": ["cotisation", "assurance", "chiffre_affaires"],
    "SEC": ["cotisation", "assurance", "chiffre_affaires"],
    "EC Cabinet": ["cotisation", "formation"],
    "EC Salarié": ["cotisation", "formation"],
    "EC Indépendant": ["cotisation", "assurance", "chiffre_affaires", "formation"],
    "Stagiaire": [],
}

# Ordre d'affichage des critères (les colonnes du Tableau).
CRITERES: list[str] = ["cotisation", "formation", "assurance", "chiffre_affaires"]

# Les colonnes de situation affichées pour chaque catégorie dans la Base du
# Tableau : une condition ne porte que sur l'une d'elles. Les colonnes
# descriptives (NIF, associé gérant, cabinet d'attache) ne jugent personne.
CRITERES_APPLICABLES: dict[str, list[str]] = {
    "Société": ["cotisation", "chiffre_affaires", "assurance"],
    "EC Indépendant": ["cotisation", "formation", "assurance", "chiffre_affaires"],
    "EC Cabinet": ["cotisation", "formation"],
    "EC Salarié": ["cotisation", "formation"],
    "Stagiaire": ["cotisation"],
}
CATEGORIES_REGLABLES: list[str] = ["EC Cabinet", "EC Indépendant", "EC Salarié", "Société", "Stagiaire"]

# Ce qu'un critère pèse dans la conclusion, réglable par catégorie :
BLOQUANT = "bloquant"        # un défaut donne NON INSCRIT
A_DELIBERER_MODE = "a_deliberer"  # un défaut donne À DÉLIBÉRER
IGNORE = "ignore"            # le critère n'est pas exigé
MODES = (BLOQUANT, A_DELIBERER_MODE, IGNORE)

_LIBELLE_CRITERE = {
    "cotisation": "cotisation non réglée",
    "assurance": "assurance non valide",
    "chiffre_affaires": "chiffre d'affaires non déclaré",
}

_LIBELLE_MANQUANT = {
    "cotisation": "cotisation non renseignée",
    "assurance": "assurance non renseignée",
    "chiffre_affaires": "chiffre d'affaires non renseigné",
}

# Barème : chaque colonne de situation de la catégorie est bloquante. Tout est
# réglable (bloquant, à délibérer, non exigé) dans les règles de délibération.
BAREME: dict[str, dict[str, str]] = {
    categorie: {critere: "bloquant" for critere in criteres}
    for categorie, criteres in CRITERES_APPLICABLES.items()
}


@dataclass
class TableauReglages:
    """Paramètres de délibération, réglables par organisation/exercice."""
    heures_formation_min: float = DEFAULT_HEURES_FORMATION_MIN
    age_seuil: int = DEFAULT_AGE_SEUIL          # ex. 50, 60, 99...
    age_action: str = DEFAULT_AGE_ACTION        # que faire au-delà du seuil d'âge
    age_conclusion_label: str = INSCRIT         # libellé si age_action == "inscrit"
    nouveau_anciennete_ans: int = DEFAULT_NOUVEAU_ANS
    # active/désactive l'exemption « nouveau membre »
    exempter_nouveaux: bool = True
    # Écarts au barème par catégorie : {"EC Salarié": {"formation": "a_deliberer"}}.
    # Une case absente garde le barème de `CATEGORIE_CRITERES`.
    criteres_par_categorie: dict[str, dict[str, str]] = field(default_factory=dict)
    # Ce que veut dire chaque condition, par catégorie (voir `DEFINITIONS`) :
    # {"EC Cabinet": {"heures_formation_min": 60, "cotisation_arrieres": False}}.
    definitions_par_categorie: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TableauReglages":
        if not data:
            return cls()
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        valeurs = {k: v for k, v in data.items() if k in allowed and v is not None}
        valeurs["criteres_par_categorie"] = _criteres_valides(valeurs.get("criteres_par_categorie"))
        valeurs["definitions_par_categorie"] = _definitions_valides(valeurs.get("definitions_par_categorie"))
        return cls(**valeurs)

    def _definition(self, categorie: str | None, cle: str) -> Any:
        categorie = "Société" if categorie == "SEC" else (categorie or "")
        valeur = self.definitions_par_categorie.get(categorie, {}).get(cle)
        return DEFINITIONS[cle] if valeur is None else valeur

    def heures_min(self, categorie: str | None) -> float:
        """Minimum d'heures (NHV) de la catégorie ; à défaut, le minimum général."""
        propre = self.definitions_par_categorie.get("Société" if categorie == "SEC" else (categorie or ""), {}).get("heures_formation_min")
        return float(propre) if propre is not None else float(self.heures_formation_min)

    def libelle_heures_min(self) -> str:
        """« 120 h », ou le détail quand une catégorie a son propre minimum."""
        def h(valeur: float) -> str:
            return f"{int(valeur) if float(valeur).is_integer() else valeur} h"
        soumises = [c for c, crit in CRITERES_APPLICABLES.items() if "formation" in crit]
        minima = {c: self.heures_min(c) for c in soumises}
        if len(set(minima.values())) <= 1:
            return h(next(iter(minima.values()), self.heures_formation_min))
        return " · ".join(f"{c} {h(v)}" for c, v in minima.items())

    def cotisation_arrieres(self, categorie: str | None) -> bool:
        """Les arriérés de cotisation doivent-ils être soldés pour être en règle ?"""
        return bool(self._definition(categorie, "cotisation_arrieres"))

    def cotisation_partielle(self, categorie: str | None) -> str:
        """Ce que donne une cotisation commencée mais pas soldée : a_deliberer ou bloquant."""
        return str(self._definition(categorie, "cotisation_partielle"))


# Définitions par défaut des conditions ; `heures_formation_min` absent = minimum général.
DEFINITIONS: dict[str, Any] = {
    "heures_formation_min": None,
    "cotisation_arrieres": True,
    "cotisation_partielle": "a_deliberer",
    # Date (AAAA-MM-JJ) jusqu'à laquelle l'assurance doit au moins couvrir ;
    # absente = la date de situation du fichier analysé.
    "assurance_fin_min": None,
    # Date (AAAA-MM-JJ) à partir de laquelle une déclaration de chiffre d'affaires
    # compte ; absente = toute déclaration de l'exercice (pas de condition de date).
    "ca_declaration_min": None,
}


def _definitions_valides(data: Any) -> dict[str, dict[str, Any]]:
    """Catégories connues, valeurs plausibles ; seuls les écarts aux défauts sont gardés."""
    if not isinstance(data, dict):
        return {}
    resultat: dict[str, dict[str, Any]] = {}
    for categorie, valeurs in data.items():
        categorie = "Société" if categorie == "SEC" else categorie
        if categorie not in CATEGORIES_REGLABLES or not isinstance(valeurs, dict):
            continue
        propres: dict[str, Any] = {}
        heures = valeurs.get("heures_formation_min")
        if isinstance(heures, (int, float)) and not isinstance(heures, bool) and 0 <= heures <= 10_000:
            if "formation" in CRITERES_APPLICABLES.get(categorie, []):
                propres["heures_formation_min"] = float(heures)
        if isinstance(valeurs.get("cotisation_arrieres"), bool) and valeurs["cotisation_arrieres"] != DEFINITIONS["cotisation_arrieres"]:
            propres["cotisation_arrieres"] = valeurs["cotisation_arrieres"]
        if valeurs.get("cotisation_partielle") in (BLOQUANT, A_DELIBERER_MODE) and valeurs["cotisation_partielle"] != DEFINITIONS["cotisation_partielle"]:
            propres["cotisation_partielle"] = valeurs["cotisation_partielle"]
        if "assurance" in CRITERES_APPLICABLES.get(categorie, []) and valeurs.get("assurance_fin_min"):
            try:
                from datetime import date as _date

                propres["assurance_fin_min"] = _date.fromisoformat(str(valeurs["assurance_fin_min"])).isoformat()
            except ValueError:
                pass  # date illisible : la date de situation reste la référence
        if "chiffre_affaires" in CRITERES_APPLICABLES.get(categorie, []) and valeurs.get("ca_declaration_min"):
            try:
                from datetime import date as _date

                propres["ca_declaration_min"] = _date.fromisoformat(str(valeurs["ca_declaration_min"])).isoformat()
            except ValueError:
                pass  # date illisible : pas de condition de date
        if propres:
            resultat[categorie] = propres
    return resultat


def assurance_valide(
    categorie: str | None,
    couverture: dict[str, Any] | None,
    valeur_import: bool | None,
    reglages: "TableauReglages | None" = None,
    *,
    date_situation: Any = None,
) -> bool | None:
    """L'assurance couvre-t-elle au moins jusqu'à la date minimale de la catégorie ?

    `couverture` : {"souscrit", "debut", "fin"} tirée des déclarations
    d'assurance. Sans déclaration, la valeur de l'import décide. Sans date
    minimale réglée, la date de situation du fichier sert de minimum.
    """
    from datetime import date as _date

    reglages = reglages or TableauReglages()
    if not couverture:
        return valeur_import
    if couverture.get("souscrit") is False:
        return False
    brut = reglages._definition(categorie, "assurance_fin_min")
    minimum = _date.fromisoformat(brut) if brut else (date_situation if isinstance(date_situation, _date) else None)
    fin = couverture.get("fin")
    if minimum is None or fin is None:
        # Rien à comparer : la souscription déclarée fait foi.
        return couverture.get("souscrit") if couverture.get("souscrit") is not None else valeur_import
    return fin >= minimum


def ca_declare(
    categorie: str | None,
    declarations: list[tuple[bool, Any]] | None,
    reglages: "TableauReglages | None" = None,
) -> bool | None:
    """Le chiffre d'affaires est-il déclaré, selon la date réglée pour la catégorie ?

    `declarations` : (ca_present, date de la déclaration) pour chaque déclaration
    de l'exercice. Sans date réglée, une déclaration suffit, quelle que soit sa
    date. Avec une date, seule compte une déclaration faite ce jour-là ou après ;
    une déclaration sans date ne permet pas de trancher (None : à délibérer).
    """
    from datetime import date as _date

    if not declarations:
        return None
    reglages = reglages or TableauReglages()
    brut = reglages._definition(categorie, "ca_declaration_min")
    presentes = [quand for present, quand in declarations if present]
    if not brut:
        return bool(presentes)
    minimum = _date.fromisoformat(brut)
    if any(isinstance(quand, _date) and quand >= minimum for quand in presentes):
        return True
    if any(quand is None for quand in presentes):
        return None
    return False


def etat_formation(dossier: dict[str, Any], exercice_annee: int | None, reglages: "TableauReglages | None" = None) -> str:
    """« atteint », « insuffisant », « non_requis » (catégorie ou nouveau membre) ou « inconnu »."""
    reglages = reglages or TableauReglages()
    if "formation" not in (criteres_requis(dossier.get("categorie"), reglages) or []):
        return "non_requis"
    nouveau = est_nouveau(dossier, exercice_annee, reglages)
    if nouveau:
        return "non_requis"
    valeur = _formation_ok(dossier, nouveau, reglages)
    return "inconnu" if valeur is None else ("atteint" if valeur else "insuffisant")


def etat_cotisation(
    categorie: str | None,
    notes: dict[str, Any] | None,
    valeur_import: bool | None,
    reglages: "TableauReglages | None" = None,
) -> str | None:
    """« payee », « partielle », « non_payee » ou None, selon la définition de la catégorie.

    Les notes de débit font foi quand le membre en a : la cotisation de N doit
    être soldée et, si la catégorie l'exige, les arriérés de cotisation aussi.
    Sans note, la valeur de l'import (Oui/Non) décide.
    """
    reglages = reglages or TableauReglages()
    if not notes:
        return None if valeur_import is None else ("payee" if valeur_import else "non_payee")
    from decimal import Decimal

    def nombre(cle: str) -> Decimal:
        return Decimal(str(notes.get(cle) or 0))

    avec_arrieres = reglages.cotisation_arrieres(categorie)
    du = nombre("du_n") + (nombre("du_anterieur") if avec_arrieres else 0)
    reste = nombre("reste_n") + (nombre("reste_anterieur") if avec_arrieres else 0)
    if du <= 0:
        # Rien d'exigible selon cette définition (ex. seuls des arriérés, non comptés).
        return "payee"
    if reste <= 0:
        return "payee"
    return "partielle" if reste < du else "non_payee"


def _criteres_valides(data: Any) -> dict[str, dict[str, str]]:
    """Ne garde que des catégories, critères et modes connus — et seulement les écarts au barème."""
    if not isinstance(data, dict):
        return {}
    resultat: dict[str, dict[str, str]] = {}
    for categorie, regles in data.items():
        categorie = "Société" if categorie == "SEC" else categorie
        if categorie not in CATEGORIES_REGLABLES or not isinstance(regles, dict):
            continue
        defaut = bareme_categorie(categorie)
        ecarts = {
            critere: mode
            for critere, mode in regles.items()
            if critere in defaut and mode in MODES and mode != defaut[critere]
        }
        if ecarts:
            resultat[categorie] = ecarts
    return resultat


def bareme_categorie(categorie: str) -> dict[str, str]:
    """Le barème d'origine, limité aux colonnes de la catégorie (voir `CRITERES_APPLICABLES`)."""
    categorie = "Société" if categorie == "SEC" else categorie
    bareme = BAREME.get(categorie, {})
    return {critere: bareme.get(critere, IGNORE) for critere in CRITERES_APPLICABLES.get(categorie, [])}


def regles_categorie(categorie: str | None, reglages: "TableauReglages | None" = None) -> dict[str, str] | None:
    """Le mode de chaque critère pour cette catégorie, réglages compris. None si catégorie inconnue."""
    categorie = "Société" if categorie == "SEC" else (categorie or "")
    if categorie not in CATEGORIE_CRITERES:
        return None
    regles = bareme_categorie(categorie)
    if reglages is not None:
        regles.update(reglages.criteres_par_categorie.get(categorie, {}))
    return regles


def criteres_requis(categorie: str | None, reglages: "TableauReglages | None" = None) -> list[str] | None:
    """Les critères exigés (bloquants ou à délibérer), dans l'ordre des colonnes."""
    regles = regles_categorie(categorie, reglages)
    if regles is None:
        return None
    return [critere for critere in CRITERES if regles.get(critere, IGNORE) != IGNORE]


def annee_ordre(numero_ordre: str | None) -> int | None:
    """Extrait l'année d'inscription du N° d'ordre (ex. EC/25.00604 -> 2025)."""
    if not numero_ordre:
        return None
    m = re.search(r"/(\d{2})\.", str(numero_ordre))
    if m:
        return 2000 + int(m.group(1))
    return None


ANCIENNETE_A_VERIFIER = "À vérifier"


def libelle_anciennete(numero_ordre: str | None, exercice_annee: int | None) -> str | None:
    """« Nouveau » si inscrit l'année de l'exercice traité, « Ancien » si avant.

    L'année de référence est celle de l'exercice, jamais une date figée : à
    l'exercice suivant, les inscrits de cette année deviennent des anciens. Ne pas
    confondre avec `est_nouveau`, qui décide de l'exemption de formation selon le
    réglage `nouveau_anciennete_ans`.
    """
    annee = annee_ordre(numero_ordre)
    if annee is None or exercice_annee is None:
        return None
    if annee > exercice_annee:
        # Personne n'est inscrit après l'exercice traité : numéro provisoire ou erroné.
        return ANCIENNETE_A_VERIFIER
    return "Nouveau" if annee == exercice_annee else "Ancien"


def est_nouveau(dossier: dict[str, Any], exercice_annee: int | None,
                reglages: "TableauReglages | None" = None) -> bool:
    reglages = reglages or TableauReglages()
    if not reglages.exempter_nouveaux:
        return False
    anciennete = str(dossier.get("anciennete") or "").strip().lower()
    if "nouveau" in anciennete:
        return True
    if exercice_annee is not None:
        an = annee_ordre(dossier.get("numero_ordre"))
        if an is not None and exercice_annee - (reglages.nouveau_anciennete_ans - 1) <= an <= exercice_annee:
            return True
    return False


def _formation_ok(dossier: dict[str, Any], nouveau: bool, reglages: TableauReglages) -> bool | None:
    """True = satisfaite/exemptée, False = insuffisante, None = inconnu."""
    if nouveau:
        return True
    heures = dossier.get("heures_forco")
    if heures is not None:
        return float(heures) >= reglages.heures_min(dossier.get("categorie"))
    hf = dossier.get("hformation")
    return hf if hf is not None else None


def _critere_ok(nom: str, dossier: dict[str, Any], nouveau: bool, reglages: TableauReglages) -> bool | None:
    if nom == "cotisation":
        return dossier.get("cotisation_payee")
    if nom == "assurance":
        return dossier.get("assurance")
    if nom == "chiffre_affaires":
        return dossier.get("chiffre_affaires")
    if nom == "formation":
        return _formation_ok(dossier, nouveau, reglages)
    return None


def evaluer(dossier: dict[str, Any], exercice_annee: int | None = None,
            reglages: "TableauReglages | None" = None) -> dict[str, Any]:
    """Retourne {conclusion, motif, exemptions} pour un dossier.

    `dossier` attend : categorie, numero_ordre, cotisation_payee (bool),
    assurance (bool), chiffre_affaires (bool), heures_forco (float),
    hformation (bool|None), anciennete (str), age (int|None).
    """
    reglages = reglages or TableauReglages()
    categorie = dossier.get("categorie") or "Inconnu"
    regles = regles_categorie(categorie, reglages)
    criteres = criteres_requis(categorie, reglages)
    if criteres is None or regles is None:
        return {"conclusion": A_DELIBERER, "motif": f"Catégorie non reconnue : {categorie}", "exemptions": []}
    if not criteres:
        return {"conclusion": NON_APPLICABLE, "motif": "Section sans critère automatique", "exemptions": []}

    nouveau = est_nouveau(dossier, exercice_annee, reglages)
    age = dossier.get("age")
    exemptions: list[str] = []
    if nouveau:
        exemptions.append(f"nouveau membre (< {reglages.nouveau_anciennete_ans} ans) : formation non requise")

    motifs_echec: list[str] = []
    motifs_a_deliberer: list[str] = []
    motifs_manquants: list[str] = []
    formation_insuffisante = False

    for critere in criteres:
        valeur = _critere_ok(critere, dossier, nouveau, reglages)
        if critere == "formation":
            if valeur is False:
                formation_insuffisante = True
            elif valeur is None:
                motifs_manquants.append("heures de formation non renseignées")
        elif critere == "cotisation" and valeur is False and dossier.get("cotisation_partielle"):
            # Un membre qui a commencé à payer : la définition de la catégorie dit
            # s'il revient au conseil (par défaut) ou s'il n'est pas en règle.
            cible = motifs_echec if reglages.cotisation_partielle(categorie) == BLOQUANT else motifs_a_deliberer
            cible.append("cotisation partiellement réglée")
        else:
            if valeur is False:
                cible = motifs_a_deliberer if regles[critere] == A_DELIBERER_MODE else motifs_echec
                cible.append(_LIBELLE_CRITERE[critere])
            elif valeur is None:
                motifs_manquants.append(_LIBELLE_MANQUANT.get(critere, _LIBELLE_CRITERE[critere]))

    # 1) Échec « dur » (cotisation, assurance, CA) -> NON INSCRIT
    if motifs_echec:
        return {"conclusion": NON_INSCRIT, "motif": " ; ".join(motifs_echec), "exemptions": exemptions}

    # 2) Formation insuffisante : exemption d'âge réglable, sinon NON INSCRIT
    if formation_insuffisante:
        depasse_age = age is not None and reglages.age_seuil is not None and age > reglages.age_seuil
        seuil_h = int(reglages.heures_min(categorie))
        if depasse_age and reglages.age_action != "aucune":
            if reglages.age_action == "inscrit":
                return {
                    "conclusion": reglages.age_conclusion_label,
                    "motif": f"Membre de plus de {reglages.age_seuil} ans ({age}) : exempté des {seuil_h}h",
                    "exemptions": exemptions + [f"âge > {reglages.age_seuil} ans"],
                }
            return {
                "conclusion": A_DELIBERER,
                "motif": f"Membre de plus de {reglages.age_seuil} ans ({age}) : exemption des {seuil_h}h à trancher par le conseil",
                "exemptions": exemptions + [f"âge > {reglages.age_seuil} ans"],
            }
        if regles["formation"] == A_DELIBERER_MODE:
            motifs_a_deliberer.append(f"heures de formation < {seuil_h}h")
        else:
            return {"conclusion": NON_INSCRIT, "motif": f"heures de formation < {seuil_h}h", "exemptions": exemptions}

    # 3) Défaut d'un critère que les réglages renvoient au conseil
    if motifs_a_deliberer:
        return {
            "conclusion": A_DELIBERER,
            "motif": "À trancher par le conseil : " + " ; ".join(motifs_a_deliberer),
            "exemptions": exemptions,
        }

    # 4) Données manquantes -> à délibérer
    if motifs_manquants:
        return {"conclusion": A_DELIBERER, "motif": "Données manquantes : " + " ; ".join(motifs_manquants), "exemptions": exemptions}

    # 5) Tous les critères satisfaits
    return {"conclusion": INSCRIT, "motif": "Tous les critères sont satisfaits", "exemptions": exemptions}
