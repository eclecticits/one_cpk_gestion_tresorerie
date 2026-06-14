"""
Endpoints Super Admin — Configuration des fournisseurs IA.
Seuls les utilisateurs avec le rôle super_admin peuvent accéder à ces routes.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_super_admin
from app.core.encryption import encrypt_secret, generate_encryption_key
from app.models.ai_provider_config import AIProviderConfig
from app.models.user import User
from app.schemas.ai_provider import (
    AIProviderConfigCreate,
    AIProviderConfigOut,
    AIProviderConfigUpdate,
    AIProviderTestRequest,
    AIProviderTestResult,
)

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_out(cfg: AIProviderConfig) -> AIProviderConfigOut:
    return AIProviderConfigOut(
        id=cfg.id,
        organisation_id=cfg.organisation_id,
        name=cfg.name,
        provider_type=cfg.provider_type,
        base_url=cfg.base_url,
        default_model=cfg.default_model,
        is_active=cfg.is_active,
        is_default=cfg.is_default,
        fallback_priority=cfg.fallback_priority,
        config_json=cfg.config_json,
        has_api_key=bool(cfg.api_key_encrypted),
        created_at=cfg.created_at,
        updated_at=cfg.updated_at,
    )


async def _get_or_404(db: AsyncSession, config_id: int) -> AIProviderConfig:
    result = await db.execute(
        select(AIProviderConfig).where(AIProviderConfig.id == config_id)
    )
    cfg = result.scalar_one_or_none()
    if cfg is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuration IA introuvable.")
    return cfg


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[AIProviderConfigOut])
async def list_ai_providers(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
) -> list[AIProviderConfigOut]:
    result = await db.execute(
        select(AIProviderConfig).order_by(
            AIProviderConfig.is_default.desc(),
            AIProviderConfig.fallback_priority.asc(),
        )
    )
    return [_to_out(cfg) for cfg in result.scalars().all()]


@router.post("", response_model=AIProviderConfigOut, status_code=status.HTTP_201_CREATED)
async def create_ai_provider(
    payload: AIProviderConfigCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
) -> AIProviderConfigOut:
    api_key_enc: str | None = None
    if payload.api_key:
        api_key_enc = encrypt_secret(payload.api_key)

    cfg = AIProviderConfig(
        organisation_id=None,  # Super Admin only = system scope
        name=payload.name,
        provider_type=payload.provider_type,
        api_key_encrypted=api_key_enc,
        base_url=payload.base_url,
        default_model=payload.default_model,
        is_active=payload.is_active,
        is_default=payload.is_default,
        fallback_priority=payload.fallback_priority,
        config_json=payload.config_json,
    )

    if cfg.is_default:
        await _clear_default_flag(db, exclude_id=None)

    db.add(cfg)
    await db.flush()
    await db.commit()
    await db.refresh(cfg)
    return _to_out(cfg)


@router.get("/{config_id}", response_model=AIProviderConfigOut)
async def get_ai_provider(
    config_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
) -> AIProviderConfigOut:
    cfg = await _get_or_404(db, config_id)
    return _to_out(cfg)


@router.put("/{config_id}", response_model=AIProviderConfigOut)
async def update_ai_provider(
    config_id: int,
    payload: AIProviderConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
) -> AIProviderConfigOut:
    cfg = await _get_or_404(db, config_id)

    if payload.name is not None:
        cfg.name = payload.name
    if payload.provider_type is not None:
        cfg.provider_type = payload.provider_type
    if payload.api_key is not None:
        cfg.api_key_encrypted = encrypt_secret(payload.api_key) if payload.api_key else None
    if payload.base_url is not None:
        cfg.base_url = payload.base_url
    if payload.default_model is not None:
        cfg.default_model = payload.default_model
    if payload.is_active is not None:
        cfg.is_active = payload.is_active
    if payload.is_default is not None:
        cfg.is_default = payload.is_default
        if cfg.is_default:
            await _clear_default_flag(db, exclude_id=cfg.id)
    if payload.fallback_priority is not None:
        cfg.fallback_priority = payload.fallback_priority
    if payload.config_json is not None:
        cfg.config_json = payload.config_json

    await db.commit()
    await db.refresh(cfg)
    return _to_out(cfg)


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_ai_provider(
    config_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
) -> Response:
    cfg = await _get_or_404(db, config_id)
    await db.delete(cfg)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Test de connexion ─────────────────────────────────────────────────────────

@router.post("/test", response_model=AIProviderTestResult)
async def test_ai_provider(
    payload: AIProviderTestRequest,
    _: User = Depends(require_super_admin),
) -> AIProviderTestResult:
    """Teste la connectivité d'un provider IA avec les paramètres fournis."""
    from app.core.ai.service import _build_provider_from_config

    class _FakeCfg:
        provider_type = payload.provider_type
        api_key_encrypted: str | None = None
        base_url = payload.base_url
        default_model = payload.model or ""
        config_json: dict = {}

    if payload.api_key:
        _FakeCfg.api_key_encrypted = encrypt_secret(payload.api_key)

    try:
        provider = _build_provider_from_config(_FakeCfg())
        ok = await provider.health_check()
        return AIProviderTestResult(
            ok=ok,
            provider=provider.provider_name,
            model=provider.model,
            message="Connexion réussie." if ok else "Le provider a répondu mais le health check a échoué.",
        )
    except Exception as exc:
        return AIProviderTestResult(
            ok=False,
            provider=payload.provider_type,
            model=payload.model or "",
            message=f"Erreur : {exc}",
        )


# ── Génération de clé de chiffrement ─────────────────────────────────────────

@router.get("/encryption-key/generate")
async def generate_new_encryption_key(
    _: User = Depends(require_super_admin),
) -> dict[str, str]:
    """
    Génère une nouvelle clé de chiffrement Fernet à mettre dans
    AI_PROVIDER_ENCRYPTION_KEY. Usage unique — génère à la demande.
    """
    return {
        "key": generate_encryption_key(),
        "warning": (
            "Mettez cette clé dans AI_PROVIDER_ENCRYPTION_KEY et redémarrez le serveur. "
            "Toute clé API précédemment chiffrée avec une autre clé sera illisible."
        ),
    }


# ── Utilitaire interne ────────────────────────────────────────────────────────

async def _clear_default_flag(db: AsyncSession, exclude_id: int | None) -> None:
    """Retire le flag is_default de tous les providers sauf exclude_id."""
    from sqlalchemy import update
    stmt = (
        update(AIProviderConfig)
        .where(AIProviderConfig.is_default == True)  # noqa: E712
    )
    if exclude_id is not None:
        stmt = stmt.where(AIProviderConfig.id != exclude_id)
    await db.execute(stmt.values(is_default=False))
