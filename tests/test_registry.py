import pytest

from app import registry


@pytest.fixture(autouse=True)
def _restore_registry():
    """Snapshot and restore the module-global registry around each test.

    Without this, tests here permanently mutate app.registry._registry,
    corrupting global state for any test file that runs afterward and
    depends on real blueprint registration (e.g. test_admin_routes.py,
    test_tab_routes.py).
    """
    snapshot = dict(registry._registry)
    yield
    registry._registry.clear()
    registry._registry.update(snapshot)


def test_register_and_get_registry():
    registry._registry.clear()
    registry.register("dashboard", "Dashboard", "dashboard.index", icon="D")
    reg = registry.get_registry()
    assert reg == {"dashboard": {"name": "Dashboard", "endpoint": "dashboard.index", "icon": "D"}}


def test_known_tabs_maps_key_to_name():
    registry._registry.clear()
    registry.register("dashboard", "Dashboard", "dashboard.index")
    registry.register("admin", "Admin", "admin.admin_page")
    assert registry.known_tabs() == {"dashboard": "Dashboard", "admin": "Admin"}


def test_get_registry_preserves_insertion_order():
    registry._registry.clear()
    registry.register("b", "B", "b.index")
    registry.register("a", "A", "a.index")
    assert list(registry.get_registry().keys()) == ["b", "a"]
