"""Qui peut écrire dans le budget.

Le routeur budget n'était gardé que par `menu_budget` (« Accès au menu ») : un
caissier à qui l'on ne laissait que la lecture modifiait pourtant les lignes,
parce que les cases « Créer », « Modifier », « Supprimer », « Valider » et
« Exporter » de l'écran Rôles n'étaient évaluées par aucune route.

Comme dans test_examen_permissions, les gardes sont appelées directement avec un
AuthUser dont les permissions sont déjà résolues. Avant de refuser,
`has_permission` relit le code du rôle (un rôle `admin` passe toujours) : une
session factice le lui donne, sans base.
"""

import inspect
import uuid

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import budget, exports
from app.core.auth_user import AuthUser

ECRITURES = [
    ("POST", "/exercices", "treso.budget.create"),
    ("POST", "/exercices/{annee}/initialiser", "treso.budget.create"),
    ("POST", "/lines", "treso.budget.create"),
    ("POST", "/postes", "treso.budget.create"),
    ("POST", "/postes/import", "treso.budget.create"),
    ("PUT", "/lines/{line_id}", "treso.budget.update"),
    ("PUT", "/postes/{poste_id}", "treso.budget.update"),
    ("PUT", "/postes/{poste_id}/poste-arrieres", "treso.budget.update"),
    ("DELETE", "/lines/{line_id}", "treso.budget.delete"),
    ("DELETE", "/postes/{poste_id}", "treso.budget.delete"),
    ("POST", "/lines/{line_id}/restore", "treso.budget.delete"),
    ("POST", "/postes/{poste_id}/restore", "treso.budget.delete"),
    ("POST", "/exercices/{annee}/cloture", "treso.budget.validate"),
    ("POST", "/exercices/{annee}/ouvrir", "treso.budget.validate"),
    ("POST", "/exercices/{annee}/reporter-creances", "treso.budget.validate"),
]

# Écritures qui ne modifient pas le budget lui-même, ou déjà réservées aux
# administrateurs dans leur corps.
HORS_DROITS_D_ACTION = {
    ("POST", "/engagements/reconcilier"),
    ("POST", "/commentaires"),
    ("PUT", "/commentaires/{commentaire_id}"),
    ("PUT", "/commentaire-general"),
}


def _route(router, methode, chemin):
    return next(
        r for r in router.routes if getattr(r, "path", None) == chemin and methode in getattr(r, "methods", ())
    )


def _codes_exiges(route) -> dict[str, object]:
    """Code de permission -> garde, pour chaque `has_permission` de la route."""
    gardes = {}
    for dep in route.dependencies:
        code = inspect.getclosurevars(dep.dependency).nonlocals.get("resolved_permission_code")
        if code is not None:
            gardes[code] = dep.dependency
    return gardes


class _SessionCaissier:
    """Répond à la seule requête du refus : le code du rôle."""

    async def execute(self, *args, **kwargs):
        return self

    def scalar_one_or_none(self):
        return "caissier"


def _appelant(*permissions: str) -> AuthUser:
    return AuthUser(
        id=uuid.uuid4(),
        role="caissier",
        role_id=5,
        organisation_id=1,
        active=True,
        permission_codes=frozenset(permissions),
        service_ids=(),
    )


@pytest.mark.parametrize("methode,chemin,code", ECRITURES)
def test_chaque_ecriture_exige_son_droit_d_action(methode, chemin, code):
    assert list(_codes_exiges(_route(budget.router, methode, chemin))) == [code]


def test_aucune_ecriture_n_echappe_aux_droits_d_action():
    """Une route d'écriture ajoutée sans garde redonnerait tous les droits à
    « Accès au menu » : elle doit figurer dans l'une des deux listes."""
    attendues = {(m, c) for m, c, _ in ECRITURES} | HORS_DROITS_D_ACTION
    for route in budget.router.routes:
        for methode in getattr(route, "methods", ()) or ():
            if methode in {"POST", "PUT", "PATCH", "DELETE"}:
                assert (methode, route.path) in attendues, (
                    f"{methode} {route.path} n'est gardée par aucun droit treso.budget.*"
                )


@pytest.mark.asyncio
@pytest.mark.parametrize("methode,chemin,code", ECRITURES)
async def test_l_acces_au_menu_seul_ne_suffit_plus(methode, chemin, code):
    garde = _codes_exiges(_route(budget.router, methode, chemin))[code]

    with pytest.raises(HTTPException) as erreur:
        await garde(user=_appelant("menu_budget"), db=_SessionCaissier())
    assert erreur.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("methode,chemin,code", ECRITURES)
async def test_la_case_de_l_action_suffit(methode, chemin, code):
    garde = _codes_exiges(_route(budget.router, methode, chemin))[code]
    user = _appelant("menu_budget", code)

    assert await garde(user=user, db=None) is user


@pytest.mark.asyncio
async def test_modifier_n_autorise_pas_a_supprimer():
    garde = _codes_exiges(_route(budget.router, "DELETE", "/lines/{line_id}"))["treso.budget.delete"]

    with pytest.raises(HTTPException) as erreur:
        await garde(user=_appelant("menu_budget", "treso.budget.update"), db=_SessionCaissier())
    assert erreur.value.status_code == 403


@pytest.mark.asyncio
async def test_l_export_du_budget_exige_son_droit():
    """Il n'avait aucune garde : tout utilisateur connecté exportait le budget."""
    gardes = _codes_exiges(_route(exports.router, "GET", "/budget"))
    assert list(gardes) == ["treso.budget.export"]

    with pytest.raises(HTTPException) as erreur:
        await gardes["treso.budget.export"](user=_appelant("menu_budget"), db=_SessionCaissier())
    assert erreur.value.status_code == 403


def test_les_jobs_d_export_budget_suivent_la_route():
    from app.api.v1.endpoints.export_jobs import PERMISSION_PAR_TYPE

    assert PERMISSION_PAR_TYPE["budget"] == "treso.budget.export"
