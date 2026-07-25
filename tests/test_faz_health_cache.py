import pytest


@pytest.fixture(autouse=True)
def clear_faz_health_cache():
    """Clear the faz_health_cache module-level cache before each test in this file."""
    try:
        import app.faz_health_cache as cache_mod
        cache_mod._cache.clear()
    except ImportError:
        pass
    yield
    # Also clear after test to be safe
    try:
        import app.faz_health_cache as cache_mod
        cache_mod._cache.clear()
    except ImportError:
        pass


@pytest.fixture
def targets_file(tmp_path, monkeypatch):
    path = tmp_path / "faz_targets.json"
    import app.faz_targets as faz_targets_mod

    monkeypatch.setattr(faz_targets_mod, "FAZ_TARGETS_FILE", path)
    from app.faz_targets import create_target

    create_target("Primary", host="192.168.64.4", adom="root", token="tok")
    yield path


def test_classify_status_green_when_below_thresholds():
    from app.faz_health_cache import _classify_status

    assert _classify_status(cpu=10, mem=20) == "green"


def test_classify_status_yellow_at_warn_threshold():
    from app.faz_health_cache import _classify_status

    assert _classify_status(cpu=75, mem=10) == "yellow"


def test_classify_status_red_at_crit_threshold():
    from app.faz_health_cache import _classify_status

    assert _classify_status(cpu=10, mem=95) == "red"


def test_classify_status_green_when_no_snmp_data():
    from app.faz_health_cache import _classify_status

    assert _classify_status(cpu=None, mem=None) == "green"


def test_poll_all_targets_populates_cache_on_success(targets_file, monkeypatch):
    import app.faz_health_cache as cache_mod
    from app.config import Config

    monkeypatch.setattr(Config, "SNMP_ENABLED", False)

    def fake_get_sys_status(self):
        return {
            "Hostname": "FAZ-TEST",
            "Version": "v7.6.7",
            "Serial Number": "SN1",
            "Disk Usage": "Free 100GB, Total 200GB",
        }

    def fake_preflight(self):
        return True

    monkeypatch.setattr("app.faz_client.FAZClient.get_sys_status", fake_get_sys_status)
    monkeypatch.setattr("app.faz_client.FAZClient.preflight", fake_preflight)
    monkeypatch.setattr("app.faz_client.FAZClient.logout", lambda self: None)

    cache_mod.poll_all_targets()
    entry = cache_mod.get_cached("Primary")
    assert entry is not None
    assert entry["status"] == "green"
    assert entry["hostname"] == "FAZ-TEST"
    assert entry["serial"] == "SN1"
    assert entry["disk_used"] == "Free 100GB, Total 200GB"
    assert entry["error"] is None


def test_poll_all_targets_marks_offline_on_connection_failure(targets_file, monkeypatch):
    import app.faz_health_cache as cache_mod
    from app.faz_client import FAZError

    def raising_preflight(self):
        raise FAZError("No permission for the resource")

    monkeypatch.setattr("app.faz_client.FAZClient.preflight", raising_preflight)
    monkeypatch.setattr("app.faz_client.FAZClient.logout", lambda self: None)

    cache_mod.poll_all_targets()
    entry = cache_mod.get_cached("Primary")
    assert entry["status"] == "offline"
    assert "No permission" in entry["error"]


def test_poll_all_targets_survives_malformed_target(targets_file, monkeypatch):
    # A malformed entry (e.g. missing "host") must not abort the whole poll
    # cycle and leave every OTHER valid target frozen at its last cache
    # state — it should be recorded as offline and polling should continue.
    import app.faz_health_cache as cache_mod
    import app.faz_targets as faz_targets_mod
    from app.config import Config

    targets = faz_targets_mod._load()
    targets.append({"label": "Broken"})  # no "host" key
    faz_targets_mod._save(targets)

    monkeypatch.setattr(Config, "SNMP_ENABLED", False)

    def fake_get_sys_status(self):
        return {
            "Hostname": "FAZ-TEST",
            "Version": "v7.6.7",
            "Serial Number": "SN1",
        }

    def fake_preflight(self):
        return True

    monkeypatch.setattr("app.faz_client.FAZClient.get_sys_status", fake_get_sys_status)
    monkeypatch.setattr("app.faz_client.FAZClient.preflight", fake_preflight)
    monkeypatch.setattr("app.faz_client.FAZClient.logout", lambda self: None)

    cache_mod.poll_all_targets()

    primary = cache_mod.get_cached("Primary")
    assert primary is not None
    assert primary["status"] == "green"

    broken = cache_mod.get_cached("Broken")
    assert broken is not None
    assert broken["status"] == "offline"
    assert "Malformed target entry" in broken["error"]


def test_get_all_cached_returns_uncached_targets_as_pending(targets_file):
    import app.faz_health_cache as cache_mod

    entries = cache_mod.get_all_cached()
    assert len(entries) == 1
    assert entries[0]["label"] == "Primary"
    assert entries[0]["status"] == "gray"
