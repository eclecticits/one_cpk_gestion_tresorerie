from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.tenant_context import set_current_tenant_id
from app.db import session as _tenant_session  # noqa: F401
from app.models.hr import HREmployee
from app.models.organisation import Organisation


@pytest.mark.asyncio
async def test_hr_employee_is_scoped_by_current_tenant(db_session):
    org_a = Organisation(nom="CPK RH", slug="cpk-rh")
    org_b = Organisation(nom="CN RH", slug="cn-rh")
    db_session.add_all([org_a, org_b])
    await db_session.flush()

    set_current_tenant_id(org_a.id)
    db_session.add(HREmployee(tenant_id=org_a.id, matricule="RH-001", nom="Agent A", statut="actif"))
    await db_session.commit()

    set_current_tenant_id(org_b.id)
    db_session.add(HREmployee(tenant_id=org_b.id, matricule="RH-001", nom="Agent B", statut="actif"))
    await db_session.commit()

    rows_b = (await db_session.execute(select(HREmployee))).scalars().all()
    assert [row.nom for row in rows_b] == ["Agent B"]

    set_current_tenant_id(org_a.id)
    rows_a = (await db_session.execute(select(HREmployee))).scalars().all()
    assert [row.nom for row in rows_a] == ["Agent A"]

    set_current_tenant_id(None)
