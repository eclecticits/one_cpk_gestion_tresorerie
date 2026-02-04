from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings


async def _purge() -> None:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM public.refresh_tokens;"))
    await engine.dispose()


def main() -> None:
    asyncio.run(_purge())
    print("Refresh tokens purged.")


if __name__ == "__main__":
    main()
