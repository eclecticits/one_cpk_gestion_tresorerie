import importlib

import pytest
from fastapi import HTTPException

from app.core.config import settings


def _reload_debug_router(monkeypatch: pytest.MonkeyPatch, *, env: str, enabled: bool):
    monkeypatch.setattr(settings, "env", env)
    monkeypatch.setattr(settings, "enable_debug_endpoints", enabled)

    import app.api.v1.endpoints.debug as debug_endpoint
    import app.api.v1.router as router_module

    debug_endpoint = importlib.reload(debug_endpoint)
    router_module = importlib.reload(router_module)
    return router_module, debug_endpoint


@pytest.fixture(autouse=True)
def _restore_debug_router_after_test():
    yield
    import app.api.v1.endpoints.debug as debug_endpoint
    import app.api.v1.router as router_module

    importlib.reload(debug_endpoint)
    importlib.reload(router_module)


def _registered_paths(router_module) -> set[str]:
    return {getattr(route, "path", "") for route in router_module.api_router.routes}


def test_debug_finance_sanity_not_registered_when_env_is_prod(monkeypatch):
    router_module, debug_endpoint = _reload_debug_router(monkeypatch, env="prod", enabled=True)

    assert "/debug/finance-sanity" not in _registered_paths(router_module)
    with pytest.raises(HTTPException) as exc:
        debug_endpoint._reject_if_production()
    assert exc.value.status_code == 404


def test_debug_finance_sanity_not_registered_when_env_is_production(monkeypatch):
    router_module, debug_endpoint = _reload_debug_router(monkeypatch, env="production", enabled=True)

    assert "/debug/finance-sanity" not in _registered_paths(router_module)
    with pytest.raises(HTTPException) as exc:
        debug_endpoint._reject_if_production()
    assert exc.value.status_code == 404


def test_debug_finance_sanity_not_registered_by_default_in_dev(monkeypatch):
    router_module, debug_endpoint = _reload_debug_router(monkeypatch, env="dev", enabled=False)

    assert "/debug/finance-sanity" not in _registered_paths(router_module)
    with pytest.raises(HTTPException) as exc:
        debug_endpoint._reject_if_production()
    assert exc.value.status_code == 404


def test_debug_finance_sanity_requires_explicit_enablement_outside_production(monkeypatch):
    router_module, debug_endpoint = _reload_debug_router(monkeypatch, env="dev", enabled=True)

    assert "/debug/finance-sanity" in _registered_paths(router_module)
    debug_endpoint._reject_if_production()
