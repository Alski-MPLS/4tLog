from app.app_logger import (
    app_log, set_log_level, get_log_level, get_log_levels,
    get_log_entries, clear_log_entries,
)


def test_default_level_is_info():
    clear_log_entries()
    set_log_level("INFO")
    assert get_log_level() == "INFO"


def test_log_below_threshold_is_dropped():
    clear_log_entries()
    set_log_level("WARN")
    app_log("INFO", "test", "should be dropped")
    assert get_log_entries() == []


def test_log_at_or_above_threshold_is_kept():
    clear_log_entries()
    set_log_level("INFO")
    app_log("WARN", "test", "kept", foo="bar")
    entries = get_log_entries()
    assert len(entries) == 1
    assert entries[0]["level"] == "WARN"
    assert entries[0]["component"] == "test"
    assert entries[0]["extra"] == {"foo": "bar"}


def test_get_log_entries_filters_by_component():
    clear_log_entries()
    set_log_level("INFO")
    app_log("INFO", "auth", "a")
    app_log("INFO", "admin", "b")
    entries = get_log_entries(component="auth")
    assert len(entries) == 1
    assert entries[0]["component"] == "auth"


def test_invalid_level_raises():
    import pytest
    with pytest.raises(ValueError):
        set_log_level("BOGUS")
