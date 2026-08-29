"""L'horodatage de génération porté par les classeurs exportés.

Un export asynchrone reflète les données au moment de sa GÉNÉRATION, pas du
clic : le job peut démarrer plusieurs minutes après la demande, et la
déduplication peut rendre un artefact produit une demi-heure plus tôt. Sans
cette mention, un classeur imprimé ne dit pas à quel instant ses chiffres
étaient vrais — sur des pièces comptables, c'est une ambiguïté que la bascule
asynchrone introduirait sans le dire.

Le prix de cette mention est qu'elle fait diverger deux classeurs par ailleurs
identiques. C'est pourquoi `observe/comparer_classeurs.py` la neutralise, et
pourquoi les deux fichiers sont testés ensemble ici.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook

from app.api.v1.endpoints.exports import (
    MENTION_GENERATION,
    _fuseau_documents,
    _write_banner,
    horodatage_generation,
)
from app.core.config import settings


def _comparateur():
    """Charge observe/comparer_classeurs.py, qui n'est pas un module du paquet."""
    chemin = (
        Path(__file__).resolve().parents[1]
        / "scripts/loadtest/observe/comparer_classeurs.py"
    )
    spec = importlib.util.spec_from_file_location("comparer_classeurs", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_le_fuseau_retombe_sur_celui_des_rapports(monkeypatch):
    """Un défaut à UTC aurait horodaté chaque document d'une heure d'écart avec
    l'horloge de celui qui le lit, sans que rien ne le signale."""
    monkeypatch.setattr(settings, "document_timezone", "")
    monkeypatch.setattr(settings, "weekly_report_timezone", "Africa/Kinshasa")
    assert _fuseau_documents().key == "Africa/Kinshasa"


def test_un_fuseau_explicite_l_emporte(monkeypatch):
    monkeypatch.setattr(settings, "document_timezone", "Europe/Paris")
    monkeypatch.setattr(settings, "weekly_report_timezone", "Africa/Kinshasa")
    assert _fuseau_documents().key == "Europe/Paris"


def test_un_fuseau_invalide_ne_fait_pas_echouer_l_export(monkeypatch):
    """Un réglage fautif doit dégrader l'horodatage, pas empêcher la production
    du document."""
    monkeypatch.setattr(settings, "document_timezone", "Mars/Olympus_Mons")
    assert _fuseau_documents().key == "UTC"


def test_l_horodatage_est_converti_dans_le_fuseau_local(monkeypatch):
    monkeypatch.setattr(settings, "document_timezone", "Africa/Kinshasa")
    # 23h30 UTC = 00h30 le lendemain à Kinshasa (UTC+1) : la date change, pas
    # seulement l'heure. C'est exactement le cas qu'un défaut à UTC aurait faussé.
    instant = datetime(2026, 8, 29, 23, 30, tzinfo=timezone.utc)
    rendu = horodatage_generation(instant)
    assert rendu.startswith(MENTION_GENERATION)
    assert "30/08/2026 à 00:30" in rendu


def test_le_bandeau_porte_l_horodatage_avec_ou_sans_sous_titre():
    """Les lignes 1 à 3 sont réservées au bandeau et l'en-tête des données
    commence en ligne 4 : l'horodatage rejoint le sous-titre plutôt que
    d'occuper une quatrième ligne, ce qui décalerait toutes les plages."""
    wb = Workbook()

    sans = wb.active
    _write_banner(sans, "Titre", None, 5, "Organisation X")
    assert MENTION_GENERATION in sans["A3"].value

    avec = wb.create_sheet("avec")
    _write_banner(avec, "Titre", "Période 2026", 5, "Organisation X")
    assert "Période 2026" in avec["A3"].value
    assert MENTION_GENERATION in avec["A3"].value

    # L'en-tête des données doit rester en ligne 4.
    assert sans["A4"].value is None


def test_le_comparateur_partage_la_meme_mention():
    """La mention est dupliquée à dessein — le script tourne depuis l'hôte, hors
    du conteneur, sans le paquet applicatif. Le prix de cette duplication est ce
    test : si l'une des deux bouge, la neutralisation cesse silencieusement
    d'opérer et l'outil déclare un écart à chaque comparaison."""
    assert _comparateur().MENTION_GENERATION == MENTION_GENERATION


def test_le_comparateur_neutralise_deux_horodatages_differents():
    comparateur = _comparateur()
    assert comparateur._est_horodatage("Généré le 29/08/2026 à 09:32 (WAT)") is True
    assert comparateur._est_horodatage("Période 2026") is False
    # Une cellule vide face à un horodatage doit rester un écart : c'est le
    # signe de deux versions du code, pas de deux instants.
    assert comparateur._est_horodatage(None) is False
