from fastapi import APIRouter, Depends
import logging

from app.api.v1.endpoints import (
    admin,
    ai,
    ai_providers,
    audit,
    audit_logs,
    auth,
    banques,
    projets_activites,
    budget,
    clotures,
    billing,
    dashboard,
    debug,
    denominations,
    dossiers_requisition,
    domain,
    clients,
    encaissements,
    experts,
    exports,
    health,
    hr,
    hr_attendance_agent,
    imports_history,
    lignes_requisition,
    online_payments,
    ordres_decaissement,
    organisation,
    participants_transport,
    payments,
    permissions,
    requisition_approvers,
    requisitions,
    retours_caisse,
    remboursements_transport,
    reports,
    reconciliation,
    services,
    settings,
    sorties,
    sorties_fonds,
    super_admin,
    secure_uploads,
    treasury,
    transferts,
    uploads,
    webhooks,
    onboarding,
    saas_console,
)
from app.core.config import settings as app_settings
from app.api.deps import has_permission, has_any_permission, require_module
from app.modules.secretariat import routes as secretariat
from app.modules.comptabilite.routers import ecritures as comptabilite
from app.modules.comptabilite.routers import parametrage as comptabilite_parametrage
from app.modules.comptabilite.routers import restitutions as comptabilite_restitutions
from app.modules.comptabilite.routers import etats as comptabilite_etats

logger = logging.getLogger("onec_cpk_api")

api_router = APIRouter()

# Routes techniques
api_router.include_router(health.router, tags=["health"])
api_router.include_router(audit.router, tags=["audit"])
api_router.include_router(audit_logs.router, prefix="/audit-logs", tags=["audit-logs"], dependencies=[Depends(has_permission("audit_logs"))])
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(permissions.router, prefix="/permissions", tags=["permissions"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(has_permission("dashboard"))])
if app_settings.enable_debug_endpoints and not app_settings.is_production():
    api_router.include_router(debug.router, prefix="/debug", tags=["debug"])
    logger.warning(
        "Endpoints /debug montés (ENV=%s, ENABLE_DEBUG_ENDPOINTS=true).",
        app_settings.env,
    )
else:
    logger.info("Endpoints /debug désactivés (ENV=%s).", app_settings.env)
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(uploads.router, prefix="/admin", tags=["uploads"])
api_router.include_router(secure_uploads.router, tags=["secure-uploads"])
api_router.include_router(organisation.router, prefix="/organisation", tags=["organisation"])
api_router.include_router(super_admin.router, prefix="/super-admin", tags=["super-admin"])
api_router.include_router(ai_providers.router, prefix="/ai-providers", tags=["ai-providers"])
api_router.include_router(onboarding.router, prefix="/onboarding", tags=["onboarding"])
api_router.include_router(saas_console.router, tags=["saas-console"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
api_router.include_router(imports_history.router, prefix="/imports-history", tags=["imports-history"], dependencies=[Depends(has_permission("historique_imports"))])

# Routes métier
api_router.include_router(experts.router, prefix="/experts-comptables", tags=["experts-comptables"])
api_router.include_router(payments.router, prefix="/payment-history", tags=["payment-history"])
api_router.include_router(online_payments.router, prefix="/online-payments", tags=["online-payments"])
api_router.include_router(billing.router, prefix="/billing", tags=["billing"])
api_router.include_router(settings.router, prefix="/print-settings", tags=["print-settings"])
api_router.include_router(domain.router, tags=["domain"])
api_router.include_router(encaissements.router, prefix="/encaissements", tags=["encaissements"])
api_router.include_router(
    clients.router,
    prefix="/clients",
    tags=["clients"],
    dependencies=[Depends(has_any_permission(["encaissements", "sorties_fonds", "requisitions"]))],
)
api_router.include_router(exports.router, prefix="/exports", tags=["exports"])
api_router.include_router(requisitions.router, prefix="/requisitions", tags=["requisitions"])
api_router.include_router(dossiers_requisition.router, prefix="/dossiers", tags=["dossiers"], dependencies=[Depends(has_any_permission(["validation_examens", "requisitions", "services"]))])
api_router.include_router(sorties_fonds.router, prefix="/sorties-fonds", tags=["sorties-fonds"], dependencies=[Depends(has_permission("sorties_fonds"))])
api_router.include_router(sorties.router, prefix="/sorties", tags=["sorties"], dependencies=[Depends(has_permission("sorties_fonds"))])
api_router.include_router(retours_caisse.router, prefix="/retours-caisse", tags=["retours-caisse"], dependencies=[Depends(has_permission("sorties_fonds"))])
api_router.include_router(
    ordres_decaissement.router,
    prefix="/ordres-decaissement",
    tags=["ordres-decaissement"],
    dependencies=[
        Depends(
            has_any_permission(
                ["requisitions", "sorties_fonds", "can_authorize_disbursement", "can_direct_disbursement"]
            )
        )
    ],
)
api_router.include_router(budget.router, prefix="/budget", tags=["budget"], dependencies=[Depends(has_permission("budget"))])
api_router.include_router(clotures.router, prefix="/clotures", tags=["clotures"])
api_router.include_router(lignes_requisition.router, prefix="/lignes-requisition", tags=["lignes-requisition"])
api_router.include_router(requisition_approvers.router, prefix="/requisition-approvers", tags=["requisition-approvers"])
api_router.include_router(remboursements_transport.router, prefix="/remboursements-transport", tags=["remboursements-transport"], dependencies=[Depends(has_any_permission(["remboursement_transport", "services"]))])
api_router.include_router(participants_transport.router, prefix="/participants-transport", tags=["participants-transport"], dependencies=[Depends(has_any_permission(["remboursement_transport", "services"]))])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"], dependencies=[Depends(has_permission("rapports"))])
api_router.include_router(reconciliation.router, prefix="/reconciliation", tags=["reconciliation"], dependencies=[Depends(has_any_permission(["encaissements", "sorties_fonds"]))])
api_router.include_router(treasury.router, prefix="/tresorerie", tags=["tresorerie"])
api_router.include_router(denominations.router, prefix="/denominations", tags=["denominations"], dependencies=[Depends(has_permission("denominations"))])
api_router.include_router(services.router, prefix="/services", tags=["services"])
api_router.include_router(hr_attendance_agent.router, prefix="/hr", tags=["hr-attendance-agent"])
api_router.include_router(hr.router, prefix="/hr", tags=["hr"], dependencies=[Depends(require_module("rh"))])
api_router.include_router(banques.router, tags=["banques"])
api_router.include_router(projets_activites.router, tags=["projets-activites"])
api_router.include_router(transferts.router, prefix="/transferts-internes", tags=["transferts-internes"])
api_router.include_router(secretariat.router, prefix="/secretariat", tags=["secretariat"], dependencies=[Depends(require_module("secretariat"))])
api_router.include_router(comptabilite.router, prefix="/comptabilite", tags=["comptabilite"], dependencies=[Depends(require_module("comptabilite"))])
api_router.include_router(comptabilite_parametrage.router, prefix="/comptabilite", tags=["comptabilite"], dependencies=[Depends(require_module("comptabilite"))])
api_router.include_router(comptabilite_restitutions.router, prefix="/comptabilite", tags=["comptabilite"], dependencies=[Depends(require_module("comptabilite"))])
api_router.include_router(comptabilite_etats.router, prefix="/comptabilite", tags=["comptabilite"], dependencies=[Depends(require_module("comptabilite"))])
