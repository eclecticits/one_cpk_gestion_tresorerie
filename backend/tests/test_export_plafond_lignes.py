"""Le plafond de lignes des exports : refuser tôt plutôt que tenir un worker.

Un export coûte du temps CPU par ligne, et l'arbitre gunicorn tue le worker à
120 s en emportant les requêtes de ses voisins — l'UvicornWorker est partagé.
Au-delà du plafond, l'export ne peut pas aboutir : le refuser à la première
seconde est la seule issue qui rende la main à l'utilisateur avec une raison.

Ces tests n'ont besoin d'aucune base : `_compter_lignes` ne fait qu'un agrégat,
et une session factice suffit à vérifier sa décision comme le SQL qu'il produit.
"""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.api.v1.endpoints.exports import (
    BasculeAsynchroneRequise,
    _compter_lignes,
    _seuil_bascule,
)
from app.core.config import settings
from app.models.requisition import Requisition
from app.models.service import Service


class _ResultatFactice:
    def __init__(self, total: int) -> None:
        self._total = total

    def scalar_one(self) -> int:
        return self._total


class _SessionFactice:
    """Session minimale : retient les requêtes reçues, rend un compte fixe."""

    def __init__(self, total: int) -> None:
        self.total = total
        self.requetes: list = []

    async def execute(self, requete):
        self.requetes.append(requete)
        return _ResultatFactice(self.total)


def _requete_export():
    """Forme réelle d'une requête d'export : jointure externe, filtre, tri."""
    return (
        select(Requisition, Service)
        .outerjoin(Service, Requisition.service_id == Service.id)
        .where(Requisition.organisation_id == uuid.uuid4())
        .order_by(Requisition.created_at.desc())
    )


async def test_sous_le_plafond_l_export_passe(monkeypatch):
    monkeypatch.setattr(settings, "export_max_rows", 1000)
    db = _SessionFactice(999)

    assert await _compter_lignes(db, _requete_export(), export="requisitions") == 999


async def test_le_plafond_lui_meme_est_accepte(monkeypatch):
    """Le refus est strict : le plafond est la dernière valeur servie."""
    monkeypatch.setattr(settings, "export_max_rows", 1000)
    db = _SessionFactice(1000)

    assert await _compter_lignes(db, _requete_export(), export="requisitions") == 1000


async def test_au_dela_du_plafond_refus_413_exploitable(monkeypatch):
    """Un refus qui ne dit pas quoi faire pousse l'utilisateur à recliquer."""
    monkeypatch.setattr(settings, "export_max_rows", 1000)
    db = _SessionFactice(60123)

    with pytest.raises(HTTPException) as echec:
        await _compter_lignes(db, _requete_export(), export="requisitions")

    assert echec.value.status_code == 413
    detail = echec.value.detail
    assert "60 123" in detail  # ce qu'il a demandé
    assert "1 000" in detail  # la limite
    assert "filtres" in detail  # et l'action qui débloque


async def test_plafond_a_zero_desactive_le_refus(monkeypatch):
    """EXPORT_MAX_ROWS=0 : une soupape d'exploitation, sans redéploiement."""
    monkeypatch.setattr(settings, "export_max_rows", 0)
    db = _SessionFactice(10_000_000)

    assert await _compter_lignes(db, _requete_export(), export="requisitions") == 10_000_000


async def test_le_comptage_est_un_agregat_qui_conserve_les_filtres(monkeypatch):
    """Ce que le comptage doit coûter, et ce qu'il ne doit pas perdre."""
    monkeypatch.setattr(settings, "export_max_rows", 1000)
    db = _SessionFactice(1)

    await _compter_lignes(db, _requete_export(), export="requisitions")

    sql = " ".join(str(db.requetes[0].compile(dialect=postgresql.dialect())).split()).lower()
    assert sql.startswith("select count(*)")
    # Trier des dizaines de milliers de lignes ne change aucun compte.
    assert "order by" not in sql
    # Le filtre d'organisation de l'export est conservé : le compte est celui du
    # tenant, pas celui de la base. Les `with_loader_criteria` du listener ne
    # s'appliquent pas à une sous-requête Core (cf. docstring de
    # `_compter_lignes`) : ce filtre explicite est ce qui tient le comptage.
    assert "requisitions.organisation_id =" in sql
    # La jointure de l'export est conservée : un COUNT sur une autre forme de
    # requête ne compterait pas les mêmes lignes que celles qui seront écrites.
    assert "left outer join services" in sql


# ── Seuil de bascule asynchrone (phase 2) ────────────────────────────────────


def test_un_type_ferme_n_a_pas_de_seuil(monkeypatch):
    """Drapeau fermé = aucune bascule possible, quel que soit le volume."""
    monkeypatch.setattr(settings, "export_async_types", "")
    assert _seuil_bascule("requisitions") is None


def test_un_type_ouvert_prend_le_seuil_configure(monkeypatch):
    monkeypatch.setattr(settings, "export_async_types", "requisitions")
    monkeypatch.setattr(settings, "export_async_row_threshold", 5000)
    assert _seuil_bascule("requisitions") == 5000
    # Un autre type ouvert nulle part reste synchrone.
    assert _seuil_bascule("encaissements") is None


def test_seuil_a_zero_fait_tout_basculer(monkeypatch):
    """0 et None ne veulent pas dire la même chose : 0 est un type ouvert dont
    tout bascule, et c'est le réglage qui permet de valider la chaîne sur un
    petit export."""
    monkeypatch.setattr(settings, "export_async_types", "budget")
    monkeypatch.setattr(settings, "export_async_row_threshold", 0)
    assert _seuil_bascule("budget") == 0


async def test_sous_le_seuil_le_chemin_direct_est_conserve(monkeypatch):
    """Un export de 500 lignes doit rester instantané : l'asynchrone y serait
    une régression d'usage."""
    monkeypatch.setattr(settings, "export_max_rows", 60000)
    db = _SessionFactice(500)
    assert await _compter_lignes(db, _requete_export(), export="requisitions", seuil_bascule=5000) == 500


async def test_au_dessus_du_seuil_la_bascule_est_demandee(monkeypatch):
    monkeypatch.setattr(settings, "export_max_rows", 60000)
    db = _SessionFactice(5001)
    with pytest.raises(BasculeAsynchroneRequise) as bascule:
        await _compter_lignes(db, _requete_export(), export="requisitions", seuil_bascule=5000)
    # Le nombre voyage avec le signal : il est écrit sur le job à la création,
    # pour que l'écran d'attente sache déjà combien de lignes sont en jeu.
    assert bascule.value.total == 5001


async def test_le_plafond_prime_sur_la_bascule(monkeypatch):
    """L'ordre des deux contrôles est ce qui rend les réglages cohérents : au-delà
    du plafond, refus immédiat à la soumission — et non un 202 suivi d'un échec
    du worker vingt minutes plus tard, pour la raison qu'on connaissait déjà."""
    monkeypatch.setattr(settings, "export_max_rows", 60000)
    db = _SessionFactice(60001)
    with pytest.raises(HTTPException) as echec:
        await _compter_lignes(db, _requete_export(), export="requisitions", seuil_bascule=5000)
    assert echec.value.status_code == 413


async def test_le_worker_ne_peut_pas_declencher_de_bascule(monkeypatch):
    """Sans seuil transmis, aucune bascule : c'est ce qui empêche un job de se
    remettre en file lui-même, indéfiniment. Le volume choisi dépasse largement
    le seuil par défaut, mais reste sous le plafond — c'est bien l'absence de
    seuil qui est testée ici, pas le plafond."""
    monkeypatch.setattr(settings, "export_max_rows", 60000)
    db = _SessionFactice(59_000)
    assert await _compter_lignes(db, _requete_export(), export="requisitions") == 59_000


def test_le_seuil_reste_sous_le_plafond():
    """Un seuil au-dessus du plafond rendrait la bascule inatteignable : tout
    export assez gros pour basculer serait d'abord refusé en 413."""
    assert settings.export_async_row_threshold < settings.export_max_rows
