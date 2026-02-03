from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone

from sqlalchemy import select

# Ensure /app is in sys.path when executed in the container.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.user import User  # noqa: E402

EMAIL = "kidikala@onecrdc.com"
PASSWORD = "kncd5623"
NOM = "Christian"
PRENOM = "Kidikala"
ROLE = "admin"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def main() -> None:
    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.email == EMAIL))
        user = result.scalar_one_or_none()

        if user is None:
            user = User(
                email=EMAIL,
                nom=NOM,
                prenom=PRENOM,
                role=ROLE,
                active=True,
                must_change_password=False,
                hashed_password=hash_password(PASSWORD),
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
            session.add(user)
            await session.commit()
            print("created user:", EMAIL)
            return

        user.hashed_password = hash_password(PASSWORD)
        user.active = True
        user.must_change_password = False
        user.nom = user.nom or NOM
        user.prenom = user.prenom or PRENOM
        user.updated_at = _utcnow()
        await session.commit()
        print("updated user:", EMAIL)


if __name__ == "__main__":
    asyncio.run(main())
