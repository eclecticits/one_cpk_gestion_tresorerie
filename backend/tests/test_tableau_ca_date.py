from __future__ import annotations

from datetime import date

from app.modules.tableau import verdict as v


def _reglages(categorie: str, minimum: str | None):
    definitions = {categorie: {"ca_declaration_min": minimum}} if minimum else {}
    return v.TableauReglages.from_dict({"definitions_par_categorie": definitions})


def test_sans_date_reglee_toute_declaration_compte():
    assert v.ca_declare("EC Indépendant", [(True, date(2025, 7, 4))], _reglages("EC Indépendant", None)) is True


def test_une_declaration_anterieure_a_la_date_ne_compte_pas():
    reglages = _reglages("Société", "2026-01-01")
    assert v.ca_declare("Société", [(True, date(2025, 7, 4))], reglages) is False
    assert v.ca_declare("Société", [(True, date(2025, 7, 4)), (True, date(2026, 3, 2))], reglages) is True
    # Le jour même compte.
    assert v.ca_declare("Société", [(True, date(2026, 1, 1))], reglages) is True


def test_une_declaration_sans_date_ne_permet_pas_de_trancher():
    reglages = _reglages("Société", "2026-01-01")
    assert v.ca_declare("Société", [(True, None)], reglages) is None
    assert v.ca_declare("Société", [], reglages) is None


def test_la_date_ne_vaut_que_pour_les_categories_jugees_sur_le_ca():
    reglages = v.TableauReglages.from_dict({"definitions_par_categorie": {
        "EC Salarié": {"ca_declaration_min": "2026-01-01"},
        "SEC": {"ca_declaration_min": "2026-01-01"},
        "EC Indépendant": {"ca_declaration_min": "pas une date"},
    }})
    assert "EC Salarié" not in reglages.definitions_par_categorie
    assert reglages.definitions_par_categorie["Société"]["ca_declaration_min"] == "2026-01-01"
    assert "EC Indépendant" not in reglages.definitions_par_categorie
