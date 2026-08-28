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

from app.api.v1.endpoints.exports import _compter_lignes
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
