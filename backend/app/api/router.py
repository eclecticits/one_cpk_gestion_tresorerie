from fastapi import APIRouter

from app.api.v1.router import api_router as v1

router = APIRouter()
router.include_router(v1, prefix="/api/v1")
