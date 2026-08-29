"""Qui porte les ordonnanceurs : le backend HTTP, ou le worker.

Un rapport hebdomadaire s'exécutait jusqu'ici DANS un worker gunicorn qui sert
des requêtes — le même défaut de nature que les exports, pour la même raison.
Le déplacement vers le conteneur worker est gouverné par un seul réglage, et
c'est précisément ce qui le rend risqué : deux processus lisent ce réglage, et
s'ils le lisent différemment, soit les rapports partent en double, soit — bien
pire parce que silencieux — ils ne partent plus du tout.

Ces tests verrouillent l'invariant : un seul hôte, et il est nommé.
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.utils.scheduler import (
    _hote_des_ordonnanceurs,
    get_monthly_report_status,
    get_weekly_report_status,
    stop_schedulers,
)


def test_le_defaut_ne_change_rien(monkeypatch):
    """Le déplacement doit être une décision, jamais un effet de bord de mise à
    jour : passer à true sans déployer le worker arrête les rapports."""
    assert settings.model_fields["schedulers_in_worker"].default is False


def test_l_hote_suit_le_reglage(monkeypatch):
    monkeypatch.setattr(settings, "schedulers_in_worker", False)
    assert _hote_des_ordonnanceurs() == "backend"
    monkeypatch.setattr(settings, "schedulers_in_worker", True)
    assert _hote_des_ordonnanceurs() == "exports-worker"


def test_le_statut_nomme_son_hote(monkeypatch):
    """`running` ne vaut que pour le processus qui répond. Quand les
    ordonnanceurs sont portés par le worker, l'API ne peut pas savoir s'ils
    tournent : elle doit le dire, pas répondre « arrêté »."""
    monkeypatch.setattr(settings, "schedulers_in_worker", True)
    for statut in (get_weekly_report_status(), get_monthly_report_status()):
        assert statut["host"] == "exports-worker"
        # Le contrat existant reste intact : les consommateurs (admin.py,
        # super_admin.py) lisent toujours les mêmes clés.
        assert {"enabled", "running", "timezone", "next_run", "schedule"} <= set(statut)


def test_l_arret_est_idempotent():
    """Appelé à l'arrêt d'un worker qui n'a jamais démarré d'ordonnanceur."""
    stop_schedulers()
    stop_schedulers()


def test_les_deux_hotes_lisent_le_meme_reglage():
    """L'invariant qui compte, et qu'aucun test unitaire ne peut observer
    autrement : le backend et le worker doivent se déterminer sur le MÊME
    réglage, et conclure à l'inverse l'un de l'autre. S'ils divergeaient, la
    panne serait muette — aucun rapport envoyé, aucune erreur nulle part.

    La lecture se fait sur le SOURCE et non par import : importer `app.main`
    crée le répertoire d'uploads et monte l'application, et importer
    `arq_worker` exige qu'arq soit installé. Deux dépendances d'environnement
    qu'un test de trois assertions n'a aucune raison d'imposer au reste de la
    suite.
    """
    racine = Path(__file__).resolve().parents[1]
    source_backend = (racine / "app/main.py").read_text(encoding="utf-8")
    source_worker = (racine / "app/workers/arq_worker.py").read_text(encoding="utf-8")

    assert "if settings.schedulers_in_worker:" in source_backend
    assert "if not settings.schedulers_in_worker:" in source_worker
