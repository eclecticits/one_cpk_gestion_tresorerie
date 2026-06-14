from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, inspect, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.modules.secretariat.models import SecretariatDocument, SecretariatDocumentVersion
from app.modules.secretariat.schemas import SecretariatDocumentVersionCreate
from app.modules.secretariat.services.ai_service import generate_document_synthesis as ai_generate_document_synthesis
from app.modules.secretariat.services.ai_service import summarize_document as ai_summarize_document
from app.modules.secretariat.services.audit import record_secretariat_audit, sanitize_secretariat_metadata


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_keywords(keywords: list[str] | None) -> list[str] | None:
    if keywords is None:
        return None
    cleaned = [keyword.strip() for keyword in keywords if keyword and keyword.strip()]
    return cleaned or None



def _user_id(user: User):
    identity = inspect(user).identity
    if identity and identity[0] is not None:
        return identity[0]
    raise RuntimeError("User identity is not available")

async def _get_document(db: AsyncSession, organisation_id: int, document_id: int) -> SecretariatDocument:
    document = await db.get(SecretariatDocument, document_id)
    if document is not None and document.organisation_id != organisation_id:
        document = None
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document introuvable")
    return document


async def _latest_version_number(db: AsyncSession, organisation_id: int, document_id: int) -> int:
    res = await db.execute(
        select(func.coalesce(func.max(SecretariatDocumentVersion.version_number), 0)).where(
            SecretariatDocumentVersion.organisation_id == organisation_id,
            SecretariatDocumentVersion.document_id == document_id,
        )
    )
    return int(res.scalar_one() or 0)


def _document_snapshot(document: SecretariatDocument) -> dict:
    return {
        "document_type": document.document_type,
        "category": document.category,
        "status": document.status,
        "source": document.source,
        "file_name": document.file_name,
        "mime_type": document.mime_type,
        "file_size": document.file_size,
        "has_file": bool(document.has_file),
        "keywords_count": len(document.keywords_json or []),
        "has_extracted_text": bool(document.extracted_text),
        "has_summary": bool(document.summary_text),
        "has_synthesis": bool(document.synthesis_text),
    }


async def create_document(db: AsyncSession, user: User, organisation_id: int, payload) -> SecretariatDocument:
    document = SecretariatDocument(
        organisation_id=organisation_id,
        created_by_user_id=_user_id(user),
        title=payload.title,
        document_type=payload.document_type,
        category=payload.category,
        status="draft",
        source=payload.source,
        description=payload.description,
        keywords_json=_clean_keywords(payload.keywords_json),
        file_name=payload.file_name,
        mime_type=payload.mime_type,
        file_size=payload.file_size,
        extracted_text=payload.extracted_text,
        metadata_json=sanitize_secretariat_metadata(payload.metadata_json),
    )
    db.add(document)
    await db.flush()
    if document.file_path or document.file_name or document.extracted_text:
        version = SecretariatDocumentVersion(
            organisation_id=organisation_id,
            document_id=document.id,
            version_number=1,
            file_name=document.file_name,
            extracted_text=document.extracted_text,
            summary_text=document.summary_text,
            synthesis_text=document.synthesis_text,
            created_by_user_id=_user_id(user),
        )
        db.add(version)
        await db.flush()
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=_user_id(user),
        action="document_created",
        agent_type="documents",
        target_type="secretariat_document",
        target_id=document.id,
        metadata_json=_document_snapshot(document),
    )
    return document


async def update_document(db: AsyncSession, user: User, organisation_id: int, document_id: int, payload) -> SecretariatDocument:
    document = await _get_document(db, organisation_id, document_id)
    if document.status in {"archived", "pending_approval", "approved"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ce document ne peut plus être modifié via la mise à jour générique.")
    changes = payload.model_dump(exclude_unset=True)
    if "keywords_json" in changes:
        changes["keywords_json"] = _clean_keywords(changes["keywords_json"])
    if "metadata_json" in changes:
        changes["metadata_json"] = sanitize_secretariat_metadata(changes["metadata_json"])
    for field, value in changes.items():
        setattr(document, field, value)
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=_user_id(user),
        action="document_updated",
        agent_type="documents",
        target_type="secretariat_document",
        target_id=document.id,
        metadata_json={"fields": sorted(changes.keys()), **_document_snapshot(document)},
    )
    return document


async def list_documents(
    db: AsyncSession,
    organisation_id: int,
    *,
    document_type: str | None = None,
    category: str | None = None,
    status_value: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    author_id: UUID | None = None,
    keyword: str | None = None,
) -> list[SecretariatDocument]:
    stmt = select(SecretariatDocument).where(SecretariatDocument.organisation_id == organisation_id)
    if document_type:
        stmt = stmt.where(SecretariatDocument.document_type == document_type)
    if category:
        stmt = stmt.where(SecretariatDocument.category == category)
    if status_value:
        stmt = stmt.where(SecretariatDocument.status == status_value)
    if date_from:
        stmt = stmt.where(SecretariatDocument.created_at >= date_from)
    if date_to:
        stmt = stmt.where(SecretariatDocument.created_at < date_to)
    if author_id:
        stmt = stmt.where(SecretariatDocument.created_by_user_id == author_id)
    if keyword:
        stmt = stmt.where(
            or_(
                SecretariatDocument.title.ilike(f"%{keyword}%"),
                SecretariatDocument.description.ilike(f"%{keyword}%"),
                SecretariatDocument.source.ilike(f"%{keyword}%"),
                SecretariatDocument.extracted_text.ilike(f"%{keyword}%"),
                SecretariatDocument.keywords_json.contains([keyword]),
            )
        )
    stmt = stmt.order_by(SecretariatDocument.created_at.desc())
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def get_document(db: AsyncSession, organisation_id: int, document_id: int) -> SecretariatDocument:
    return await _get_document(db, organisation_id, document_id)


async def archive_document(db: AsyncSession, user: User, organisation_id: int, document_id: int) -> SecretariatDocument:
    document = await _get_document(db, organisation_id, document_id)
    if document.status == "archived":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Le document est déjà archivé.")
    document.status = "archived"
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=_user_id(user),
        action="document_archived",
        agent_type="documents",
        target_type="secretariat_document",
        target_id=document.id,
        metadata_json=_document_snapshot(document),
    )
    return document


async def add_document_version(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    document_id: int,
    payload: SecretariatDocumentVersionCreate,
) -> SecretariatDocumentVersion:
    document = await _get_document(db, organisation_id, document_id)
    if document.status in {"archived", "pending_approval", "approved"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ce document ne peut plus recevoir de nouvelle version.")
    next_version = await _latest_version_number(db, organisation_id, document.id) + 1
    version = SecretariatDocumentVersion(
        organisation_id=organisation_id,
        document_id=document.id,
        version_number=next_version,
        file_name=payload.file_name,
        extracted_text=payload.extracted_text,
        summary_text=payload.summary_text,
        synthesis_text=payload.synthesis_text,
        created_by_user_id=_user_id(user),
    )
    db.add(version)
    if payload.file_name is not None:
        document.file_name = payload.file_name
    if payload.extracted_text is not None:
        document.extracted_text = payload.extracted_text
    if payload.summary_text is not None:
        document.summary_text = payload.summary_text
    if payload.synthesis_text is not None:
        document.synthesis_text = payload.synthesis_text
    await db.flush()
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=_user_id(user),
        action="document_version_added",
        agent_type="documents",
        target_type="secretariat_document",
        target_id=document.id,
        metadata_json={"version_number": version.version_number, **_document_snapshot(document)},
    )
    return version


async def summarize_document(db: AsyncSession, user: User, organisation_id: int, document_id: int) -> SecretariatDocument:
    document = await _get_document(db, organisation_id, document_id)
    if document.status in {"archived", "pending_approval", "approved"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ce document archivé, en attente de validation ou approuvé ne peut pas être résumé.")
    source_text = (document.extracted_text or document.description or "").strip()
    if not source_text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le document ne contient pas de texte résumable.")
    summary = await ai_summarize_document(
        {
            "title": document.title,
            "document_type": document.document_type,
            "category": document.category,
            "source": document.source,
            "description": document.description,
            "keywords_json": document.keywords_json or [],
            "extracted_text": source_text,
        },
        db=db,
        organisation_id=organisation_id,
    )
    document.summary_text = summary.get("summary_text") or ""
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=_user_id(user),
        action="document_summarized",
        agent_type="documents",
        target_type="secretariat_document",
        target_id=document.id,
        metadata_json={
            "document_type": document.document_type,
            "status": document.status,
            "summary_length": len(document.summary_text or ""),
            "key_points_count": len(summary.get("key_points") or []),
            "requires_human_validation": bool(summary.get("requires_human_validation", True)),
        },
    )
    return document


async def generate_synthesis(db: AsyncSession, user: User, organisation_id: int, document_id: int) -> SecretariatDocument:
    document = await _get_document(db, organisation_id, document_id)
    if document.status in {"archived", "pending_approval", "approved"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ce document archivé, en attente de validation ou approuvé ne peut pas être synthétisé.")
    source_text = (document.summary_text or document.extracted_text or document.description or "").strip()
    if not source_text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le document ne contient pas de texte suffisant pour une synthèse.")
    synthesis = await ai_generate_document_synthesis(
        {
            "title": document.title,
            "document_type": document.document_type,
            "category": document.category,
            "source": document.source,
            "description": document.description,
            "keywords_json": document.keywords_json or [],
            "extracted_text": source_text,
        },
        db=db,
        organisation_id=organisation_id,
    )
    synthesis_lines = [
        f"Objet: {synthesis.get('object') or ''}",
        f"Contexte: {synthesis.get('context') or ''}",
        f"Points clés: {'; '.join(synthesis.get('key_points') or [])}",
        f"Décisions ou demandes: {'; '.join(synthesis.get('decisions_or_requests') or [])}",
        f"Actions à suivre: {'; '.join(synthesis.get('actions_to_follow') or [])}",
        f"Risques ou observations: {'; '.join(synthesis.get('risks_or_observations') or [])}",
        f"Proposition de suite: {'; '.join(synthesis.get('proposed_next_steps') or [])}",
        f"Informations manquantes: {'; '.join(synthesis.get('missing_information') or [])}",
    ]
    document.synthesis_text = "\n".join(synthesis_lines).strip()
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=_user_id(user),
        action="document_synthesis_generated",
        agent_type="documents",
        target_type="secretariat_document",
        target_id=document.id,
        metadata_json={
            "document_type": document.document_type,
            "status": document.status,
            "object_length": len((synthesis.get("object") or "")),
            "key_points_count": len(synthesis.get("key_points") or []),
            "requires_human_validation": bool(synthesis.get("requires_human_validation", True)),
        },
    )
    return document


async def submit_synthesis_for_approval(db: AsyncSession, user: User, organisation_id: int, document_id: int):
    from app.modules.secretariat.schemas import SecretariatApprovalCreate
    from app.modules.secretariat.services.approval_service import create_approval_request

    document = await _get_document(db, organisation_id, document_id)
    if document.status in {"archived", "pending_approval", "approved"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ce document archivé, en attente de validation ou approuvé ne peut pas être soumis à validation.")
    if not document.synthesis_text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La fiche synthèse doit être générée avant soumission.")
    approval = await create_approval_request(
        db,
        user,
        organisation_id,
        SecretariatApprovalCreate(
            agent_type="documents",
            approval_type="document_synthesis_validation",
            target_type="secretariat_document",
            target_id=str(document.id),
            title=f"Valider la fiche synthèse : {document.title}",
            description="Validation humaine requise avant validation finale du document.",
            priority="normal",
            metadata_json={"document_id": document.id, "document_type": document.document_type},
        ),
    )
    document.status = "pending_approval"
    await record_secretariat_audit(
        db,
        organisation_id=organisation_id,
        user_id=_user_id(user),
        action="document_synthesis_submitted_for_approval",
        agent_type="documents",
        target_type="secretariat_document",
        target_id=document.id,
        metadata_json={"approval_id": approval.id, "document_type": document.document_type, "status": document.status},
    )
    return approval
