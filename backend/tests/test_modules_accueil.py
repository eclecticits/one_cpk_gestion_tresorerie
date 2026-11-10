"""Ordre des modules à la connexion : toujours complet, sans clé inconnue."""

import pytest

from app.services.modules_accueil import MODULES_ORDRE_DEFAUT, normaliser_module_accueil, normaliser_priorite


def test_ordre_par_defaut_quand_rien_n_est_fixe():
    assert normaliser_priorite(None) == list(MODULES_ORDRE_DEFAUT)


def test_ordre_complete_dedoublonne_et_filtre():
    ordre = normaliser_priorite(["Tableau", "inconnu", "tableau", "rh"])
    # Les modules choisis d'abord, puis les oubliés dans l'ordre par défaut.
    assert ordre == ["tableau", "rh", "tresorerie", "comptabilite", "secretariat"]


def test_module_accueil_vide_suit_l_organisation():
    assert normaliser_module_accueil("") is None
    assert normaliser_module_accueil(None) is None
    assert normaliser_module_accueil(" Tableau ") == "tableau"


def test_module_accueil_inconnu_refuse():
    with pytest.raises(ValueError):
        normaliser_module_accueil("paie")
