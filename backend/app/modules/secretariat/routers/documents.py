from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, has_any_permission, has_permission
from app.db.session import get_db
from app.models.user import User
from app.modules.secretariat.models import SecretariatApproval, SecretariatDocumentVersion
from app.modules.secretariat.schemas import (
    SecretariatApprovalOut,
    SecretariatDocumentCreate,
    SecretariatDocumentRead,
    SecretariatDocumentSummary,
    SecretariatDocumentSynthesis,
    SecretariatDocumentUpdate,
    SecretariatDocumentVersionCreate,
    SecretariatDocumentVersionRead,
)
from app.modules.secretariat.services.documents_agent import (
    add_document_version as documents_add_version,
    archive_document as documents_archive,
    create_document as documents_create,
    generate_synthesis as documents_generate_synthesis,
    get_document as documents_get,
    list_documents as documents_list,
    summarize_document as documents_summarize,
    submit_synthesis_for_approval as documents_submit_synthesis,
    update_document as documents_update,
)

router = APIRouter()


@router.get(
    "/documents",
    response_model=list[SecretariatDocumentRead],
    dependencies=[Depends(has_any_permission(["secretariat.view_documents", "secretariat.use_agent_documents"]))],
)
async def list_documents(
    document_type: str | None = Query(default=None),
    category: str | None = Query(default=None),
    status_value: str | None = Query(default=None, alias="status"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    author_id: UUID | None = Query(default=None),
    keyword: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list:
    return await documents_list(
        db,
        tenant_id,
        document_type=document_type,
        category=category,
        status_value=status_value,
        date_from=date_from,
        date_to=date_to,
        author_id=author_id,
        keyword=keyword,
    )


@router.post(
    "/documents",
    response_model=SecretariatDocumentRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_permission("secretariat.manage_documents"))],
)
async def create_document(
    payload: SecretariatDocumentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
):
    document = await documents_create(db, user, tenant_id, payload)
    await db.commit()
    return document


@router.get(
    "/documents/{document_id}",
    response_model=SecretariatDocumentRead,
    dependencies=[Depends(has_any_permission(["secretariat.view_documents", "secretariat.use_agent_documents"]))],
)
async def get_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
):
    return await documents_get(db, tenant_id, document_id)


@router.patch(
    "/documents/{document_id}",
    response_model=SecretariatDocumentRead,
    dependencies=[Depends(has_permission("secretariat.manage_documents"))],
)
async def update_document(
    document_id: int,
    payload: SecretariatDocumentUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
):
    document = await documents_update(db, user, tenant_id, document_id, payload)
    await db.commit()
    return document


@router.post(
    "/documents/{document_id}/archive",
    response_model=SecretariatDocumentRead,
    dependencies=[Depends(has_permission("secretariat.manage_documents"))],
)
async def archive_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
):
    document = await documents_archive(db, user, tenant_id, document_id)
    await db.commit()
    return document


@router.post(
    "/documents/{document_id}/versions",
    response_model=SecretariatDocumentVersionRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(has_permission("secretariat.manage_documents"))],
)
async def add_document_version(
    document_id: int,
    payload: SecretariatDocumentVersionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatDocumentVersionRead:
    version = await documents_add_version(db, user, tenant_id, document_id, payload)
    await db.commit()
    return version


@router.get(
    "/documents/{document_id}/versions",
    response_model=list[SecretariatDocumentVersionRead],
    dependencies=[Depends(has_any_permission(["secretariat.view_documents", "secretariat.use_agent_documents"]))],
)
async def list_document_versions(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[SecretariatDocumentVersion]:
    await documents_get(db, tenant_id, document_id)
    res = await db.execute(
        select(SecretariatDocumentVersion).where(
            SecretariatDocumentVersion.organisation_id == tenant_id,
            SecretariatDocumentVersion.document_id == document_id,
        ).order_by(SecretariatDocumentVersion.version_number.asc())
    )
    return list(res.scalars().all())


@router.post(
    "/documents/{document_id}/summarize",
    response_model=SecretariatDocumentSummary,
    dependencies=[Depends(has_permission("secretariat.generate_document_summary"))],
)
async def summarize_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatDocumentSummary:
    document = await documents_summarize(db, user, tenant_id, document_id)
    await db.commit()
    return SecretariatDocumentSummary(document_id=document.id, summary_text=document.summary_text or "", requires_human_validation=True)


@router.post(
    "/documents/{document_id}/generate-synthesis",
    response_model=SecretariatDocumentSynthesis,
    dependencies=[Depends(has_permission("secretariat.generate_document_summary"))],
)
async def generate_document_synthesis(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatDocumentSynthesis:
    document = await documents_generate_synthesis(db, user, tenant_id, document_id)
    await db.commit()
    return SecretariatDocumentSynthesis(document_id=document.id, synthesis_text=document.synthesis_text or "", requires_human_validation=True)


@router.post(
    "/documents/{document_id}/submit-synthesis-approval",
    response_model=SecretariatApprovalOut,
    dependencies=[Depends(has_permission("secretariat.submit_document_synthesis"))],
)
async def submit_document_synthesis_approval(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
) -> SecretariatApproval:
    approval = await documents_submit_synthesis(db, user, tenant_id, document_id)
    await db.commit()
    return approval
