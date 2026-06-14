from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as aioredis
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings

logger = logging.getLogger("onec_cpk_cache")

_redis_client: Redis | None = None


async def init_redis() -> None:
    global _redis_client
    _redis_client = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    try:
        await _redis_client.ping()
        logger.info("Redis connected: %s", settings.redis_url)
    except RedisError as exc:
        logger.warning("Redis not reachable at startup: %s", exc)


async def close_redis() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


def get_redis() -> Redis | None:
    return _redis_client


async def cache_get(key: str) -> Any | None:
    client = get_redis()
    if client is None:
        return None
    try:
        raw = await client.get(key)
        return json.loads(raw) if raw is not None else None
    except (RedisError, json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.debug("cache_get(%s) failed: %s", key, exc)
        return None


async def cache_set(key: str, value: Any, ttl: int | None = None) -> bool:
    client = get_redis()
    if client is None:
        return False
    try:
        await client.set(key, json.dumps(value), ex=ttl or settings.redis_default_ttl)
        return True
    except (RedisError, TypeError) as exc:
        logger.debug("cache_set(%s) failed: %s", key, exc)
        return False


async def cache_delete(key: str) -> bool:
    client = get_redis()
    if client is None:
        return False
    try:
        await client.delete(key)
        return True
    except RedisError as exc:
        logger.debug("cache_delete(%s) failed: %s", key, exc)
        return False


async def cache_delete_pattern(pattern: str) -> int:
    """Delete all keys matching a glob pattern. Returns count deleted."""
    client = get_redis()
    if client is None:
        return 0
    try:
        keys = await client.keys(pattern)
        if keys:
            return await client.delete(*keys)
        return 0
    except RedisError as exc:
        logger.debug("cache_delete_pattern(%s) failed: %s", pattern, exc)
        return 0


async def redis_ping() -> bool:
    """Return True if Redis is reachable."""
    client = get_redis()
    if client is None:
        return False
    try:
        return await client.ping()
    except RedisError:
        return False
