"""Métriques d'export publiées sur /metrics, dérivées de la base.

Les jobs sont produits par le conteneur worker et `/metrics` est servi par le
backend : deux processus. Des compteurs tenus en mémoire par le worker ne
seraient jamais visibles là où Prometheus vient les chercher — d'où une lecture
en base au moment du scrape, testée ici sans base grâce à une session factice.
"""

from __future__ import annotations

import pytest
from prometheus_client import REGISTRY
from sqlalchemy.exc import ProgrammingError

from app.core import export_metrics as em


class _Resultat:
    def __init__(self, lignes=None, scalaire=None):
        self._lignes = lignes or []
        self._scalaire = scalaire

    def all(self):
        return self._lignes

    def scalar_one_or_none(self):
        return self._scalaire

    def scalar_one(self):
        return self._scalaire


class _SessionFactice:
    """Rend les résultats dans l'ordre où `rafraichir` les demande."""

    def __init__(self, resultats):
        self._resultats = list(resultats)
        self.appels = 0

    async def execute(self, _requete):
        self.appels += 1
        return self._resultats.pop(0)


def _valeur(nom, **etiquettes):
    return REGISTRY.get_sample_value(nom, etiquettes)


@pytest.fixture(autouse=True)
def _cache_vide(monkeypatch):
    """Le cache de fraîcheur est un global de module : sans remise à zéro, le
    deuxième test de la session ne rafraîchirait rien."""
    monkeypatch.setattr(em, "_dernier_calcul", 0.0)


def _session_pleine():
    return _SessionFactice([
        _Resultat(lignes=[("budget", "DONE", 3), ("requisitions", "QUEUED", 2)]),
        _Resultat(scalaire=412.5),
        _Resultat(lignes=[("budget", 1.5, 2.0, 120.0)]),
        _Resultat(scalaire=2_048_000),
    ])


async def test_les_jauges_sont_alimentees_depuis_la_base():
    assert await em.rafraichir(_session_pleine()) is True

    assert _valeur("onec_export_jobs", type="budget", etat="DONE") == 3
    assert _valeur("onec_export_jobs", type="requisitions", etat="QUEUED") == 2
    assert _valeur("onec_export_attente_max_secondes") == 412.5
    assert _valeur("onec_export_duree_moyenne_secondes", type="budget") == 1.5
    assert _valeur("onec_export_duree_max_secondes", type="budget") == 2.0
    assert _valeur("onec_export_lignes_moyennes", type="budget") == 120.0
    assert _valeur("onec_export_artefacts_octets") == 2_048_000


async def test_un_couple_disparu_ne_reste_pas_fige():
    """Une jauge oubliée à douze jobs en file est exactement le genre de fausse
    alerte qui apprend à ignorer les alertes."""
    await em.rafraichir(_session_pleine())
    assert _valeur("onec_export_jobs", type="requisitions", etat="QUEUED") == 2

    em._dernier_calcul = 0.0
    await em.rafraichir(_SessionFactice([
        _Resultat(lignes=[("budget", "DONE", 3)]),
        _Resultat(scalaire=None),
        _Resultat(lignes=[]),
        _Resultat(scalaire=0),
    ]))
    # La série a disparu, elle ne vaut pas « 2 » indéfiniment.
    assert _valeur("onec_export_jobs", type="requisitions", etat="QUEUED") is None
    assert _valeur("onec_export_attente_max_secondes") == 0


async def test_le_cache_borne_la_frequence_des_agregats(monkeypatch):
    """Quatre workers gunicorn scrapés toutes les 15 s feraient sinon douze
    agrégats par cycle sur `export_jobs`."""
    monkeypatch.setattr(em.settings, "metrics_export_refresh_seconds", 3600)
    session = _session_pleine()
    assert await em.rafraichir(session) is True
    assert session.appels == 4

    # Deuxième appel immédiat : aucune requête de plus.
    session2 = _session_pleine()
    assert await em.rafraichir(session2) is False
    assert session2.appels == 0


class _Orig:
    def __init__(self, sqlstate):
        self.sqlstate = sqlstate


class _SessionEnErreur:
    def __init__(self, sqlstate):
        self._sqlstate = sqlstate

    async def execute(self, _requete):
        raise ProgrammingError("SELECT ...", {}, _Orig(self._sqlstate))


async def test_la_table_absente_ne_casse_pas_le_scrape():
    """Le backend peut démarrer avant que la migration ne soit appliquée ;
    /metrics ne doit pas répondre 500 pour autant."""
    assert await em.rafraichir(_SessionEnErreur("42P01")) is False


async def test_une_autre_erreur_sql_reste_bruyante():
    """Une colonne absente signale un modèle désynchronisé : la masquer ferait
    disparaître les métriques sans que personne ne sache pourquoi."""
    with pytest.raises(ProgrammingError):
        await em.rafraichir(_SessionEnErreur("42703"))
