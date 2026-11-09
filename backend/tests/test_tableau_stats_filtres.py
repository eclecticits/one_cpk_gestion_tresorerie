"""Filtres du tableau de bord : personne (physique, morale) et statut « Actif »."""

import pytest

from app.modules.tableau import service

LIGNES = [
    {"categorie": "EC Cabinet", "actif": True, "conclusion": "INSCRIT"},
    {"categorie": "EC Cabinet", "actif": False, "conclusion": "NON INSCRIT"},
    {"categorie": "EC Salarié", "actif": None, "conclusion": "INSCRIT"},
    {"categorie": "SEC", "actif": None, "conclusion": "À DÉLIBÉRER"},
]


@pytest.fixture
def base(monkeypatch):
    async def stats(db, organisation_id):
        return {"last_exercice": "2026"}

    async def base_tableau(db, organisation_ids, exercice=None, situation=None, limit=None, **_):
        if situation == "sortis":
            return {"total_membres": 0, "dossiers": [], "membres_a_completer": []}
        return {"total_membres": len(LIGNES), "dossiers": [], "membres_a_completer": [dict(l) for l in LIGNES]}

    monkeypatch.setattr(service, "get_stats", stats)
    monkeypatch.setattr(service, "get_base_tableau", base_tableau)


async def test_par_defaut_les_personnes_physiques_actives(base):
    s = await service.get_stats_tableau(None, 1)
    assert (s["membres_base"], s["membres_total"], s["en_regle"]) == (1, 4, 1)
    assert s["filtre"] == {"personne": "physique", "actif": "oui"}
    # Le membre sans statut est écarté, mais signalé.
    assert s["hors_filtre_actif_inconnu"] == 1


async def test_le_statut_ne_filtre_jamais_les_personnes_morales(base):
    morales = await service.get_stats_tableau(None, 1, personne="morale", actif="oui")
    assert (morales["membres_base"], morales["a_deliberer"], morales["hors_filtre_actif_inconnu"]) == (1, 1, 0)
    toutes = await service.get_stats_tableau(None, 1, personne="toutes", actif="non")
    assert (toutes["membres_base"], toutes["non_en_regle"], toutes["a_deliberer"]) == (2, 1, 1)


async def test_tous_et_non_renseigne(base):
    assert (await service.get_stats_tableau(None, 1, personne="toutes", actif="tous"))["membres_base"] == 4
    inconnus = await service.get_stats_tableau(None, 1, personne="physique", actif="inconnu")
    assert (inconnus["membres_base"], inconnus["hors_filtre_actif_inconnu"]) == (1, 0)
