"""Les cases de l'écran Rôles gardent réellement leur action.

La migration 20260822_treso_actions a semé les droits d'action `treso.*` et les
a rétro-accordés, en annonçant une seconde phase : poser les gardes route par
route. Elle n'avait été faite pour aucun module — décocher « Supprimer une
réquisition » ou « Créer un encaissement » ne retirait rien, et
`PUT /requisitions/{id}` n'exigeait même aucune permission.

Même technique que test_budget_permissions : la garde est appelée avec un
AuthUser aux permissions résolues, et une session factice qui ne sert qu'à
relire le code du rôle au moment du refus.
"""

import inspect
import uuid

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import (
    audit_logs,
    clotures,
    dossiers_requisition,
    encaissements,
    exports,
    hr,
    remboursements_transport,
    requisitions,
    services,
    sorties_fonds,
)
from app.core.auth_user import AuthUser

GARDES = [
    (encaissements.router, "POST", "", "treso.encaissements.create"),
    (encaissements.router, "POST", "/proformas", "treso.encaissements.create"),
    (encaissements.router, "POST", "/{encaissement_id}/convertir", "treso.encaissements.create"),
    (encaissements.router, "POST", "/{encaissement_id}/soft-delete", "treso.encaissements.delete"),
    (encaissements.router, "POST", "/{encaissement_id}/restore", "treso.encaissements.delete"),
    (requisitions.router, "PUT", "/{requisition_id}", "treso.requisitions.update"),
    (requisitions.router, "POST", "/{requisition_id}/soft-delete", "treso.requisitions.delete"),
    (requisitions.router, "POST", "/{requisition_id}/restore", "treso.requisitions.delete"),
    (sorties_fonds.router, "POST", "", "treso.sorties_fonds.create"),
    (sorties_fonds.router, "POST", "/drafts", "treso.sorties_fonds.create"),
    (sorties_fonds.router, "PUT", "/{sortie_id}/brouillon", "treso.sorties_fonds.create"),
    (dossiers_requisition.router, "POST", "", "treso.validation_examens.create"),
    (dossiers_requisition.router, "PATCH", "/{dossier_id}", "treso.validation_examens.update"),
    (dossiers_requisition.router, "POST", "/{dossier_id}/submit-examen", "treso.validation_examens.update"),
    (dossiers_requisition.router, "POST", "/{dossier_id}/add-requisitions", "treso.validation_examens.update"),
    (dossiers_requisition.router, "POST", "/{dossier_id}/remove-requisitions", "treso.validation_examens.update"),
    (dossiers_requisition.router, "DELETE", "/{dossier_id}", "treso.validation_examens.delete"),
    (remboursements_transport.router, "POST", "", "treso.remboursement_transport.create"),
    (services.router, "POST", "", "treso.services.create"),
    (services.router, "PATCH", "/{service_id}", "treso.services.update"),
    (clotures.router, "GET", "/export-xlsx", "treso.cloture_caisse.export"),
    (audit_logs.router, "GET", "/export", "treso.audit_logs.export"),
    (audit_logs.router, "GET", "/export-xlsx", "treso.audit_logs.export"),
    (exports.router, "GET", "/encaissements", "treso.encaissements.export"),
    (exports.router, "GET", "/sorties-fonds", "treso.sorties_fonds.export"),
    (exports.router, "GET", "/requisitions", "treso.requisitions.export"),
    (hr.router, "POST", "/payroll-entries/{entry_id}/generate-slips", "rh.payslips.generate"),
]


class _SessionSansRoleAdmin:
    """Répond à la seule requête du refus : le code du rôle."""

    async def execute(self, *args, **kwargs):
        return self

    def scalar_one_or_none(self):
        return "caissier"


def _route(router, methode, chemin):
    return next(
        r for r in router.routes if getattr(r, "path", None) == chemin and methode in getattr(r, "methods", ())
    )


def _gardes(route) -> dict[str, object]:
    """Code exigé -> garde, qu'elle soit posée sur la route ou sur un paramètre."""
    gardes = {}
    for dep in route.dependant.dependencies:
        if dep.call is None:
            continue
        code = inspect.getclosurevars(dep.call).nonlocals.get("resolved_permission_code")
        if code is not None:
            gardes[code] = dep.call
    return gardes


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


@pytest.mark.parametrize("router,methode,chemin,code", GARDES, ids=[f"{m} {c or '/'} {code}" for _, m, c, code in GARDES])
def test_la_route_exige_la_case_de_son_action(router, methode, chemin, code):
    assert code in _gardes(_route(router, methode, chemin))


@pytest.mark.asyncio
@pytest.mark.parametrize("router,methode,chemin,code", GARDES, ids=[f"{m} {c or '/'} {code}" for _, m, c, code in GARDES])
async def test_la_case_decochee_refuse(router, methode, chemin, code):
    """Tous les accès au menu, mais pas la case de l'action : 403."""
    garde = _gardes(_route(router, methode, chemin))[code]
    menus = ("menu_encaissements", "menu_requisitions", "menu_sorties_fonds", "menu_validation_examens",
             "menu_remboursement_transport", "menu_services", "menu_budget", "menu_cloture_caisse",
             "menu_audit_logs", "can_create_requisition", "can_execute_payment", "rh.payroll.prepare")

    with pytest.raises(HTTPException) as erreur:
        await garde(user=_appelant(*menus), db=_SessionSansRoleAdmin())
    assert erreur.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("router,methode,chemin,code", GARDES, ids=[f"{m} {c or '/'} {code}" for _, m, c, code in GARDES])
async def test_la_case_cochee_suffit(router, methode, chemin, code):
    garde = _gardes(_route(router, methode, chemin))[code]
    user = _appelant(code)

    assert await garde(user=user, db=None) is user


def test_les_jobs_d_export_suivent_leur_route():
    """Un job d'export se consulte avec le même droit que l'export synchrone :
    sinon la case « Exporter » décochée se contourne par la liste des jobs."""
    from app.api.v1.endpoints.export_jobs import PERMISSION_PAR_TYPE

    for type_export, code in PERMISSION_PAR_TYPE.items():
        assert code in _gardes(_route(exports.router, "GET", f"/{type_export}")), type_export


def test_la_creation_d_une_sortie_garde_le_droit_de_payer():
    """Le droit d'action s'ajoute au droit de payer, il ne le remplace pas."""
    gardes = _gardes(_route(sorties_fonds.router, "POST", ""))
    assert {"can_execute_payment", "treso.sorties_fonds.create"} <= set(gardes)
