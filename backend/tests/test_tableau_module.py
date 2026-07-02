from __future__ import annotations

from app.modules.secretariat.tableau.analyzer import (
    HEURES_FORCO_MIN,
    compute_analyse_stats,
    detect_anomalies,
)
from app.modules.secretariat.tableau.comparison import compare_exercices


def _dossier(**overrides) -> dict:
    base = {
        "id": 1,
        "nom": "Dupont",
        "prenom": "Jean",
        "categorie": "EC Cabinet",
        "cotisation_payee": True,
        "heures_forco": 25.0,
        "assurance": True,
    }
    base.update(overrides)
    return base


class TestDetectAnomalies:
    def test_dossier_complet_ne_genere_aucune_anomalie(self):
        anomalies = detect_anomalies([_dossier()])
        assert anomalies == []

    def test_doublon_nom_prenom_insensible_a_la_casse(self):
        dossiers = [
            _dossier(id=1, nom="Dupont", prenom="Jean"),
            _dossier(id=2, nom="DUPONT", prenom="jean"),
        ]
        anomalies = detect_anomalies(dossiers)
        doublons = [a for a in anomalies if a["type_anomalie"] == "doublon"]
        assert len(doublons) == 1
        assert doublons[0]["dossier_id"] == 2
        assert doublons[0]["gravite"] == "high"

    def test_nom_manquant_signale_dossier_incomplet(self):
        anomalies = detect_anomalies([_dossier(nom="")])
        types = {a["type_anomalie"] for a in anomalies}
        assert "dossier_incomplet" in types

    def test_categorie_inconnue(self):
        anomalies = detect_anomalies([_dossier(categorie="Autre")])
        assert any(a["type_anomalie"] == "categorie_inconnue" and a["gravite"] == "medium" for a in anomalies)

    def test_cotisation_non_payee(self):
        anomalies = detect_anomalies([_dossier(cotisation_payee=False)])
        assert any(a["type_anomalie"] == "cotisation_non_payee" and a["gravite"] == "high" for a in anomalies)

    def test_cotisation_non_renseignee(self):
        anomalies = detect_anomalies([_dossier(cotisation_payee=None)])
        assert any(a["type_anomalie"] == "cotisation_non_renseignee" and a["gravite"] == "medium" for a in anomalies)

    def test_heures_forco_insuffisantes(self):
        anomalies = detect_anomalies([_dossier(heures_forco=HEURES_FORCO_MIN - 1)])
        assert any(a["type_anomalie"] == "heures_forco_insuffisantes" for a in anomalies)

    def test_heures_forco_au_seuil_ne_declenche_pas_anomalie(self):
        anomalies = detect_anomalies([_dossier(heures_forco=HEURES_FORCO_MIN)])
        assert not any(a["type_anomalie"].startswith("heures_forco") for a in anomalies)

    def test_heures_forco_manquantes(self):
        anomalies = detect_anomalies([_dossier(heures_forco=None)])
        assert any(a["type_anomalie"] == "heures_forco_manquantes" and a["gravite"] == "low" for a in anomalies)

    def test_assurance_manquante(self):
        anomalies = detect_anomalies([_dossier(assurance=False)])
        assert any(a["type_anomalie"] == "assurance_manquante" and a["gravite"] == "high" for a in anomalies)

    def test_assurance_non_renseignee(self):
        anomalies = detect_anomalies([_dossier(assurance=None)])
        assert any(a["type_anomalie"] == "assurance_non_renseignee" and a["gravite"] == "medium" for a in anomalies)

    def test_dossier_avec_plusieurs_problemes_cumule_les_anomalies(self):
        dossier = _dossier(categorie="Autre", cotisation_payee=False, heures_forco=None, assurance=False)
        anomalies = detect_anomalies([dossier])
        types = {a["type_anomalie"] for a in anomalies}
        assert types == {
            "categorie_inconnue",
            "cotisation_non_payee",
            "heures_forco_manquantes",
            "assurance_manquante",
        }


class TestComputeAnalyseStats:
    def test_stats_sur_dossiers_complets(self):
        dossiers = [_dossier(id=1), _dossier(id=2, nom="Martin", prenom="Alice")]
        stats = compute_analyse_stats(dossiers, detect_anomalies(dossiers))
        assert stats["total_dossiers"] == 2
        assert stats["dossiers_complets"] == 2
        assert stats["dossiers_incomplets"] == 0
        assert stats["anomalies_count"] == 0

    def test_stats_comptent_dossiers_incomplets_et_anomalies_par_type(self):
        dossiers = [
            _dossier(id=1, nom="Dupont", prenom="Jean", cotisation_payee=None),
            _dossier(id=2, nom="Martin", prenom="Alice", heures_forco=None),
            _dossier(id=3, nom="Petit", prenom="Marc", assurance=None),
        ]
        anomalies = detect_anomalies(dossiers)
        stats = compute_analyse_stats(dossiers, anomalies)
        assert stats["total_dossiers"] == 3
        assert stats["dossiers_incomplets"] == 3
        assert stats["dossiers_complets"] == 0
        assert stats["assurances_manquantes"] == 1
        assert stats["heures_forco_insuffisantes"] == 1
        assert stats["stats_json"]["anomalies_par_type"]["cotisation_non_renseignee"] == 1

    def test_stats_json_regroupe_categories(self):
        dossiers = [_dossier(id=1, categorie="EC Cabinet"), _dossier(id=2, categorie="SEC")]
        stats = compute_analyse_stats(dossiers, detect_anomalies(dossiers))
        assert stats["stats_json"]["categories"] == {"EC Cabinet": 1, "SEC": 1}


class TestCompareExercices:
    def test_dossiers_identiques_sont_en_commun(self):
        dossiers = [_dossier(id=1)]
        result = compare_exercices(dossiers, dossiers, "2025", "2026")
        assert result["dossiers_en_commun"] == 1
        assert result["nouveaux_dans_b"] == 0
        assert result["absents_de_b"] == 0
        assert result["changements_categorie"] == 0

    def test_nouveau_dossier_dans_exercice_b(self):
        dossiers_a = [_dossier(id=1, nom="Dupont", prenom="Jean")]
        dossiers_b = [
            _dossier(id=1, nom="Dupont", prenom="Jean"),
            _dossier(id=2, nom="Martin", prenom="Alice"),
        ]
        result = compare_exercices(dossiers_a, dossiers_b, "2025", "2026")
        assert result["nouveaux_dans_b"] == 1
        assert any(d["type"] == "nouveau" and d["nom"] == "Martin" for d in result["details"])

    def test_dossier_absent_de_exercice_b(self):
        dossiers_a = [
            _dossier(id=1, nom="Dupont", prenom="Jean"),
            _dossier(id=2, nom="Martin", prenom="Alice"),
        ]
        dossiers_b = [_dossier(id=1, nom="Dupont", prenom="Jean")]
        result = compare_exercices(dossiers_a, dossiers_b, "2025", "2026")
        assert result["absents_de_b"] == 1
        assert any(d["type"] == "absent" and d["nom"] == "Martin" for d in result["details"])

    def test_changement_de_categorie_est_detecte(self):
        dossiers_a = [_dossier(id=1, nom="Dupont", prenom="Jean", categorie="EC Salarié")]
        dossiers_b = [_dossier(id=1, nom="Dupont", prenom="Jean", categorie="EC Indépendant")]
        result = compare_exercices(dossiers_a, dossiers_b, "2025", "2026")
        assert result["changements_categorie"] == 1
        detail = next(d for d in result["details"] if d["type"] == "changement_categorie")
        assert detail["categorie_avant"] == "EC Salarié"
        assert detail["categorie_apres"] == "EC Indépendant"

    def test_matching_ignore_casse_et_espaces(self):
        dossiers_a = [_dossier(id=1, nom="  Dupont ", prenom=" Jean")]
        dossiers_b = [_dossier(id=1, nom="DUPONT", prenom="jean")]
        result = compare_exercices(dossiers_a, dossiers_b, "2025", "2026")
        assert result["dossiers_en_commun"] == 1
        assert result["nouveaux_dans_b"] == 0
