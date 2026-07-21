"""Analyse des dossiers Tableau : verdict + détection d'anomalies + stats.

S'appuie sur `verdict.evaluer` pour la conclusion réglementaire
(INSCRIT / NON INSCRIT / À DÉLIBÉRER) et produit des anomalies cohérentes
avec ce verdict.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from . import verdict as verdict_engine

HEURES_FORCO_MIN = verdict_engine.HEURES_FORMATION_MIN  # 120h / 3 ans
COTISATION_CATEGORIES = {"Société", "SEC", "EC Cabinet", "EC Indépendant", "EC Salarié"}


def detect_anomalies(dossiers: list[dict[str, Any]], exercice_annee: int | None = None) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    seen: dict[str, int] = {}

    for d in dossiers:
        dossier_id = d["id"]
        nom = (d.get("nom") or "")
        prenom = (d.get("prenom") or "")
        key = f"{nom.lower()}|{prenom.lower()}"
        nouveau = verdict_engine.est_nouveau(d, exercice_annee)
        criteres = verdict_engine.CATEGORIE_CRITERES.get(d.get("categorie", ""), None)

        if key in seen:
            anomalies.append({
                "dossier_id": dossier_id,
                "type_anomalie": "doublon",
                "gravite": "high",
                "description": f"Doublon détecté : {nom} {prenom} apparaît plusieurs fois.",
                "champ_concerne": "nom/prenom",
                "valeur_trouvee": f"{nom} {prenom}".strip(),
                "valeur_attendue": "Entrée unique",
            })
        else:
            seen[key] = dossier_id

        if not nom.strip():
            anomalies.append({
                "dossier_id": dossier_id, "type_anomalie": "dossier_incomplet", "gravite": "high",
                "description": "Nom manquant — dossier incomplet.", "champ_concerne": "nom",
                "valeur_trouvee": None, "valeur_attendue": "Nom obligatoire",
            })

        categorie = d.get("categorie", "")
        if categorie not in COTISATION_CATEGORIES and categorie != "Stagiaire":
            anomalies.append({
                "dossier_id": dossier_id, "type_anomalie": "categorie_inconnue", "gravite": "medium",
                "description": f"Catégorie non reconnue : «{categorie}».", "champ_concerne": "categorie",
                "valeur_trouvee": categorie, "valeur_attendue": ", ".join(sorted(COTISATION_CATEGORIES)),
            })

        if not criteres:
            continue  # stagiaire / catégorie sans critère

        # Cotisation
        cot = d.get("cotisation_payee")
        if cot is False:
            anomalies.append({
                "dossier_id": dossier_id, "type_anomalie": "cotisation_non_payee", "gravite": "high",
                "description": "Cotisation non réglée.", "champ_concerne": "cotisation_payee",
                "valeur_trouvee": "Non", "valeur_attendue": "Oui",
            })
        elif cot is None:
            anomalies.append({
                "dossier_id": dossier_id, "type_anomalie": "cotisation_non_renseignee", "gravite": "medium",
                "description": "Statut de cotisation non renseigné.", "champ_concerne": "cotisation_payee",
                "valeur_trouvee": None, "valeur_attendue": "Oui ou Non",
            })

        # Formation (uniquement si requise et non exemptée)
        if "formation" in criteres and not nouveau:
            heures = d.get("heures_forco")
            if heures is not None and heures < HEURES_FORCO_MIN:
                age = d.get("age")
                gravite = "low" if (age is not None and age > verdict_engine.AGE_EXEMPTION) else "medium"
                anomalies.append({
                    "dossier_id": dossier_id, "type_anomalie": "heures_forco_insuffisantes", "gravite": gravite,
                    "description": f"Heures de formation insuffisantes : {heures}h (minimum {int(HEURES_FORCO_MIN)}h).",
                    "champ_concerne": "heures_forco", "valeur_trouvee": str(heures),
                    "valeur_attendue": f">= {int(HEURES_FORCO_MIN)}h",
                })
            elif heures is None and d.get("hformation") is None:
                anomalies.append({
                    "dossier_id": dossier_id, "type_anomalie": "heures_forco_manquantes", "gravite": "low",
                    "description": "Heures de formation non renseignées.", "champ_concerne": "heures_forco",
                    "valeur_trouvee": None, "valeur_attendue": f">= {int(HEURES_FORCO_MIN)}h",
                })

        # Assurance (sociétés + indépendants)
        if "assurance" in criteres:
            ass = d.get("assurance")
            if ass is False:
                anomalies.append({
                    "dossier_id": dossier_id, "type_anomalie": "assurance_manquante", "gravite": "high",
                    "description": "Assurance professionnelle absente ou non valide.", "champ_concerne": "assurance",
                    "valeur_trouvee": "Non", "valeur_attendue": "Oui",
                })
            elif ass is None:
                anomalies.append({
                    "dossier_id": dossier_id, "type_anomalie": "assurance_non_renseignee", "gravite": "medium",
                    "description": "Statut d'assurance non renseigné.", "champ_concerne": "assurance",
                    "valeur_trouvee": None, "valeur_attendue": "Oui ou Non",
                })

        # Chiffre d'affaires (sociétés + indépendants)
        if "chiffre_affaires" in criteres:
            ca = d.get("chiffre_affaires")
            if ca is False:
                anomalies.append({
                    "dossier_id": dossier_id, "type_anomalie": "chiffre_affaires_non_declare", "gravite": "high",
                    "description": "Chiffre d'affaires non déclaré.", "champ_concerne": "chiffre_affaires",
                    "valeur_trouvee": "Non", "valeur_attendue": "Oui",
                })
            elif ca is None:
                anomalies.append({
                    "dossier_id": dossier_id, "type_anomalie": "chiffre_affaires_non_renseigne", "gravite": "medium",
                    "description": "Déclaration de chiffre d'affaires non renseignée.", "champ_concerne": "chiffre_affaires",
                    "valeur_trouvee": None, "valeur_attendue": "Oui ou Non",
                })

    return anomalies


def compute_analyse_stats(
    dossiers: list[dict[str, Any]],
    anomalies: list[dict[str, Any]],
    verdicts: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    total = len(dossiers)
    verdicts = verdicts or {}

    incomplets = sum(
        1 for d in dossiers
        if d.get("cotisation_payee") is None or d.get("heures_forco") is None or d.get("assurance") is None
    )
    doublons = sum(1 for a in anomalies if a["type_anomalie"] == "doublon")
    cotisations_non_payees = sum(1 for a in anomalies if a["type_anomalie"] == "cotisation_non_payee")
    heures_insuffisantes = sum(1 for a in anomalies if a["type_anomalie"] in ("heures_forco_insuffisantes", "heures_forco_manquantes"))
    assurances_manquantes = sum(1 for a in anomalies if a["type_anomalie"] in ("assurance_manquante", "assurance_non_renseignee"))

    conclusions = Counter(v.get("conclusion") for v in verdicts.values())

    return {
        "total_dossiers": total,
        "dossiers_complets": total - incomplets,
        "dossiers_incomplets": incomplets,
        "anomalies_count": len(anomalies),
        "doublons_count": doublons,
        "cotisations_non_payees": cotisations_non_payees,
        "heures_forco_insuffisantes": heures_insuffisantes,
        "assurances_manquantes": assurances_manquantes,
        "stats_json": {
            "categories": dict(Counter(d.get("categorie", "Inconnu") for d in dossiers)),
            "anomalies_par_type": dict(Counter(a["type_anomalie"] for a in anomalies)),
            "anomalies_par_gravite": dict(Counter(a["gravite"] for a in anomalies)),
            "conclusions": {
                "inscrits": conclusions.get(verdict_engine.INSCRIT, 0),
                "non_inscrits": conclusions.get(verdict_engine.NON_INSCRIT, 0),
                "a_deliberer": conclusions.get(verdict_engine.A_DELIBERER, 0),
                "non_applicable": conclusions.get(verdict_engine.NON_APPLICABLE, 0),
            },
        },
    }
