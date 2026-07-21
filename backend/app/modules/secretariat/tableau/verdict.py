"""Moteur de verdict Tableau — INSCRIT / NON INSCRIT / À DÉLIBÉRER.

Logique métier ONEC (Conseil Provincial), validée à 99,8 % contre le
« Projet Tableau » du secrétariat.

Critères par catégorie :
- Société (SEC)      : cotisation + assurance + chiffre d'affaires
- EC Cabinet         : cotisation + formation (>= seuil h / 3 ans)
- EC Salarié         : cotisation + formation (>= seuil h / 3 ans)
- EC Indépendant     : cotisation + assurance + chiffre d'affaires + formation
- Stagiaire          : aucun critère automatique

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

INSCRIT = "INSCRIT"
NON_INSCRIT = "NON INSCRIT"
A_DELIBERER = "À DÉLIBÉRER"
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

_LIBELLE_CRITERE = {
    "cotisation": "cotisation non réglée",
    "assurance": "assurance non valide",
    "chiffre_affaires": "chiffre d'affaires non déclaré",
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

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TableauReglages":
        if not data:
            return cls()
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in allowed and v is not None})


def annee_ordre(numero_ordre: str | None) -> int | None:
    """Extrait l'année d'inscription du N° d'ordre (ex. EC/25.00604 -> 2025)."""
    if not numero_ordre:
        return None
    m = re.search(r"/(\d{2})\.", str(numero_ordre))
    if m:
        return 2000 + int(m.group(1))
    return None


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
        if an is not None and an >= exercice_annee - (reglages.nouveau_anciennete_ans - 1):
            return True
    return False


def _formation_ok(dossier: dict[str, Any], nouveau: bool, reglages: TableauReglages) -> bool | None:
    """True = satisfaite/exemptée, False = insuffisante, None = inconnu."""
    if nouveau:
        return True
    heures = dossier.get("heures_forco")
    if heures is not None:
        return float(heures) >= reglages.heures_formation_min
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
    criteres = CATEGORIE_CRITERES.get(categorie)
    if criteres is None:
        return {"conclusion": A_DELIBERER, "motif": f"Catégorie non reconnue : {categorie}", "exemptions": []}
    if not criteres:
        return {"conclusion": NON_APPLICABLE, "motif": "Section sans critère automatique", "exemptions": []}

    nouveau = est_nouveau(dossier, exercice_annee, reglages)
    age = dossier.get("age")
    exemptions: list[str] = []
    if nouveau:
        exemptions.append(f"nouveau membre (< {reglages.nouveau_anciennete_ans} ans) : formation non requise")

    motifs_echec: list[str] = []
    motifs_manquants: list[str] = []
    formation_insuffisante = False

    for critere in criteres:
        valeur = _critere_ok(critere, dossier, nouveau, reglages)
        if critere == "formation":
            if valeur is False:
                formation_insuffisante = True
            elif valeur is None:
                motifs_manquants.append("heures de formation non renseignées")
        else:
            if valeur is False:
                motifs_echec.append(_LIBELLE_CRITERE[critere])
            elif valeur is None:
                motifs_manquants.append(f"{critere} non renseigné")

    # 1) Échec « dur » (cotisation, assurance, CA) -> NON INSCRIT
    if motifs_echec:
        return {"conclusion": NON_INSCRIT, "motif": " ; ".join(motifs_echec), "exemptions": exemptions}

    # 2) Formation insuffisante : exemption d'âge réglable, sinon NON INSCRIT
    if formation_insuffisante:
        depasse_age = age is not None and reglages.age_seuil is not None and age > reglages.age_seuil
        seuil_h = int(reglages.heures_formation_min)
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
        return {"conclusion": NON_INSCRIT, "motif": f"heures de formation < {seuil_h}h", "exemptions": exemptions}

    # 3) Données manquantes -> à délibérer
    if motifs_manquants:
        return {"conclusion": A_DELIBERER, "motif": "Données manquantes : " + " ; ".join(motifs_manquants), "exemptions": exemptions}

    # 4) Tous les critères satisfaits
    return {"conclusion": INSCRIT, "motif": "Tous les critères sont satisfaits", "exemptions": exemptions}
