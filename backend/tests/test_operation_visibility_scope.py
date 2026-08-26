"""Tests for the separation between module visibility and unit context access."""

import pytest

from app.services import service_access


@pytest.mark.asyncio
async def test_menu_visibility_does_not_resolve_or_change_unit_context(monkeypatch):
    calls = []

    async def menu_permission(_db, _user, permission):
        calls.append(permission)
        return True

    async def forbidden_unit_lookup(*_args, **_kwargs):
        raise AssertionError("La visibilité du module ne doit pas résoudre les unités")

    monkeypatch.setattr(service_access, "user_has_permission", menu_permission)
    monkeypatch.setattr(service_access, "get_user_service_ids", forbidden_unit_lookup)

    assert await service_access.has_module_menu_access(object(), object(), "menu_encaissements") is True
    assert calls == ["menu_encaissements"]


@pytest.mark.asyncio
async def test_without_menu_the_unit_scope_remains_a_separate_decision(monkeypatch):
    async def menu_permission(_db, _user, _permission):
        return False

    monkeypatch.setattr(service_access, "user_has_permission", menu_permission)

    assert await service_access.has_module_menu_access(object(), object(), "menu_requisitions") is False
