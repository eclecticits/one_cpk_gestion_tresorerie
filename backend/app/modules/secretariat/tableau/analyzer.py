from __future__ import annotations

from collections import Counter
from typing import Any

HEURES_FORCO_MIN = 20.0
COTISATION_CATEGORIES = {"SEC", "EC Cabinet", "EC Indépendant", "EC Salarié"}


def detect_anomalies(dossiers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    seen: dict[str, int] = {}

    for d in dossiers:
        dossier_id = d["id"]
        nom = d.get("nom", "")
        prenom = d.get("prenom", "") or ""
        key = f"{nom.lower()}|{prenom.lower()}"

        if key in seen:
            anomalies.append({
                "dossier_id": dossier_id,
                "type_anomalie": "doublon",
                "gravite": "high",
                "description": f"Doublon détecté : {nom} {prenom} apparaît plusieurs fois dans le tableau.",
                "champ_concerne": "nom/prenom",
                "valeur_trouvee": f"{nom} {prenom}",
                "valeur_attendue": "Entrée unique",
            })
        else:
            seen[key] = dossier_id

        if not nom.strip():
            anomalies.append({
                "dossier_id": dossier_id,
                "type_anomalie": "dossier_incomplet",
                "gravite": "high",
                "description": "Nom manquant — dossier incomplet.",
                "champ_concerne": "nom",
                "valeur_trouvee": None,
                "valeur_attendue": "Nom obligatoire",
            })

        categorie = d.get("categorie", "")
        if categorie not in COTISATION_CATEGORIES:
            anomalies.append({
                "dossier_id": dossier_id,
                "type_anomalie": "categorie_inconnue",
                "gravite": "medium",
                "description": f"Catégorie inconnue ou non reconnue : «{categorie}».",
                "champ_concerne": "categorie",
                "valeur_trouvee": categorie,
                "valeur_attendue": ", ".join(sorted(COTISATION_CATEGORIES)),
            })

        cotisation_payee = d.get("cotisation_payee")
        if cotisation_payee is False:
            anomalies.append({
                "dossier_id": dossier_id,
                "type_anomalie": "cotisation_non_payee",
                "gravite": "high",
                "description": "Cotisation non réglée.",
                "champ_concerne": "cotisation_payee",
                "valeur_trouvee": "Non",
                "valeur_attendue": "Oui",
            })
        elif cotisation_payee is None:
            anomalies.append({
                "dossier_id": dossier_id,
                "type_anomalie": "cotisation_non_renseignee",
                "gravite": "medium",
                "description": "Statut de cotisation non renseigné.",
                "champ_concerne": "cotisation_payee",
                "valeur_trouvee": None,
                "valeur_attendue": "Oui ou Non",
            })

        heures_forco = d.get("heures_forco")
        if heures_forco is not None and heures_forco < HEURES_FORCO_MIN:
            anomalies.append({
                "dossier_id": dossier_id,
                "type_anomalie": "heures_forco_insuffisantes",
                "gravite": "medium",
                "description": f"Heures FORCO insuffisantes : {heures_forco}h (minimum requis : {HEURES_FORCO_MIN}h).",
                "champ_concerne": "heures_forco",
                "valeur_trouvee": str(heures_forco),
                "valeur_attendue": f">= {HEURES_FORCO_MIN}h",
            })
        elif heures_forco is None:
            anomalies.append({
                "dossier_id": dossier_id,
                "type_anomalie": "heures_forco_manquantes",
                "gravite": "low",
                "description": "Heures FORCO non renseignées.",
                "champ_concerne": "heures_forco",
                "valeur_trouvee": None,
                "valeur_attendue": f">= {HEURES_FORCO_MIN}h",
            })

        assurance = d.get("assurance")
        if assurance is False:
            anomalies.append({
                "dossier_id": dossier_id,
                "type_anomalie": "assurance_manquante",
                "gravite": "high",
                "description": "Assurance professionnelle absente ou non souscrite.",
                "champ_concerne": "assurance",
                "valeur_trouvee": "Non",
                "valeur_attendue": "Oui",
            })
        elif assurance is None:
            anomalies.append({
                "dossier_id": dossier_id,
                "type_anomalie": "assurance_non_renseignee",
                "gravite": "medium",
                "description": "Statut d'assurance non renseigné.",
                "champ_concerne": "assurance",
                "valeur_trouvee": None,
                "valeur_attendue": "Oui ou Non",
            })

    return anomalies


def compute_analyse_stats(dossiers: list[dict[str, Any]], anomalies: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(dossiers)
    anomalies_per_dossier: dict[int, list] = {}
    for a in anomalies:
        anomalies_per_dossier.setdefault(a["dossier_id"], []).append(a)

    incomplets = sum(
        1 for d in dossiers
        if d.get("cotisation_payee") is None or d.get("heures_forco") is None or d.get("assurance") is None
    )

    doublons = sum(1 for a in anomalies if a["type_anomalie"] == "doublon")
    cotisations_non_payees = sum(1 for a in anomalies if a["type_anomalie"] == "cotisation_non_payee")
    heures_insuffisantes = sum(1 for a in anomalies if a["type_anomalie"] in ("heures_forco_insuffisantes", "heures_forco_manquantes"))
    assurances_manquantes = sum(1 for a in anomalies if a["type_anomalie"] in ("assurance_manquante", "assurance_non_renseignee"))

    categories_counter = Counter(d.get("categorie", "Inconnu") for d in dossiers)

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
            "categories": dict(categories_counter),
            "anomalies_par_type": dict(Counter(a["type_anomalie"] for a in anomalies)),
            "anomalies_par_gravite": dict(Counter(a["gravite"] for a in anomalies)),
        },
    }
