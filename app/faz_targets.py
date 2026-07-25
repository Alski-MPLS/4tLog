"""FortiAnalyzer target list — local store backed by faz_targets.json.

Stored as a JSON array (not a dict keyed by label) to match the shape
documented in the Phase 2 design spec and 4thealth's infra_targets.json
convention. Each entry:

  label   str   unique display name, used as the CRUD key
  host    str   hostname or IP of the FortiAnalyzer appliance
  adom    str   ADOM to query (default "root")
  token   str   bearer token for app.faz_client.FAZClient

Optional per-entry SNMP overrides (each falls back to the matching
Config.SNMP_* default when absent):
  snmp_user, snmp_auth_key, snmp_priv_key, snmp_auth_protocol, snmp_priv_protocol

This module intentionally re-reads the file on every call rather than
caching in memory, so admin edits via the CRUD routes (Task 6) are picked
up by the next background poll cycle (Task 4) without an app restart.
"""

import json
import threading
from pathlib import Path

FAZ_TARGETS_FILE = Path(__file__).parent.parent / "faz_targets.json"
_lock = threading.Lock()

_SNMP_FIELDS = (
    "snmp_user",
    "snmp_auth_key",
    "snmp_priv_key",
    "snmp_auth_protocol",
    "snmp_priv_protocol",
)


def _load() -> list[dict]:
    if not FAZ_TARGETS_FILE.exists():
        return []
    with FAZ_TARGETS_FILE.open() as f:
        return json.load(f)


def _save(targets: list[dict]) -> None:
    with FAZ_TARGETS_FILE.open("w") as f:
        json.dump(targets, f, indent=2)


def list_targets() -> list[dict]:
    with _lock:
        return _load()


def get_target(label: str) -> dict | None:
    with _lock:
        targets = _load()
    for t in targets:
        if t.get("label") == label:
            return t
    return None


def _build_entry(label: str, host: str, adom: str, token: str, snmp_overrides: dict | None) -> dict:
    entry = {"label": label, "host": host, "adom": adom, "token": token}
    for key, value in (snmp_overrides or {}).items():
        if key in _SNMP_FIELDS and value:
            entry[key] = value
    return entry


def create_target(
    label: str,
    host: str,
    adom: str = "root",
    token: str = "",
    snmp_overrides: dict | None = None,
) -> bool:
    """Returns False if a target with this label already exists."""
    label = label.strip()
    if not label:
        raise ValueError("Target label cannot be empty.")
    with _lock:
        targets = _load()
        if any(t.get("label") == label for t in targets):
            return False
        targets.append(_build_entry(label, host, adom, token, snmp_overrides))
        _save(targets)
    return True


def update_target(
    label: str,
    host: str,
    adom: str,
    token: str,
    snmp_overrides: dict | None = None,
) -> bool:
    """Returns False if no target with this label exists."""
    with _lock:
        targets = _load()
        for i, t in enumerate(targets):
            if t.get("label") == label:
                targets[i] = _build_entry(label, host, adom, token, snmp_overrides)
                _save(targets)
                return True
    return False


def delete_target(label: str) -> bool:
    with _lock:
        targets = _load()
        remaining = [t for t in targets if t.get("label") != label]
        if len(remaining) == len(targets):
            return False
        _save(remaining)
    return True
