# 4tlog Phase 2: Dashboard Tab & Docker TLS — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Dashboard tab's placeholder with real FortiAnalyzer health cards backed by a new `faz_client.py` (health/status methods only) and `faz_health_cache.py` (SNMPv3 + JSON-RPC background poller), add an Admin → FAZ Targets CRUD UI, extend the existing group-based access-restriction UI to cover FAZ targets, and add TLS termination in front of the Docker deployment via an Nginx reverse-proxy service.

**Architecture:** Direct structural port of `/Users/alanw/code/github/web/4thealth`'s `fmg_client.py` (context-managed bearer-token JSON-RPC client) and `infra_health_cache.py` (`BackgroundScheduler`-driven SNMPv3 poller feeding a lock-guarded in-memory cache), adapted to FortiAnalyzer-only and to a live-editable `faz_targets.json` (4tlog needs an admin CRUD UI for targets, which 4thealth's static `Config.INFRA_TARGETS` doesn't support — see `app/faz_targets.py` below). `search_logs()`/`build_filter_expression()` are deliberately **not** added to `faz_client.py` in this phase; they land in Phase 3 as the Log Search tab's first consumer.

**Tech Stack:** Python 3.11+, Flask 3.x, `requests`, `apscheduler`, `pysnmp`, pytest, ruff, uv, Nginx (Docker TLS).

## Global Constraints

- Follows Phase 1's constraints (see `docs/superpowers/plans/2026-07-24-phase1-app-scaffold.md`): `uv` for dependency management, `SECRET_KEY` guard, gitignored runtime data (`users.json`/`groups.json`/`.env`/`certs/`) each with a committed `*.example.*` template, CSRF protection on state-changing requests.
- `faz_targets.json` follows the same convention: gitignored runtime file + committed `faz_targets.example.json` template + `.gitignore` entry.
- `faz_client.py` authenticates with `Authorization: Bearer <token>` — this exact header was validated against the test appliance (`192.168.64.4`) during the Ansible playbook debugging session; do not use `X-API-Key` (confirmed silently ignored by FortiAnalyzer's `/jsonrpc` endpoint).
- `faz_client.py` in this phase implements only `login()`/`logout()`/`preflight()`/`get_sys_status()`. Do not add `search_logs()` or `build_filter_expression()` — YAGNI until Phase 3 needs them.
- Background scheduler startup must be disabled during tests (real network/SNMP calls in every test run would be slow and flaky) — guarded via `Config.FAZ_HEALTH_POLL_DISABLED`, set by `tests/conftest.py`, not by relying on every individual test file remembering to set `app.config["TESTING"]`.
- FAZ target visibility restriction reuses the **existing** `groups.json` fields `adom_restrict`/`allowed_adoms` and the **existing** `app/groups.py` functions `get_allowed_adoms()`/`user_can_access_adom()` (already implemented in Phase 1, explicitly reserved for this — see their docstrings). Do not add a new groups.json field.
- No new tab, route, or JSON file may be added without a matching `*.example.*` template and a `.gitignore` entry for the real file (carried over from Phase 1).

---

### Task 1: Dependencies, Config, and gitignore

**Files:**
- Modify: `pyproject.toml`
- Modify: `app/config.py`
- Modify: `.env.example`
- Modify: `.gitignore`
- Modify: `tests/conftest.py`

**Interfaces:**
- Produces: `Config.SNMP_*`, `Config.CPU_WARN/CRIT`, `Config.MEM_WARN/CRIT`, `Config.FAZ_VERIFY_SSL`, `Config.FAZ_REQUEST_TIMEOUT`, `Config.FAZ_HEALTH_POLL_DISABLED` — consumed by Tasks 3 and 4.

- [ ] **Step 1: Add dependencies**

In `pyproject.toml`, add to the `dependencies` list (matching the exact version floors already proven in `/Users/alanw/code/github/web/4thealth/pyproject.toml`):

```toml
dependencies = [
    "flask>=3.0,<4",
    "python-dotenv>=1.0",
    "bcrypt>=4.1",
    "requests>=2.31",
    "apscheduler>=3.11.2",
    "pysnmp>=7.1.27",
]
```

Run: `uv sync`
Expected: resolves and installs without error; `uv.lock` is updated.

- [ ] **Step 2: Add Config fields**

In `app/config.py`, inside the `Config` class, after the existing `MAX_CONTENT_LENGTH` line, add:

```python
    # FortiAnalyzer client (app/faz_client.py)
    FAZ_VERIFY_SSL = os.environ.get("FAZ_VERIFY_SSL", "false").lower() == "true"
    FAZ_REQUEST_TIMEOUT = int(os.environ.get("FAZ_REQUEST_TIMEOUT", "30"))

    # SNMPv3 health polling (app/faz_health_cache.py)
    SNMP_ENABLED = os.environ.get("SNMP_ENABLED", "false").lower() == "true"
    SNMP_PORT = int(os.environ.get("SNMP_PORT", "161"))
    SNMP_TIMEOUT = int(os.environ.get("SNMP_TIMEOUT", "5"))
    SNMP_RETRIES = int(os.environ.get("SNMP_RETRIES", "1"))
    SNMP_POLL_INTERVAL = int(os.environ.get("SNMP_POLL_INTERVAL", "60"))
    SNMP_USER = os.environ.get("SNMP_USER", "")
    SNMP_AUTH_PROTOCOL = os.environ.get("SNMP_AUTH_PROTOCOL", "SHA")
    SNMP_AUTH_KEY = os.environ.get("SNMP_AUTH_KEY", "")
    SNMP_PRIV_PROTOCOL = os.environ.get("SNMP_PRIV_PROTOCOL", "AES")
    SNMP_PRIV_KEY = os.environ.get("SNMP_PRIV_KEY", "")

    # Three-tier health thresholds (percent), same convention as 4thealth
    CPU_WARN = float(os.environ.get("CPU_WARN", "70"))
    CPU_CRIT = float(os.environ.get("CPU_CRIT", "90"))
    MEM_WARN = float(os.environ.get("MEM_WARN", "70"))
    MEM_CRIT = float(os.environ.get("MEM_CRIT", "90"))

    # Set by tests/conftest.py to skip starting the background health
    # poller (real network/SNMP calls) during the test suite.
    FAZ_HEALTH_POLL_DISABLED = (
        os.environ.get("FAZ_HEALTH_POLL_DISABLED", "false").lower() == "true"
    )
```

- [ ] **Step 3: Disable the health poller during tests**

In `tests/conftest.py`, after the existing `os.environ.setdefault("SECRET_KEY", ...)` line, add:

```python
os.environ.setdefault("FAZ_HEALTH_POLL_DISABLED", "true")
```

- [ ] **Step 4: Document the new env vars**

Append to `.env.example`:

```bash
# FortiAnalyzer client (app/faz_client.py)
# FAZ_VERIFY_SSL=false
# FAZ_REQUEST_TIMEOUT=30

# SNMPv3 health polling for the Dashboard tab — off by default; CPU/mem
# stay blank on health cards until enabled. Per-target snmp_user/snmp_auth_key/
# snmp_priv_key in faz_targets.json override these.
# SNMP_ENABLED=false
# SNMP_PORT=161
# SNMP_TIMEOUT=5
# SNMP_RETRIES=1
# SNMP_POLL_INTERVAL=60
# SNMP_USER=
# SNMP_AUTH_PROTOCOL=SHA
# SNMP_AUTH_KEY=
# SNMP_PRIV_PROTOCOL=AES
# SNMP_PRIV_KEY=

# Dashboard health card thresholds (percent)
# CPU_WARN=70
# CPU_CRIT=90
# MEM_WARN=70
# MEM_CRIT=90
```

- [ ] **Step 5: gitignore faz_targets.json**

In `.gitignore`, under the `# Application config / secrets` section, add a line:

```
faz_targets.json
```

- [ ] **Step 6: Verify existing tests still pass**

Run: `uv run pytest -q`
Expected: all existing tests PASS (no behavior changed yet, only config/deps added).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock app/config.py .env.example .gitignore tests/conftest.py
git commit -m "Add Phase 2 dependencies and FAZ/SNMP config"
```

---

### Task 2: `app/faz_targets.py` — target list CRUD

**Files:**
- Create: `app/faz_targets.py`
- Create: `faz_targets.example.json`
- Test: `tests/test_faz_targets.py`

**Interfaces:**
- Produces: `list_targets() -> list[dict]`, `get_target(label) -> dict | None`, `create_target(label, host, adom="root", token="", snmp_overrides=None) -> bool`, `update_target(label, host, adom, token, snmp_overrides=None) -> bool`, `delete_target(label) -> bool`. Each dict has keys: `label`, `host`, `adom`, `token`, and optionally `snmp_user`/`snmp_auth_key`/`snmp_priv_key`/`snmp_auth_protocol`/`snmp_priv_protocol`. Consumed by Task 4 (`faz_health_cache.py`) and Task 6 (admin routes).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_faz_targets.py`:

```python
import pytest


@pytest.fixture
def targets_file(tmp_path, monkeypatch):
    path = tmp_path / "faz_targets.json"
    import app.faz_targets as faz_targets_mod

    monkeypatch.setattr(faz_targets_mod, "FAZ_TARGETS_FILE", path)
    yield path


def test_list_empty_when_no_file(targets_file):
    from app.faz_targets import list_targets

    assert list_targets() == []


def test_create_list_get(targets_file):
    from app.faz_targets import create_target, get_target, list_targets

    assert create_target("Primary", host="192.168.64.4", adom="root", token="abc123") is True
    assert [t["label"] for t in list_targets()] == ["Primary"]
    t = get_target("Primary")
    assert t["host"] == "192.168.64.4"
    assert t["adom"] == "root"
    assert t["token"] == "abc123"


def test_create_duplicate_label_fails(targets_file):
    from app.faz_targets import create_target

    assert create_target("Primary", host="192.168.64.4") is True
    assert create_target("Primary", host="10.0.0.9") is False


def test_create_with_snmp_overrides(targets_file):
    from app.faz_targets import create_target, get_target

    create_target(
        "Primary",
        host="192.168.64.4",
        snmp_overrides={"snmp_user": "monitor2", "snmp_auth_key": "k1"},
    )
    t = get_target("Primary")
    assert t["snmp_user"] == "monitor2"
    assert t["snmp_auth_key"] == "k1"


def test_update_target(targets_file):
    from app.faz_targets import create_target, get_target, update_target

    create_target("Primary", host="192.168.64.4", adom="root", token="abc123")
    ok = update_target("Primary", host="10.0.0.9", adom="lab", token="xyz789")
    assert ok is True
    t = get_target("Primary")
    assert t["host"] == "10.0.0.9"
    assert t["adom"] == "lab"
    assert t["token"] == "xyz789"


def test_update_missing_target_fails(targets_file):
    from app.faz_targets import update_target

    assert update_target("Ghost", host="10.0.0.9", adom="root", token="x") is False


def test_delete_target(targets_file):
    from app.faz_targets import create_target, delete_target, list_targets

    create_target("Primary", host="192.168.64.4")
    assert delete_target("Primary") is True
    assert list_targets() == []
    assert delete_target("Primary") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_faz_targets.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.faz_targets'`

- [ ] **Step 3: Implement `app/faz_targets.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_faz_targets.py -v`
Expected: PASS (all 7 tests)

- [ ] **Step 5: Write the committed example template**

Create `faz_targets.example.json`:

```json
[
  {
    "label": "FortiAnalyzer Primary",
    "host": "192.168.64.4",
    "adom": "root",
    "token": "faz-primary-bearer-token"
  }
]
```

- [ ] **Step 6: Commit**

```bash
git add app/faz_targets.py faz_targets.example.json tests/test_faz_targets.py
git commit -m "Add faz_targets.json CRUD module"
```

---

### Task 3: `app/faz_client.py` — health/status JSON-RPC client

**Files:**
- Create: `app/faz_client.py`
- Test: `tests/test_faz_client.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `FAZClient(host, token, adom="root", verify_ssl=True, timeout=30, port=443, preflight_resource=None)`, context manager (`__enter__`/`__exit__`), `.preflight() -> bool` (raises `FAZError`), `.get_sys_status() -> dict` (raises `FAZError`). `FAZError` exception class. Consumed by Task 4 (`faz_health_cache.py`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_faz_client.py`:

```python
import pytest


class FakeResponse:
    def __init__(self, json_body, status_code=200):
        self._json = json_body
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


def _client(monkeypatch, responses):
    """responses: list of dicts returned by successive _post() calls."""
    from app.faz_client import FAZClient

    client = FAZClient(host="192.168.64.4", token="test-token", adom="root")
    calls = []

    def fake_post(url, json=None, headers=None, verify=None, timeout=None):
        calls.append({"url": url, "json": json, "headers": headers})
        return FakeResponse(responses[len(calls) - 1])

    monkeypatch.setattr(client._http, "post", fake_post)
    return client, calls


def test_preflight_success(monkeypatch):
    client, calls = _client(
        monkeypatch,
        [{"jsonrpc": "2.0", "id": 1, "result": [{"status": {"code": 0, "message": "OK"}}]}],
    )
    assert client.preflight() is True
    assert calls[0]["headers"]["Authorization"] == "Bearer test-token"
    assert calls[0]["json"]["params"][0]["url"] == "/logview/adom/root/logfields"


def test_preflight_permission_denied_raises(monkeypatch):
    from app.faz_client import FAZError

    client, _ = _client(
        monkeypatch,
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": [{"status": {"code": -11, "message": "No permission for the resource"}}],
            }
        ],
    )
    with pytest.raises(FAZError, match="No permission for the resource"):
        client.preflight()


def test_preflight_jsonrpc_error_raises(monkeypatch):
    from app.faz_client import FAZError

    client, _ = _client(
        monkeypatch,
        [{"jsonrpc": "2.0", "id": 1, "error": {"code": -32600, "message": "Invalid Request"}}],
    )
    with pytest.raises(FAZError, match="Invalid Request"):
        client.preflight()


def test_get_sys_status_returns_data(monkeypatch):
    client, calls = _client(
        monkeypatch,
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": [
                    {
                        "status": {"code": 0, "message": "OK"},
                        "data": {
                            "hostname": "FAZ-TEST",
                            "version": "v7.6.7",
                            "serial": "FAZ-VM0000000001",
                            "ha-mode": "standalone",
                        },
                    }
                ],
            }
        ],
    )
    data = client.get_sys_status()
    assert data["hostname"] == "FAZ-TEST"
    assert calls[0]["json"]["params"][0]["url"] == "/sys/status"


def test_context_manager_closes_session(monkeypatch):
    from app.faz_client import FAZClient

    client = FAZClient(host="192.168.64.4", token="t", adom="root")
    closed = {"value": False}
    monkeypatch.setattr(client._http, "close", lambda: closed.__setitem__("value", True))
    with client as c:
        assert c is client
    assert closed["value"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_faz_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.faz_client'`

- [ ] **Step 3: Implement `app/faz_client.py`**

```python
"""FortiAnalyzer JSON-RPC client — read-only health/status calls.

Authenticates with Authorization: Bearer <token>. This header, not
X-API-Key, is what FortiAnalyzer's /jsonrpc endpoint actually recognizes —
confirmed by direct curl comparison against the test appliance
(192.168.64.4) while debugging ansible/faz_log_search.yml: X-API-Key and
no-auth-header-at-all produced byte-identical "-11 No permission" errors,
while Authorization: Bearer returned real data.

Only login()/logout()/preflight()/get_sys_status() are implemented here —
search_logs() and build_filter_expression() (ported from the Ansible
playbook's Jinja filter-building logic) are added in Phase 3 when the Log
Search tab is their first consumer.
"""

import requests
import urllib3


class FAZError(Exception):
    """Raised when FortiAnalyzer returns a non-zero status code, a JSON-RPC
    error envelope, or an unexpected response shape."""


class FAZClient:
    def __init__(
        self,
        host: str,
        token: str,
        adom: str = "root",
        verify_ssl: bool = True,
        timeout: int = 30,
        port: int = 443,
        preflight_resource: str | None = None,
    ):
        self.host = host
        self.port = port
        self.token = token
        self.adom = adom
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.preflight_resource = preflight_resource or f"/logview/adom/{adom}/logfields"
        self.base_url = f"https://{host}:{port}/jsonrpc"
        self._req_id = 0
        self._http = requests.Session()
        if not verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _post(self, body: dict) -> dict:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        resp = self._http.post(
            self.base_url,
            json=body,
            headers=headers,
            verify=self.verify_ssl,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _unwrap_result(data: dict) -> dict:
        if "error" in data:
            raise FAZError(f"FortiAnalyzer error: {data['error']}")
        result = data.get("result")
        if isinstance(result, list):
            result = result[0] if result else {}
        if not isinstance(result, dict):
            raise FAZError(f"Unexpected FortiAnalyzer response shape: {data!r}")
        status = result.get("status", {})
        if status.get("code", -1) != 0:
            raise FAZError(status.get("message", "Unknown FortiAnalyzer error"))
        return result

    def login(self) -> "FAZClient":
        # Bearer token auth — no session login call needed.
        return self

    def logout(self) -> None:
        self._http.close()

    def __enter__(self) -> "FAZClient":
        return self.login()

    def __exit__(self, *_exc) -> None:
        self.logout()

    def preflight(self) -> bool:
        """Connectivity/permission check against the logview module.

        Ported from the Ansible playbook's preflight task
        (ansible/faz_log_search.yml). Returns True if the account can read
        logview resources; raises FAZError otherwise — most commonly with
        status code -11 "No permission for the resource".
        """
        body = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "get",
            "params": [
                {
                    "url": self.preflight_resource,
                    "apiver": 3,
                    "devtype": "FortiGate",
                    "logtype": "traffic",
                }
            ],
            "session": None,
        }
        self._unwrap_result(self._post(body))
        return True

    def get_sys_status(self) -> dict:
        """Return FortiAnalyzer /sys/status: hostname, version, serial, HA
        mode, disk usage. The exact field names in the returned dict are
        NOT covered by the Swagger specs in api-info/ (those only document
        logview/eventmgmt/fortiview) and must be validated live against
        the test appliance as part of this phase's validation step
        (Task 9) before the Dashboard is considered complete.
        """
        body = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "get",
            "params": [{"url": "/sys/status"}],
            "session": None,
        }
        result = self._unwrap_result(self._post(body))
        return result.get("data", {})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_faz_client.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Commit**

```bash
git add app/faz_client.py tests/test_faz_client.py
git commit -m "Add faz_client.py health/status JSON-RPC client"
```

---

### Task 4: `app/faz_health_cache.py` — background SNMP + status poller

**Files:**
- Create: `app/faz_health_cache.py`
- Test: `tests/test_faz_health_cache.py`

**Interfaces:**
- Consumes: `app.faz_targets.list_targets()` (Task 2), `app.faz_client.FAZClient`/`FAZError` (Task 3), `Config.SNMP_*`/`CPU_WARN`/`CPU_CRIT`/`MEM_WARN`/`MEM_CRIT`/`FAZ_VERIFY_SSL`/`FAZ_REQUEST_TIMEOUT`/`FAZ_HEALTH_POLL_DISABLED` (Task 1).
- Produces: `poll_all_targets() -> None`, `poll_now() -> None`, `get_cached(label) -> dict | None`, `get_all_cached() -> list[dict]`, `init_scheduler(app) -> None`. Consumed by Task 5 (app factory wiring) and Task 7 (dashboard route).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_faz_health_cache.py`:

```python
import pytest


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
        return {"hostname": "FAZ-TEST", "version": "v7.6.7", "serial": "SN1", "ha-mode": "standalone"}

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


def test_get_all_cached_returns_uncached_targets_as_pending(targets_file):
    import app.faz_health_cache as cache_mod

    entries = cache_mod.get_all_cached()
    assert len(entries) == 1
    assert entries[0]["label"] == "Primary"
    assert entries[0]["status"] == "gray"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_faz_health_cache.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.faz_health_cache'`

- [ ] **Step 3: Implement `app/faz_health_cache.py`**

```python
"""Background cache for FortiAnalyzer Dashboard health cards.

Each poll cycle, for every app.faz_targets entry: calls FAZClient.preflight()
+ get_sys_status() for connectivity/hostname/version/serial/HA, and (if
Config.SNMP_ENABLED) an SNMPv3 GET for CPU/mem. Results land in a
lock-guarded in-memory dict keyed by target label; app/routes/dashboard_routes.py
reads a snapshot via get_all_cached() and never blocks on a live poll.

SNMP OIDs below are FortiAnalyzer's fmSystem group
(1.3.6.1.4.1.12356.103.2.1.*), confirmed against real FAZ hardware
(v7.4.10) in /Users/alanw/code/github/web/4thealth's infra_health_cache.py —
same used-KB/total-KB computed-percentage pattern as FortiManager, since
FAZ has no native memory-percentage OID.
"""

from __future__ import annotations

import asyncio
import datetime
import threading

from flask import Flask

from pysnmp.hlapi.v3arch.asyncio import (
    SnmpEngine,
    UsmUserData,
    UdpTransportTarget,
    ContextData,
    ObjectType,
    ObjectIdentity,
    get_cmd,
    USM_AUTH_HMAC96_SHA,
    USM_AUTH_HMAC192_SHA256,
    USM_AUTH_HMAC384_SHA512,
    USM_PRIV_CFB128_AES,
    USM_PRIV_CFB192_AES,
    USM_PRIV_CFB256_AES,
)

from app.config import Config
from app.faz_client import FAZClient, FAZError
from app.faz_targets import list_targets

_lock = threading.RLock()
_cache: dict[str, dict] = {}

OID_CPU = "1.3.6.1.4.1.12356.103.2.1.1.0"
OID_MEM_USED = "1.3.6.1.4.1.12356.103.2.1.2.0"
OID_MEM_TOTAL = "1.3.6.1.4.1.12356.103.2.1.3.0"

_AUTH_PROTOCOLS = {
    "SHA": USM_AUTH_HMAC96_SHA,
    "SHA256": USM_AUTH_HMAC192_SHA256,
    "SHA512": USM_AUTH_HMAC384_SHA512,
}
_PRIV_PROTOCOLS = {
    "AES": USM_PRIV_CFB128_AES,
    "AES192": USM_PRIV_CFB192_AES,
    "AES256": USM_PRIV_CFB256_AES,
}


class SnmpTimeout(Exception):
    pass


class SnmpQueryError(Exception):
    pass


def _resolve_snmp_creds(target: dict) -> dict:
    return {
        "user": target.get("snmp_user", Config.SNMP_USER),
        "auth_key": target.get("snmp_auth_key", Config.SNMP_AUTH_KEY),
        "priv_key": target.get("snmp_priv_key", Config.SNMP_PRIV_KEY),
        "auth_protocol": target.get("snmp_auth_protocol", Config.SNMP_AUTH_PROTOCOL),
        "priv_protocol": target.get("snmp_priv_protocol", Config.SNMP_PRIV_PROTOCOL),
    }


async def _snmp_get(host: str, oids: list[str], creds: dict) -> list[float]:
    engine = SnmpEngine()
    auth_data = UsmUserData(
        creds["user"],
        authKey=creds["auth_key"],
        privKey=creds["priv_key"],
        authProtocol=_AUTH_PROTOCOLS.get(creds["auth_protocol"], USM_AUTH_HMAC96_SHA),
        privProtocol=_PRIV_PROTOCOLS.get(creds["priv_protocol"], USM_PRIV_CFB128_AES),
    )
    udp_target = await UdpTransportTarget.create(
        (host, Config.SNMP_PORT), timeout=Config.SNMP_TIMEOUT, retries=Config.SNMP_RETRIES
    )
    error_indication, error_status, _error_index, var_binds = await get_cmd(
        engine,
        auth_data,
        udp_target,
        ContextData(),
        *(ObjectType(ObjectIdentity(oid)) for oid in oids),
    )
    if error_indication:
        message = str(error_indication)
        if "timeout" in message.lower():
            raise SnmpTimeout(message)
        raise SnmpQueryError(message)
    if error_status:
        raise SnmpQueryError(str(error_status))
    return [float(var_bind[1]) for var_bind in var_binds]


def _poll_snmp(target: dict) -> tuple[float | None, float | None, str]:
    """Returns (cpu, mem, snmp_status)."""
    if not Config.SNMP_ENABLED:
        return None, None, "disabled"
    creds = _resolve_snmp_creds(target)
    try:
        cpu, mem_used, mem_total = asyncio.run(
            _snmp_get(target["host"], [OID_CPU, OID_MEM_USED, OID_MEM_TOTAL], creds)
        )
        mem = (mem_used / mem_total * 100) if mem_total else 0.0
        return cpu, mem, "ok"
    except SnmpTimeout:
        return None, None, "timeout"
    except Exception:
        return None, None, "error"


def _classify_status(cpu: float | None, mem: float | None) -> str:
    """Three-tier health classification. green when no SNMP data is
    available (health call still succeeded, just no CPU/mem to gauge)."""
    if cpu is None and mem is None:
        return "green"
    cpu = cpu or 0.0
    mem = mem or 0.0
    if cpu >= Config.CPU_CRIT or mem >= Config.MEM_CRIT:
        return "red"
    if cpu >= Config.CPU_WARN or mem >= Config.MEM_WARN:
        return "yellow"
    return "green"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _poll_target(target: dict) -> dict:
    label = target["label"]
    host = target["host"]
    adom = target.get("adom", "root")
    entry = {
        "label": label,
        "host": host,
        "adom": adom,
        "status": "offline",
        "hostname": "n/a",
        "version": "n/a",
        "serial": "n/a",
        "ha_mode": "n/a",
        "ha_role": "n/a",
        "disk_used": "n/a",
        "cpu": None,
        "mem": None,
        "snmp_status": "disabled",
        "error": None,
        "last_updated": _now(),
    }
    try:
        with FAZClient(
            host=host,
            token=target.get("token", ""),
            adom=adom,
            verify_ssl=Config.FAZ_VERIFY_SSL,
            timeout=Config.FAZ_REQUEST_TIMEOUT,
        ) as client:
            client.preflight()
            sys_status = client.get_sys_status()
    except FAZError as exc:
        entry["error"] = str(exc)
        return entry
    except Exception as exc:  # network errors, timeouts, DNS failures, etc.
        entry["error"] = f"Connection failed: {exc}"
        return entry

    entry["hostname"] = sys_status.get("hostname", "n/a")
    entry["version"] = sys_status.get("version", "n/a")
    entry["serial"] = sys_status.get("serial", "n/a")
    entry["ha_mode"] = sys_status.get("ha-mode", sys_status.get("ha_mode", "n/a"))
    entry["ha_role"] = sys_status.get("ha-role", sys_status.get("ha_role", "n/a"))
    entry["disk_used"] = sys_status.get("disk-usage", sys_status.get("disk_usage", "n/a"))

    cpu, mem, snmp_status = _poll_snmp(target)
    entry["cpu"] = round(cpu, 1) if cpu is not None else None
    entry["mem"] = round(mem, 1) if mem is not None else None
    entry["snmp_status"] = snmp_status
    entry["status"] = _classify_status(cpu, mem)
    entry["last_updated"] = _now()
    return entry


def poll_all_targets() -> None:
    for target in list_targets():
        label = target.get("label")
        if not label:
            continue
        result = _poll_target(target)
        with _lock:
            _cache[label] = result


def get_cached(label: str) -> dict | None:
    with _lock:
        entry = _cache.get(label)
        return dict(entry) if entry is not None else None


def get_all_cached() -> list[dict]:
    """Snapshot for every currently-configured target, in faz_targets.json
    order. A target with no cache entry yet (first poll still pending)
    shows as status 'gray' rather than being omitted."""
    with _lock:
        cache_snapshot = dict(_cache)
    result = []
    for target in list_targets():
        label = target.get("label")
        cached = cache_snapshot.get(label)
        if cached is not None:
            result.append(cached)
        else:
            result.append(
                {
                    "label": label,
                    "host": target.get("host", ""),
                    "adom": target.get("adom", "root"),
                    "status": "gray",
                    "hostname": "n/a",
                    "version": "n/a",
                    "serial": "n/a",
                    "ha_mode": "n/a",
                    "ha_role": "n/a",
                    "disk_used": "n/a",
                    "cpu": None,
                    "mem": None,
                    "snmp_status": "disabled",
                    "error": None,
                    "last_updated": None,
                }
            )
    return result


def poll_now() -> None:
    """Kick off a non-blocking poll of all targets in a daemon thread."""
    t = threading.Thread(target=poll_all_targets, name="faz_health_poll_now", daemon=True)
    t.start()


def init_scheduler(app: Flask) -> None:
    """Register a recurring APScheduler job and run the first poll immediately.

    No-op if Config.FAZ_HEALTH_POLL_DISABLED (set by tests/conftest.py) —
    keeps the test suite from starting real background network/SNMP
    polling threads.
    """
    if Config.FAZ_HEALTH_POLL_DISABLED:
        return

    from apscheduler.schedulers.background import BackgroundScheduler

    poll_now()

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=poll_all_targets,
        trigger="interval",
        seconds=Config.SNMP_POLL_INTERVAL,
        id="faz_health_poll",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_faz_health_cache.py -v`
Expected: PASS (all 7 tests)

- [ ] **Step 5: Commit**

```bash
git add app/faz_health_cache.py tests/test_faz_health_cache.py
git commit -m "Add faz_health_cache.py background health poller"
```

---

### Task 5: Wire the scheduler into the app factory

**Files:**
- Modify: `app/__init__.py`
- Test: `tests/test_smoke.py` (verify existing smoke test still passes — no new test needed, this task has no new externally-observable behavior beyond "the app still boots")

**Interfaces:**
- Consumes: `app.faz_health_cache.init_scheduler` (Task 4).

- [ ] **Step 1: Add the scheduler startup guard**

In `app/__init__.py`, inside `create_app()`, after the existing blueprint-registration loop and the `groups.KNOWN_TABS = registry.known_tabs()` line, before `return app`, add:

```python
    if not app.config.get("_FAZ_HEALTH_STARTED"):
        app.config["_FAZ_HEALTH_STARTED"] = True
        from app.faz_health_cache import init_scheduler as init_faz_health_scheduler

        init_faz_health_scheduler(app)
```

(Note: `init_scheduler` itself already no-ops when `Config.FAZ_HEALTH_POLL_DISABLED` is set, per Task 4 — this guard here only prevents double-registration on Flask's debug-mode reloader, matching the `_SUMMARY_STARTED`-style guards in 4thealth's `app/__init__.py`.)

- [ ] **Step 2: Run the full test suite**

Run: `uv run pytest -q`
Expected: all tests PASS, including pre-existing Phase 1 tests — confirms `FAZ_HEALTH_POLL_DISABLED=true` (set by `tests/conftest.py` in Task 1) actually prevents the scheduler from starting during `create_app()` calls in tests.

- [ ] **Step 3: Commit**

```bash
git add app/__init__.py
git commit -m "Wire faz_health_cache scheduler into the app factory"
```

---

### Task 6: Admin → FAZ Targets sub-tab + group target-restriction UI

**Files:**
- Modify: `app/routes/admin_routes.py`
- Modify: `app/templates/admin.html`
- Modify: `app/static/js/admin.js`
- Test: `tests/test_admin_routes.py` (add to existing file)

**Interfaces:**
- Consumes: `app.faz_targets.{list_targets, get_target, create_target, update_target, delete_target}` (Task 2).
- Produces: `GET/POST /admin/api/faz-targets`, `PUT/DELETE /admin/api/faz-targets/<label>` JSON endpoints. Not consumed by any later task, but the group-restriction UI (this task) is what makes `groups.json`'s existing `adom_restrict`/`allowed_adoms` fields actually settable by an admin for FAZ targets — consumed conceptually by Task 7's dashboard filtering.

- [ ] **Step 1: Write the failing route tests**

Append to `tests/test_admin_routes.py`:

```python
@pytest.fixture
def faz_targets_file(tmp_path, monkeypatch):
    path = tmp_path / "faz_targets.json"
    import app.faz_targets as faz_targets_mod

    monkeypatch.setattr(faz_targets_mod, "FAZ_TARGETS_FILE", path)
    yield path


def test_faz_targets_blocked_for_viewer(client, faz_targets_file):
    _login(client, "viewer1")
    resp = client.get("/admin/api/faz-targets")
    assert resp.status_code == 403


def test_faz_targets_crud_for_admin(client, faz_targets_file):
    _login(client, "admin1")
    csrf = _csrf(client)

    resp = client.get("/admin/api/faz-targets")
    assert resp.status_code == 200
    assert resp.get_json() == []

    resp = client.post(
        "/admin/api/faz-targets",
        json={"label": "Primary", "host": "192.168.64.4", "adom": "root", "token": "abc"},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 201
    assert resp.get_json()["label"] == "Primary"

    resp = client.post(
        "/admin/api/faz-targets",
        json={"label": "Primary", "host": "10.0.0.9"},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 409

    resp = client.put(
        "/admin/api/faz-targets/Primary",
        json={"host": "10.0.0.9", "adom": "lab", "token": "xyz"},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 200
    assert resp.get_json()["host"] == "10.0.0.9"

    resp = client.delete("/admin/api/faz-targets/Primary", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200

    resp = client.get("/admin/api/faz-targets")
    assert resp.get_json() == []


def test_faz_targets_missing_label_rejected(client, faz_targets_file):
    _login(client, "admin1")
    csrf = _csrf(client)
    resp = client.post(
        "/admin/api/faz-targets",
        json={"host": "192.168.64.4"},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 400


def test_faz_targets_update_missing_returns_404(client, faz_targets_file):
    _login(client, "admin1")
    csrf = _csrf(client)
    resp = client.put(
        "/admin/api/faz-targets/Ghost",
        json={"host": "10.0.0.9", "adom": "root", "token": "x"},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_admin_routes.py -v -k faz_targets`
Expected: FAIL — routes don't exist yet (404 instead of 403/200/201/etc.)

- [ ] **Step 3: Add the FAZ Targets routes**

In `app/routes/admin_routes.py`, add to the imports:

```python
from app.faz_targets import create_target, delete_target, get_target, list_targets, update_target
```

Add a new section (after the Groups API section, before the Users API section):

```python
# ── FAZ Targets API ────────────────────────────────────────────────────────────


@bp.route("/api/faz-targets")
@_admin_required
def api_faz_targets_list():
    return jsonify(list_targets())


@bp.route("/api/faz-targets", methods=["POST"])
@_admin_required
def api_faz_targets_create():
    data = request.get_json(silent=True) or {}
    label = (data.get("label") or "").strip()
    if not label:
        return jsonify({"error": "label is required"}), 400
    host = data.get("host", "")
    adom = data.get("adom", "root")
    token = data.get("token", "")
    snmp_overrides = {
        k: data[k]
        for k in ("snmp_user", "snmp_auth_key", "snmp_priv_key", "snmp_auth_protocol", "snmp_priv_protocol")
        if data.get(k)
    }
    ok = create_target(label, host, adom, token, snmp_overrides)
    if not ok:
        return jsonify({"error": f"Target '{label}' already exists"}), 409
    app_log("INFO", "admin", "FAZ target created", by=session["user"], target=label)
    return jsonify(get_target(label)), 201


@bp.route("/api/faz-targets/<label>", methods=["PUT"])
@_admin_required
def api_faz_targets_update(label: str):
    data = request.get_json(silent=True) or {}
    host = data.get("host", "")
    adom = data.get("adom", "root")
    token = data.get("token", "")
    snmp_overrides = {
        k: data[k]
        for k in ("snmp_user", "snmp_auth_key", "snmp_priv_key", "snmp_auth_protocol", "snmp_priv_protocol")
        if data.get(k)
    }
    ok = update_target(label, host, adom, token, snmp_overrides)
    if not ok:
        return jsonify({"error": f"Target '{label}' not found"}), 404
    app_log("INFO", "admin", "FAZ target updated", by=session["user"], target=label)
    return jsonify(get_target(label))


@bp.route("/api/faz-targets/<label>", methods=["DELETE"])
@_admin_required
def api_faz_targets_delete(label: str):
    if not delete_target(label):
        return jsonify({"error": f"Target '{label}' not found"}), 404
    app_log("INFO", "admin", "FAZ target deleted", by=session["user"], target=label)
    return jsonify({"deleted": label})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_admin_routes.py -v -k faz_targets`
Expected: PASS (all 5 new tests)

- [ ] **Step 5: Add the FAZ Targets sub-tab to admin.html**

In `app/templates/admin.html`, add a new tab button to `#adminTabs` (after "Logs"):

```html
  <button class="admin-tab-btn" data-panel="panel-faz-targets">FAZ Targets</button>
```

Add a new panel (after `#panel-logs`, before the `groupModal` div):

```html
<div class="admin-panel" id="panel-faz-targets">
  <div class="panel-header">
    <h2>FAZ Targets</h2>
    <button class="btn btn-primary" id="btnNewFazTarget">+ New Target</button>
  </div>
  <div class="table-wrapper">
    <table class="data-table" id="fazTargetsTable">
      <thead>
        <tr><th>Label</th><th>Host</th><th>ADOM</th><th>Actions</th></tr>
      </thead>
      <tbody id="fazTargetsTbody"></tbody>
    </table>
  </div>
</div>
```

Add a new modal (after `groupModal`'s closing `</div>`):

```html
<div class="modal-overlay hidden" id="fazTargetModal">
  <div class="modal">
    <div class="modal-header">
      <h3 id="fazTargetModalTitle">New FAZ Target</h3>
      <button class="modal-close" id="fazTargetModalClose">&times;</button>
    </div>
    <div class="modal-body">
      <input type="hidden" id="fazTargetModalMode" value="create" />
      <input type="hidden" id="fazTargetModalOrigLabel" value="" />
      <div class="form-group">
        <label>Label</label>
        <input type="text" class="form-control" id="fazTargetLabelInput" placeholder="e.g. FortiAnalyzer Primary" />
      </div>
      <div class="form-group">
        <label>Host</label>
        <input type="text" class="form-control" id="fazTargetHostInput" placeholder="e.g. 192.168.64.4" />
      </div>
      <div class="form-group">
        <label>ADOM</label>
        <input type="text" class="form-control" id="fazTargetAdomInput" placeholder="root" />
      </div>
      <div class="form-group">
        <label>API Token</label>
        <input type="text" class="form-control" id="fazTargetTokenInput" placeholder="Bearer token" />
      </div>
      <div id="fazTargetModalError" class="alert alert-danger hidden"></div>
    </div>
    <div class="modal-footer">
      <button class="btn" id="fazTargetModalCancel">Cancel</button>
      <button class="btn btn-primary" id="fazTargetModalSave">Save Target</button>
    </div>
  </div>
</div>
```

Also extend the existing group modal's body (inside `#groupModal .modal-body`, after the `#memberCheckboxes` `form-group` div) to expose the already-existing-but-unused `adom_restrict`/`allowed_adoms` fields:

```html
      <div class="form-group">
        <label>
          <input type="checkbox" id="groupAdomRestrictInput" />
          Restrict to specific FAZ targets
        </label>
      </div>
      <div class="form-group" id="groupTargetCheckboxesWrap">
        <label>Allowed FAZ Targets</label>
        <div id="groupTargetCheckboxes" class="checkbox-group"></div>
      </div>
```

- [ ] **Step 6: Add the FAZ Targets JS and extend the group modal JS**

In `app/static/js/admin.js`, add `fazTargets: []` to the `state` object:

```javascript
  const state = { groups: [], users: [], tabs: [], fazTargets: [] };
```

Add a new section (after the `// ── Groups ──` section, before `// ── Users ──`):

```javascript
  // ── FAZ Targets ────────────────────────────────────────────────────────────
  function renderFazTargets() {
    const tbody = document.getElementById('fazTargetsTbody');
    tbody.innerHTML = '';
    state.fazTargets.forEach((t) => {
      const tr = el('tr', {});
      tr.appendChild(el('td', { text: t.label }));
      tr.appendChild(el('td', { text: t.host }));
      tr.appendChild(el('td', { text: t.adom }));
      const actions = el('td', {});
      const editBtn = el('button', { class: 'btn btn-sm', text: 'Edit' });
      editBtn.addEventListener('click', () => openFazTargetModal(t));
      const delBtn = el('button', { class: 'btn btn-sm', text: 'Delete' });
      delBtn.addEventListener('click', () => deleteFazTarget(t.label));
      actions.appendChild(editBtn);
      actions.appendChild(delBtn);
      tr.appendChild(actions);
      tbody.appendChild(tr);
    });
  }

  async function loadFazTargets() {
    const resp = await fetch('/admin/api/faz-targets');
    state.fazTargets = await resp.json();
    renderFazTargets();
  }

  async function deleteFazTarget(label) {
    if (!confirm(`Delete FAZ target "${label}"?`)) return;
    await fetch(`/admin/api/faz-targets/${encodeURIComponent(label)}`, { method: 'DELETE' });
    await loadFazTargets();
  }

  function openFazTargetModal(target) {
    const modal = document.getElementById('fazTargetModal');
    document.getElementById('fazTargetModalMode').value = target ? 'edit' : 'create';
    document.getElementById('fazTargetModalOrigLabel').value = target ? target.label : '';
    document.getElementById('fazTargetModalTitle').textContent = target ? 'Edit FAZ Target' : 'New FAZ Target';
    document.getElementById('fazTargetLabelInput').value = target ? target.label : '';
    document.getElementById('fazTargetLabelInput').disabled = !!target;
    document.getElementById('fazTargetHostInput').value = target ? target.host : '';
    document.getElementById('fazTargetAdomInput').value = target ? target.adom : 'root';
    document.getElementById('fazTargetTokenInput').value = target ? target.token : '';
    document.getElementById('fazTargetModalError').classList.add('hidden');
    modal.classList.remove('hidden');
  }

  function closeFazTargetModal() {
    document.getElementById('fazTargetModal').classList.add('hidden');
  }

  async function saveFazTarget() {
    const mode = document.getElementById('fazTargetModalMode').value;
    const origLabel = document.getElementById('fazTargetModalOrigLabel').value;
    const label = document.getElementById('fazTargetLabelInput').value.trim();
    const host = document.getElementById('fazTargetHostInput').value.trim();
    const adom = document.getElementById('fazTargetAdomInput').value.trim() || 'root';
    const token = document.getElementById('fazTargetTokenInput').value.trim();

    const errBox = document.getElementById('fazTargetModalError');
    errBox.classList.add('hidden');

    let resp;
    if (mode === 'create') {
      resp = await fetch('/admin/api/faz-targets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ label, host, adom, token }),
      });
    } else {
      resp = await fetch(`/admin/api/faz-targets/${encodeURIComponent(origLabel)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ host, adom, token }),
      });
    }
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      errBox.textContent = body.error || 'Save failed.';
      errBox.classList.remove('hidden');
      return;
    }
    closeFazTargetModal();
    await loadFazTargets();
  }

  document.getElementById('btnNewFazTarget').addEventListener('click', () => openFazTargetModal(null));
  document.getElementById('fazTargetModalClose').addEventListener('click', closeFazTargetModal);
  document.getElementById('fazTargetModalCancel').addEventListener('click', closeFazTargetModal);
  document.getElementById('fazTargetModalSave').addEventListener('click', saveFazTarget);
```

Now extend `openGroupModal` to populate the target checkboxes and the restrict toggle (add after the existing `memberWrap` block, before `modal.classList.remove('hidden');`):

```javascript
    document.getElementById('groupAdomRestrictInput').checked = !!(group && group.adom_restrict);
    const targetWrap = document.getElementById('groupTargetCheckboxes');
    targetWrap.innerHTML = '';
    state.fazTargets.forEach((t) => {
      const label = el('label', { class: 'checkbox-item' });
      const input = el('input', { type: 'checkbox', value: t.label });
      input.checked = !!(group && group.allowed_adoms && group.allowed_adoms.includes(t.label));
      label.appendChild(input);
      label.appendChild(document.createTextNode(' ' + t.label));
      targetWrap.appendChild(label);
    });
```

And extend `saveGroup()` to send the two new fields — add these two lines alongside the existing `allowed_tabs`/`members` collection:

```javascript
    const adom_restrict = document.getElementById('groupAdomRestrictInput').checked;
    const allowed_adoms = Array.from(
      document.querySelectorAll('#groupTargetCheckboxes input:checked')
    ).map((i) => i.value);
```

and add `adom_restrict, allowed_adoms` to both the `create` and `edit` request bodies in `saveGroup()`, e.g. `body: JSON.stringify({ name, members, allowed_tabs, adom_restrict, allowed_adoms })` for create and `body: JSON.stringify({ members, allowed_tabs, adom_restrict, allowed_adoms })` for edit.

Finally, load FAZ targets during init — in the `init()` function, add `await loadFazTargets();` alongside the existing `await loadUsers(); await loadGroups();` calls (before `openGroupModal` can be invoked, since it now reads `state.fazTargets`).

- [ ] **Step 7: Manual smoke check**

Run: `uv run python wsgi.py` (with `.env`/`users.json`/`groups.json` set up per `readme.md`'s Quick start), log in as an admin, open Admin → FAZ Targets, add a target, edit it, delete it. Open Admin → Groups & Permissions, edit a group, confirm the "Restrict to specific FAZ targets" checkbox and target list appear and save correctly.

- [ ] **Step 8: Run the full test suite**

Run: `uv run pytest -q`
Expected: all tests PASS.

- [ ] **Step 9: Commit**

```bash
git add app/routes/admin_routes.py app/templates/admin.html app/static/js/admin.js tests/test_admin_routes.py
git commit -m "Add Admin FAZ Targets CRUD and group target-restriction UI"
```

---

### Task 7: Dashboard tab — health cards

**Files:**
- Modify: `app/routes/dashboard_routes.py`
- Modify: `app/templates/dashboard.html`
- Create: `app/static/js/dashboard.js`
- Test: `tests/test_tab_routes.py` (add to existing file)

**Interfaces:**
- Consumes: `app.faz_health_cache.get_all_cached()` (Task 4), `app.groups.get_allowed_adoms()` (existing, Phase 1).
- Produces: `GET /api/dashboard` JSON endpoint (list of card dicts, filtered by the requesting user's allowed targets).

- [ ] **Step 1: Write the failing route tests**

Append to `tests/test_tab_routes.py`:

```python
@pytest.fixture
def faz_dashboard_setup(tmp_path, monkeypatch):
    import app.faz_targets as faz_targets_mod
    import app.faz_health_cache as cache_mod

    monkeypatch.setattr(faz_targets_mod, "FAZ_TARGETS_FILE", tmp_path / "faz_targets.json")
    monkeypatch.setattr(cache_mod, "_cache", {})
    from app.faz_targets import create_target

    create_target("Primary", host="192.168.64.4", adom="root", token="tok")
    create_target("Secondary", host="192.168.64.5", adom="root", token="tok2")
    yield


def test_api_dashboard_requires_login(client, faz_dashboard_setup):
    resp = client.get("/api/dashboard")
    assert resp.status_code == 401


def test_api_dashboard_returns_all_targets_when_unrestricted(client, faz_dashboard_setup):
    _login(client)
    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    labels = [c["label"] for c in resp.get_json()]
    assert labels == ["Primary", "Secondary"]


def test_api_dashboard_filters_by_group_restriction(client, app, faz_dashboard_setup):
    import app.groups as groups_mod

    groups_mod.update_group(
        "g1", members=["alice"], allowed_tabs=["dashboard"], adom_restrict=True, allowed_adoms=["Primary"]
    )
    _login(client)
    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    labels = [c["label"] for c in resp.get_json()]
    assert labels == ["Primary"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tab_routes.py -v -k api_dashboard`
Expected: FAIL — `/api/dashboard` doesn't exist yet (404)

- [ ] **Step 3: Add the `/api/dashboard` route**

Replace the contents of `app/routes/dashboard_routes.py`:

```python
from flask import Blueprint, jsonify, render_template, session

from app import registry
from app.decorators import tab_required
from app.faz_health_cache import get_all_cached
from app.groups import get_allowed_adoms

bp = Blueprint("dashboard", __name__)

registry.register("dashboard", "Dashboard", "dashboard.index")


@bp.route("/")
@tab_required("dashboard")
def index():
    return render_template("dashboard.html", user=session["user"])


@bp.route("/api/dashboard")
@tab_required("dashboard")
def api_dashboard():
    ad_groups = session.get("ad_groups", [])
    allowed = get_allowed_adoms(session["user"], ad_groups=ad_groups, role=session.get("role"))
    cards = get_all_cached()
    if allowed is not None:
        cards = [c for c in cards if c["label"] in allowed]
    return jsonify(cards)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tab_routes.py -v -k api_dashboard`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Build the card grid template**

Replace `app/templates/dashboard.html`:

```html
{% extends "base.html" %}
{% block title %}Dashboard — 4tlog{% endblock %}
{% block content %}
<div class="page-header">
  <div>
    <h2>FortiAnalyzer Fleet Health</h2>
    <span class="last-updated" id="lastUpdated"></span>
  </div>
  <div class="page-header-actions">
    <select id="autoRefresh" class="form-select-sm">
      <option value="0">Manual</option>
      <option value="30">Every 30 sec</option>
      <option value="60" selected>Every 1 min</option>
      <option value="300">Every 5 min</option>
    </select>
    <button class="btn btn-primary" id="refreshBtn">&#8635; Refresh</button>
  </div>
</div>

<div class="card-grid" id="dashboardGrid">
  <div class="loading-placeholder">Loading FortiAnalyzer health…</div>
</div>
{% endblock %}

{% block scripts %}
<script src="{{ url_for('static', filename='js/dashboard.js') }}?v=1"></script>
{% endblock %}
```

- [ ] **Step 6: Write the dashboard JS**

Create `app/static/js/dashboard.js`:

```javascript
'use strict';

let refreshTimer = null;

function escHtml(str) {
  return String(str ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function renderCard(d) {
  const statusClass = `status-${d.status || 'gray'}`;

  const diskRow = d.disk_used && d.disk_used !== 'n/a'
    ? `<div class="card-row"><span class="card-row-label">Disk</span><span class="card-row-value">${escHtml(d.disk_used)}</span></div>`
    : '';

  let cpuMemRow;
  if (d.snmp_status && d.snmp_status !== 'ok') {
    const label = d.snmp_status === 'timeout' ? 'SNMP timeout'
      : d.snmp_status === 'disabled' ? 'SNMP disabled'
      : 'SNMP unreachable';
    cpuMemRow = `<div class="card-row"><span class="card-row-label">CPU / Mem</span><span class="card-row-value text-muted">${escHtml(label)}</span></div>`;
  } else if (d.cpu !== null && d.cpu !== undefined && d.mem !== null && d.mem !== undefined) {
    cpuMemRow = `<div class="card-row"><span class="card-row-label">CPU / Mem</span><span class="card-row-value">${d.cpu}% / ${d.mem}%</span></div>`;
  } else {
    cpuMemRow = '';
  }

  const errorRow = d.error
    ? `<div class="card-row card-row-error"><span class="card-row-value text-danger">${escHtml(d.error)}</span></div>`
    : '';

  return `
<div class="infra-card ${statusClass}">
  <div class="infra-card-stripe"></div>
  <div class="infra-card-body">
    <div class="card-name-block">
      <div class="card-title">${escHtml(d.label)}</div>
      <div class="card-subtitle">${escHtml(d.host)} &bull; ADOM ${escHtml(d.adom)}</div>
    </div>
    <div class="card-detail-block">
      <div class="card-col card-col-hostname">
        <div class="card-row"><span class="card-row-label">Hostname</span><span class="card-row-value">${escHtml(d.hostname)}</span></div>
      </div>
      <div class="card-col card-col-meta">
        <div class="card-row"><span class="card-row-label">Version</span><span class="card-row-value">${escHtml(d.version)}</span></div>
        <div class="card-row"><span class="card-row-label">Serial</span><span class="card-row-value">${escHtml(d.serial)}</span></div>
        <div class="card-row"><span class="card-row-label">HA Mode / Role</span><span class="card-row-value">${escHtml(d.ha_mode)} / ${escHtml(d.ha_role)}</span></div>
        ${cpuMemRow}
        ${diskRow}
      </div>
      ${errorRow}
    </div>
  </div>
</div>`;
}

async function loadDashboard() {
  const grid = document.getElementById('dashboardGrid');
  try {
    const resp = await fetch('/api/dashboard');
    if (resp.status === 401) { location.href = '/login'; return; }
    const data = await resp.json();
    if (!Array.isArray(data)) {
      grid.innerHTML = `<div class="alert alert-danger">Error: ${escHtml(JSON.stringify(data))}</div>`;
      return;
    }
    if (data.length === 0) {
      grid.innerHTML = '<div class="loading-placeholder">No FortiAnalyzer targets configured. Add one under Admin &rarr; FAZ Targets.</div>';
      return;
    }
    grid.innerHTML = data.map(renderCard).join('');
    document.getElementById('lastUpdated').textContent = 'Updated ' + new Date().toLocaleTimeString();
  } catch (err) {
    grid.innerHTML = `<div class="alert alert-danger">Failed to load: ${escHtml(err.message)}</div>`;
  }
}

function scheduleRefresh(seconds) {
  clearInterval(refreshTimer);
  if (seconds > 0) refreshTimer = setInterval(loadDashboard, seconds * 1000);
}

document.getElementById('refreshBtn').addEventListener('click', loadDashboard);
document.getElementById('autoRefresh').addEventListener('change', function () {
  scheduleRefresh(parseInt(this.value, 10));
});

loadDashboard();
scheduleRefresh(parseInt(document.getElementById('autoRefresh').value, 10));
```

- [ ] **Step 7: Add the `status-gray` CSS variant if missing**

Run: `grep -n "status-gray" app/static/css/style.css`

If the grep finds nothing (only `status-green`/`yellow`/`red` exist), add to `app/static/css/style.css` next to the existing `.infra-card.status-*` rules:

```css
.infra-card.status-offline .infra-card-stripe { background: #6b7280; }
```

(4thealth's CSS already has `.infra-card.status-gray` per the earlier grep in this repo's exploration — reuse it directly and additionally map the `offline` status this design uses to the same gray stripe, since "offline" and "gray"/"pending" read identically to a user glancing at the dashboard.)

- [ ] **Step 8: Manual smoke check**

Run: `uv run python wsgi.py`, log in, open the Dashboard tab with at least one FAZ target configured (via Admin → FAZ Targets from Task 6). Confirm a card renders, showing either real data (if `192.168.64.4` is reachable) or an offline/error card (if not) — either is an acceptable pass for this step; full live validation happens in Task 9.

- [ ] **Step 9: Run the full test suite**

Run: `uv run pytest -q`
Expected: all tests PASS.

- [ ] **Step 10: Commit**

```bash
git add app/routes/dashboard_routes.py app/templates/dashboard.html app/static/js/dashboard.js app/static/css/style.css tests/test_tab_routes.py
git commit -m "Add Dashboard tab health card grid"
```

---

### Task 8: Docker TLS — Nginx reverse proxy

**Files:**
- Modify: `docker-compose.yml`
- Create: `nginx/nginx.conf`
- Modify: `container.md`

**Interfaces:**
- None (infrastructure/deployment only, no Python interfaces).

- [ ] **Step 1: Write the Nginx config**

Create `nginx/nginx.conf`:

```nginx
server {
    listen 443 ssl;
    server_name _;

    ssl_certificate     /etc/nginx/certs/cert.pem;
    ssl_certificate_key /etc/nginx/certs/key.pem;

    location / {
        proxy_pass http://app:8100;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}

server {
    listen 80;
    server_name _;
    return 301 https://$host$request_uri;
}
```

(Same directive shape as the RHEL Nginx block in `docs/deployment.md` §5 — `proxy_pass` targets the `app` service name over the Docker Compose network instead of `127.0.0.1:8100`.)

- [ ] **Step 2: Add the nginx service to docker-compose.yml**

Replace `docker-compose.yml`:

```yaml
services:
  app:
    build: .
    image: 4tlog:latest
    container_name: 4tlog
    restart: unless-stopped
    expose:
      - "8100"
    env_file:
      - .env
      # TLS terminates at the nginx service below, so set in .env:
      #   COOKIE_SECURE=true
      #   TRUSTED_PROXY_COUNT=1
    volumes:
      - ./users.json:/app/users.json:rw
      - ./groups.json:/app/groups.json:rw
      - ./faz_targets.json:/app/faz_targets.json:rw
    healthcheck:
      test: ["CMD", "python3", "-c",
             "import urllib.request; urllib.request.urlopen('http://localhost:8100/login', timeout=5)"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s

  nginx:
    image: nginx:1.27-alpine
    container_name: 4tlog-nginx
    restart: unless-stopped
    depends_on:
      - app
    ports:
      - "8443:443"
      - "8080:80"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - ./certs:/etc/nginx/certs:ro
```

(`app` no longer publishes `8100` to the host — only `nginx` does, on `8443`/`8080`. `app` still listens on `8100` internally via `expose`, reachable from `nginx` over the default Compose network by service name.)

- [ ] **Step 3: Update container.md**

In `container.md`, replace the `## TLS` section (from `The container listens on plain HTTP...` through the `**Planned (Phase 2):**` paragraph) with:

```markdown
## TLS

An `nginx` service in front of `app` terminates TLS and proxies plain HTTP
to `app:8100` over the internal Docker network — `app` itself no longer
publishes a port to the host.

```bash
cp certs.example/cert.pem certs/cert.pem   # or your real cert
cp certs.example/key.pem certs/key.pem     # see note below
```

There's no `certs.example/` in this repo (certs aren't templatable the way
JSON config is) — for local/dev use, generate a self-signed pair:

```bash
mkdir -p certs
openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
  -keyout certs/key.pem -out certs/cert.pem \
  -subj "/CN=4tlog.local"
```

For production, replace `certs/cert.pem`/`certs/key.pem` with a real
certificate/key pair before `docker compose up`.

Set in `.env`:

```bash
COOKIE_SECURE=true
TRUSTED_PROXY_COUNT=1
```

`COOKIE_SECURE=auto` only detects local `certs/cert.pem`/`certs/key.pem`
from the `app` container's own filesystem — but in this topology TLS
terminates at `nginx`, so `app` never sees a cert on disk itself, and
`auto` would silently leave session cookies insecure. Same reasoning as
the RHEL/Nginx path in `docs/deployment.md` §5.

The app is reachable at `https://localhost:8443` (HTTP on `8080` redirects
to HTTPS).
```

Also update the "Quick sequence" section's `docker compose up -d` step — no change needed there, but add a note directly above it:

```markdown
cp certs.example... (see TLS section above for generating a cert first)
```

Actually, insert this as a distinct step in the Quick sequence, between the `groups.example.json` copy and `docker compose run --rm app uv run python manage_users.py add admin`:

```bash
# TLS cert — see the TLS section below for a self-signed option
mkdir -p certs
openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
  -keyout certs/key.pem -out certs/cert.pem -subj "/CN=4tlog.local"
```

- [ ] **Step 4: Manual smoke test**

Run: `cp .env.example .env` (fill in `SECRET_KEY` via `docker compose run --rm app uv run python manage_users.py secret`, set `COOKIE_SECURE=true` and `TRUSTED_PROXY_COUNT=1`), `cp users.example.json users.json`, `cp groups.example.json groups.json`, `cp faz_targets.example.json faz_targets.json`, generate a self-signed cert per the container.md steps above, `docker compose run --rm app uv run python manage_users.py add admin --role admin`, then `docker compose up -d`.

Run: `curl -k https://localhost:8443/login`
Expected: HTTP 200 with the login page HTML (confirms nginx terminates TLS and proxies to `app`).

Run: `curl -I http://localhost:8080/login`
Expected: HTTP 301 redirect to `https://localhost:8080/login` (note: the `Host` header reflects whatever port curl sent — cosmetic, not a bug for this smoke test).

Run: `docker compose down`

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml nginx/nginx.conf container.md
git commit -m "Add Docker TLS via Nginx reverse proxy"
```

---

### Task 9: Live validation, doc updates, and final smoke test

**Files:**
- Modify: `CLAUDE.md`
- Modify: `readme.md`

**Interfaces:**
- None — this task validates the whole phase against the real test appliance and brings docs in line with what shipped.

- [ ] **Step 1: Live-validate `faz_client.get_sys_status()` against the test appliance**

Write a throwaway script (do not commit) or use `uv run python -c`:

```bash
uv run python -c "
from app.faz_client import FAZClient
with FAZClient(host='192.168.64.4', token='YOUR_TEST_TOKEN', adom='root', verify_ssl=False) as c:
    c.preflight()
    print(c.get_sys_status())
"
```

Expected: prints a dict with real hostname/version/serial data — no `FAZError`. If the field names differ from what `app/faz_health_cache.py`'s `_poll_target()` expects (`hostname`, `version`, `serial`, `ha-mode`/`ha_mode`, `ha-role`/`ha_role`, `disk-usage`/`disk_usage`), update `_poll_target()`'s field lookups to match the real response and re-run `uv run pytest tests/test_faz_health_cache.py -v` to confirm the mocked tests still encode the corrected field names.

- [ ] **Step 2: Spot-check SNMP if exercising it**

If setting `SNMP_ENABLED=true` for real use, run:

```bash
snmpwalk -v3 -u <user> -l authPriv -a SHA -A <auth_key> -x AES -X <priv_key> 192.168.64.4 1.3.6.1.4.1.12356.103.2.1
```

Expected: returns CPU/mem-used/mem-total OIDs with plausible values, confirming the OIDs ported from 4thealth (Task 4) match this appliance's firmware.

- [ ] **Step 3: End-to-end Docker smoke test**

Repeat Task 8 Step 4's `docker compose up -d` sequence, then in the browser: log in, open Admin → FAZ Targets, add the real test target (`192.168.64.4`, real token), open the Dashboard tab, confirm a live health card renders (not just an offline card). `docker compose down` when done.

- [ ] **Step 4: Update CLAUDE.md**

Read the current `CLAUDE.md` and update it to describe the Phase 2 additions: `app/faz_client.py`, `app/faz_health_cache.py`, `app/faz_targets.py`, the Dashboard tab's real behavior, the Admin FAZ Targets sub-tab, and the Docker TLS/Nginx setup — following the same style as the existing Phase 1 content (concrete file references, not generic prose). Since the current `CLAUDE.md` still describes the pre-Flask Ansible-only state of the repo, this update should bring it fully in line with the current app structure, not just append a Phase 2 section.

- [ ] **Step 5: Update readme.md**

In `readme.md`, update the "Current features" section to move Dashboard from "placeholder" to a real feature (health cards, FAZ Targets admin, Docker TLS), matching the language already used for Phase 1's Admin tab bullet.

- [ ] **Step 6: Final full-suite run**

Run: `uv run pytest -q && uv run ruff check .`
Expected: all tests PASS, no lint errors.

- [ ] **Step 7: Commit**

```bash
git add CLAUDE.md readme.md
git commit -m "Update docs for Phase 2: Dashboard, FAZ Targets, Docker TLS"
```

---

## Self-Review Notes

- **Spec coverage:** Dashboard health cards (Task 7), `faz_client.py` scoped to health methods only (Task 3, explicitly excludes `search_logs`), `faz_health_cache.py` with confirmed FAZ SNMP OIDs (Task 4), `faz_targets.json` + admin CRUD (Tasks 2, 6), group-based target restriction reusing existing `adom_restrict`/`allowed_adoms` (Task 6), Docker TLS via Nginx (Task 8), live validation against `192.168.64.4` (Task 9) — all covered.
- **Type consistency:** `get_all_cached()` (Task 4) returns dicts with keys `label`/`host`/`adom`/`status`/`hostname`/`version`/`serial`/`ha_mode`/`ha_role`/`disk_used`/`cpu`/`mem`/`snmp_status`/`error`/`last_updated` — matched exactly by `dashboard.js`'s `renderCard()` (Task 7) and the `/api/dashboard` tests (Task 7 Step 1).
- **No placeholders:** every task has runnable code, not descriptions of code.
