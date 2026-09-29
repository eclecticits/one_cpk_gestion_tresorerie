"""Qui peut modifier le budget.

Le routeur `/budget` n'exige que `menu_budget`, le droit d'ouvrir l'écran. Les
routes d'écriture ne vérifiaient rien de plus : un caissier à qui l'on n'avait
donné que la consultation du budget pouvait en modifier les postes, en créer,
en supprimer, et clôturer l'exercice. Chaque écriture exige désormais le droit
d'action correspondant (`treso.budget.create|update|delete|validate`), semé et
rétro-accordé par 20260822_treso_actions.

Les tests appellent la garde de chaque route avec un AuthUser dont les
permissions sont déjà résolues ; seul le refus relit le code du rôle, servi
par une base factice.
"""

import uuid

import pytest
from fastapi import HTTPException

from app.api.deps import has_permission
from app.api.v1.endpoints import budget
from app.core.auth_user import AuthUser

ECRITURES = [
    ("POST", "/exercices", "create"),
    ("POST", "/exercices/{annee}/initialiser", "create"),
    ("POST", "/lines", "create"),
    ("POST", "/postes", "create"),
    ("POST", "/postes/import", "create"),
    ("PUT", "/lines/{line_id}", "update"),
    ("PUT", "/postes/{poste_id}", "update"),
    ("PUT", "/postes/{poste_id}/poste-arrieres", "update"),
    ("DELETE", "/lines/{line_id}", "delete"),
    ("DELETE", "/postes/{poste_id}", "delete"),
    ("POST", "/lines/{line_id}/restore", "delete"),
    ("POST", "/postes/{poste_id}/restore", "delete"),
    ("POST", "/exercices/{annee}/cloture", "validate"),
    ("POST", "/exercices/{annee}/ouvrir", "validate"),
    ("POST", "/exercices/{annee}/reporter-creances", "validate"),
]


def _gardes(methode, chemin):
    route = next(
        r
        for r in budget.router.routes
        if getattr(r, "path", None) == chemin and methode in getattr(r, "methods", set())
    )
    return [d.call for d in route.dependant.dependencies if d.name is None]


class _BaseRoleCaissier:
    """Seule lecture faite par la garde en cas de refus : le code du rôle."""

    async def execute(self, _stmt):
        class _Resultat:
            def scalar_one_or_none(self):
                return "caissier"

        return _Resultat()


def _appelant(*permissions: str, role: str = "caissier") -> AuthUser:
    return AuthUser(
        id=uuid.uuid4(),
        role=role,
        role_id=4,
        organisation_id=1,
        active=True,
        permission_codes=frozenset(permissions),
        service_ids=(),
    )


def test_toute_route_d_ecriture_du_budget_porte_une_garde_fine():
    """Une route d'écriture ajoutée demain sans garde doit faire échouer ce test."""
    gardees = {(m, c) for m, c, _ in ECRITURES}
    for route in budget.router.routes:
        for methode in getattr(route, "methods", set()) - {"GET", "HEAD", "OPTIONS"}:
            if route.path.startswith("/commentaire") or route.path.startswith("/engagements"):
                # Commentaires : annotation, aucun montant touché. Réconciliation :
                # déjà réservée aux administrateurs dans la route.
                continue
            assert (methode, route.path) in gardees, f"{methode} {route.path} sans droit d'action"


@pytest.mark.asyncio
@pytest.mark.parametrize("methode,chemin,action", ECRITURES)
async def test_la_consultation_seule_ne_permet_pas_de_modifier(methode, chemin, action):
    [garde] = _gardes(methode, chemin)
    with pytest.raises(HTTPException) as erreur:
        await garde(user=_appelant("menu_budget"), db=_BaseRoleCaissier())
    assert erreur.value.status_code == 403
    assert f"treso.budget.{action}" in erreur.value.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("methode,chemin,action", ECRITURES)
async def test_le_droit_d_action_ouvre_la_route(methode, chemin, action):
    [garde] = _gardes(methode, chemin)
    user = _appelant("menu_budget", f"treso.budget.{action}")
    assert await garde(user=user, db=None) is user


@pytest.mark.asyncio
async def test_l_administrateur_garde_tous_les_droits():
    garde = has_permission("treso.budget.update")
    admin = _appelant(role="admin")
    assert await garde(user=admin, db=None) is admin
