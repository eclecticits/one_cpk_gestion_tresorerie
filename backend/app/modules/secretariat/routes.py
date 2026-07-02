from __future__ import annotations

from fastapi import APIRouter

from app.modules.secretariat.routers.agenda import router as agenda_router
from app.modules.secretariat.routers.approvals import router as approvals_router
from app.modules.secretariat.routers.core import router as core_router
from app.modules.secretariat.routers.courrier import router as courrier_router
from app.modules.secretariat.routers.documents import router as documents_router
from app.modules.secretariat.routers.manager import router as manager_router
from app.modules.secretariat.routers.oauth import router as oauth_router
from app.modules.secretariat.routers.reunion import router as reunion_router
from app.modules.secretariat.tableau.router import router as tableau_router

router = APIRouter()
router.include_router(tableau_router)
router.include_router(core_router)
router.include_router(oauth_router)
router.include_router(courrier_router)
router.include_router(agenda_router)
router.include_router(documents_router)
router.include_router(reunion_router)
router.include_router(approvals_router)
router.include_router(manager_router)
