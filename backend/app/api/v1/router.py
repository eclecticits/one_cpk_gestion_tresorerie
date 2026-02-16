from fastapi import APIRouter

from app.api.v1.endpoints import (
  admin,
  audit,
  audit_logs,
  ai,
  auth,
  budget,
  clotures,
  dashboard,
  debug,
  denominations,
  domain,
    encaissements,
    exports,
    experts,
    health,
    participants_transport,
    remboursements_transport,
    payments,
    permissions,
    requisition_approvers,
    requisitions,
    reports,
    sorties_fonds,
    sorties,
    settings,
    lignes_requisition,
    uploads,
)

api_router = APIRouter()

# Routes techniques
api_router.include_router(health.router, tags=["health"])
api_router.include_router(audit.router, tags=["audit"])
api_router.include_router(audit_logs.router, prefix="/audit-logs", tags=["audit-logs"])
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(permissions.router, prefix="/permissions", tags=["permissions"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(debug.router, prefix="/debug", tags=["debug"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(uploads.router, prefix="/admin", tags=["uploads"])

# Routes métier
api_router.include_router(experts.router, prefix="/experts-comptables", tags=["experts-comptables"])
api_router.include_router(payments.router, prefix="/payment-history", tags=["payment-history"])
api_router.include_router(settings.router, prefix="/print-settings", tags=["print-settings"])
api_router.include_router(domain.router, tags=["domain"])
api_router.include_router(encaissements.router, prefix="/encaissements", tags=["encaissements"])
api_router.include_router(exports.router, prefix="/exports", tags=["exports"])
api_router.include_router(requisitions.router, prefix="/requisitions", tags=["requisitions"])
api_router.include_router(sorties_fonds.router, prefix="/sorties-fonds", tags=["sorties-fonds"])
api_router.include_router(sorties.router, prefix="/sorties", tags=["sorties"])
api_router.include_router(budget.router, prefix="/budget", tags=["budget"])
api_router.include_router(clotures.router, prefix="/clotures", tags=["clotures"])
api_router.include_router(lignes_requisition.router, prefix="/lignes-requisition", tags=["lignes-requisition"])
api_router.include_router(requisition_approvers.router, prefix="/requisition-approvers", tags=["requisition-approvers"])
api_router.include_router(remboursements_transport.router, prefix="/remboursements-transport", tags=["remboursements-transport"])
api_router.include_router(participants_transport.router, prefix="/participants-transport", tags=["participants-transport"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(denominations.router, prefix="/denominations", tags=["denominations"])
