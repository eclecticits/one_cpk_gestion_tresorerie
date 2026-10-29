"""« Programmer une sortie directe » suffit à programmer une sortie directe.

Le formulaire charge les postes de dépense. Il les lisait sur `/budget/postes`,
qui exige le module Budget : un rôle à qui l'on n'avait donné que
`can_direct_disbursement` voyait la page refuser de charger ses postes, et ne
pouvait rien programmer. Il les lit désormais sous `/ordres-decaissement`, et
la permission n'ouvre ni le budget ni la liste des sorties de fonds.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.rbac import Permission, Role, role_permissions
from app.models.user import User

MOT_DE_PASSE = "Directe-1234-abcd"


@pytest.mark.asyncio(loop_scope="session")
async def test_la_seule_permission_ouvre_les_postes_et_rien_dautre(app_client, async_engine, test_organisation):
    async with AsyncSession(async_engine) as s:
        role = Role(code=f"directe-{uuid.uuid4().hex[:8]}", label="Programmeur")
        s.add(role)
        await s.flush()
        cree: list[int] = []
        permission_id = await s.scalar(select(Permission.id).where(Permission.code == "can_direct_disbursement"))
        if permission_id is None:
            permission = Permission(code="can_direct_disbursement", description="Programmer une sortie directe")
            s.add(permission)
            await s.flush()
            permission_id = permission.id
            cree.append(permission_id)
        await s.execute(role_permissions.insert().values(role_id=role.id, permission_id=permission_id))
        email = f"directe-{uuid.uuid4().hex[:8]}@example.com"
        s.add(User(
            email=email, hashed_password=hash_password(MOT_DE_PASSE), nom="Programmeur", prenom="Ada",
            role=role.code, role_id=role.id, organisation_id=test_organisation.id, active=True,
            is_email_verified=True, is_first_login=False, must_change_password=False,
        ))
        role_id = role.id
        await s.commit()

    try:
        entetes = {"X-Tenant-ID": str(test_organisation.id)}
        connexion = await app_client.post(
            "/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE}, headers=entetes)
        assert connexion.status_code == 200, connexion.text
        entetes["Authorization"] = f"Bearer {connexion.json()['access_token']}"

        postes = await app_client.get("/api/v1/ordres-decaissement/postes-depense", headers=entetes)
        assert postes.status_code == 200, postes.text
        assert "postes" in postes.json()

        # Rien de plus : ni le module Budget, ni la liste des sorties de fonds.
        assert (await app_client.get("/api/v1/budget/postes", headers=entetes)).status_code == 403
        assert (await app_client.get("/api/v1/sorties-fonds", headers=entetes)).status_code == 403
    finally:
        # Rôles et permissions sont globaux : ne rien laisser aux tests voisins.
        async with AsyncSession(async_engine) as s:
            await s.execute(update(User).where(User.role_id == role_id).values(role_id=None))
            await s.execute(role_permissions.delete().where(role_permissions.c.role_id == role_id))
            await s.execute(delete(Role).where(Role.id == role_id))
            for permission_id in cree:
                await s.execute(delete(Permission).where(Permission.id == permission_id))
            await s.commit()
