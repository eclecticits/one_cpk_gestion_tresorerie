from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.api.v1.endpoints.sorties_fonds import upload_sortie_pdf

router = APIRouter()


@router.post("/upload-official-pdf")
async def upload_sortie_pdf_alias(
    background_tasks: BackgroundTasks,
    sortie_id: str = Form(...),
    file: UploadFile = File(...),
    notify: bool = True,
    attachments: list[UploadFile] | None = File(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return await upload_sortie_pdf(
        sortie_id=sortie_id,
        background_tasks=background_tasks,
        file=file,
        notify=notify,
        attachments=attachments,
        db=db,
        user=user,
    )
