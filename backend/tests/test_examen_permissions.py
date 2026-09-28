"""Qui peut terminer ou rejeter un examen.

L'écran des permissions propose « Dossiers d'examen → Valider un dossier
d'examen » (`treso.validation_examens.validate`). Les endpoints d'examen
n'exigeaient pourtant que `can_verify_technical` (« Validation → Avis
technique ») : un secrétaire exécutif à qui l'on avait coché la première case
recevait un 403 en validant une réquisition en examen.

Les tests attrapent la dépendance `user` de chaque route et l'appellent avec un
AuthUser dont les permissions sont déjà résolues : aucune base n'est touchée.
"""

import uuid

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import dossiers_requisition, requisitions
from app.core.auth_user import AuthUser

ROUTES_EXAMEN = [
    (requisitions.router, "/{requisition_id}/validate-examen"),
    (requisitions.router, "/{requisition_id}/reject-examen"),
    (dossiers_requisition.router, "/{dossier_id}/validate-examen"),
    (dossiers_requisition.router, "/{dossier_id}/reject-examen"),
]


def _dependance_user(router, chemin):
    route = next(r for r in router.routes if getattr(r, "path", None) == chemin)
    return next(d.call for d in route.dependant.dependencies if d.name == "user")


def _appelant(*permissions: str) -> AuthUser:
    return AuthUser(
        id=uuid.uuid4(),
        role="secretaire_executif",
        role_id=8,
        organisation_id=1,
        active=True,
        permission_codes=frozenset(permissions),
        service_ids=(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("router,chemin", ROUTES_EXAMEN)
async def test_la_case_valider_un_dossier_d_examen_suffit(router, chemin):
    dep = _dependance_user(router, chemin)
    user = _appelant("menu_validation_examens", "treso.validation_examens.validate")

    assert await dep(user=user, db=None) is user


@pytest.mark.asyncio
@pytest.mark.parametrize("router,chemin", ROUTES_EXAMEN)
async def test_l_avis_technique_ouvre_toujours_l_examen(router, chemin):
    dep = _dependance_user(router, chemin)
    user = _appelant("can_verify_technical")

    assert await dep(user=user, db=None) is user


@pytest.mark.asyncio
@pytest.mark.parametrize("router,chemin", ROUTES_EXAMEN)
async def test_l_acces_au_menu_seul_ne_suffit_pas(router, chemin):
    dep = _dependance_user(router, chemin)
    user = _appelant("menu_validation_examens", "treso.validation_examens.update")

    with pytest.raises(HTTPException) as erreur:
        await dep(user=user, db=None)
    assert erreur.value.status_code == 403
