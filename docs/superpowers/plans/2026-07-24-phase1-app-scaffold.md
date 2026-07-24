# 4tlog Phase 1: App Scaffold, Auth & Admin Shell — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a working Flask web app for 4tlog with local bcrypt authentication, group-based tab permissions, a tab registry, and an Admin shell (Users list, Groups CRUD, Logs viewer) — plus Docker and RHEL deployment packaging. Dashboard and Log Search tabs exist as placeholder pages registered in the nav; their real FAZ-backed content is built in later phases.

**Architecture:** Direct structural port of `/Users/alanw/code/github/web/4thealth`'s Flask app factory pattern (blueprints self-register nav tabs via `app/registry.py`; `app/decorators.py` enforces `login_required`/`tab_required`/`admin_required`; `app/groups.py` resolves tab access from `groups.json`; `app/auth.py` does bcrypt auth against `users.json`). RADIUS/AD, FAZ targets, ADOM restriction UI, and background health polling are deliberately deferred to later phases — this phase only needs the local-auth + tab-registry skeleton to exist and be provably correct.

**Tech Stack:** Python 3.11+, Flask 3.x, bcrypt, python-dotenv, pytest, ruff, uv (dependency manager), Gunicorn (prod), Docker.

## Global Constraints

- Python `>=3.11` (matches 4thealth's `pyproject.toml` floor).
- Dependency management via `uv` — `uv.lock` and `pyproject.toml` both committed; never `pip install` directly.
- Project/package name is `4tlog` everywhere a name is needed (page titles, Docker image name, systemd unit name) — do not carry over "4thealth" branding.
- `SECRET_KEY` must be read from `.env` and the app must refuse to start with an empty or placeholder value (same `_require_secret_key()` guard as 4thealth).
- `users.json`, `groups.json`, `.env`, and `certs/` are gitignored runtime data; every one of them ships a committed `*.example.*` template.
- HTTPS auto-enables when `certs/cert.pem` + `certs/key.pem` exist; falls back to plain HTTP otherwise (dev convenience, matches 4thealth's `wsgi.py`).
- CSRF protection (double-submit token via `X-CSRF-Token` header) applies to all state-changing (`POST`/`PUT`/`PATCH`/`DELETE`) requests except none in this phase (no bearer-token routes exist yet).
- No new tab, route, or JSON file may be added without a matching `*.example.*` template and a `.gitignore` entry for the real file.

---

### Task 1: Project scaffolding, dependencies, and directory layout

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `.gitignore` (extend existing repo `.gitignore` — check first, see Step 1)
- Create: `app/__init__.py` (empty placeholder — populated in Task 9)
- Create: `app/routes/__init__.py` (empty)
- Create: `tests/__init__.py` (empty)
- Create: `tests/conftest.py`

**Interfaces:**
- Produces: a `uv sync`-able project with `pytest` runnable via `uv run pytest`.

- [ ] **Step 1: Inspect the existing `.gitignore`**

Run: `cat /Users/alanw/code/github/web/4tlog/.gitignore`

Confirm it does not already track `.venv/`, `__pycache__/`, `*.pyc`, `.env`, `certs/`, `users.json`, `groups.json`. Note what's missing — you'll append it in Step 3.

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "4tlog"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "flask>=3.0,<4",
    "python-dotenv>=1.0",
    "bcrypt>=4.1",
]

[project.optional-dependencies]
prod = ["gunicorn>=22"]

[tool.uv]
package = false

[dependency-groups]
dev = [
    "pytest>=8.0",
    "ruff>=0.15",
]
```

- [ ] **Step 3: Append missing entries to `.gitignore`**

Add any of these not already present:
```
.venv/
__pycache__/
*.pyc
.env
certs/
users.json
groups.json
.pytest_cache/
.ruff_cache/
```

- [ ] **Step 4: Write `.env.example`**

```
# Copy this file to .env and fill in your values.
# .env is git-ignored — never commit it.

# Generate with: uv run python manage_users.py secret
SECRET_KEY=

# auto = set Secure cookie flag when TLS certs are present (recommended)
COOKIE_SECURE=auto

# Listening port — auto-selects 5443 when TLS certs are present, 5000 otherwise
# PORT=5000

# TLS certificate paths (relative to project root)
# SSL_CERT=certs/cert.pem
# SSL_KEY=certs/key.pem

# Set to the number of trusted reverse proxies in front of this app (e.g. 1 for nginx).
# TRUSTED_PROXY_COUNT=1
```

- [ ] **Step 5: Create empty package files**

```bash
mkdir -p app/routes tests
touch app/__init__.py app/routes/__init__.py tests/__init__.py
```

- [ ] **Step 6: Write `tests/conftest.py`**

```python
import os
import sys
from pathlib import Path

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci")
sys.path.insert(0, str(Path(__file__).parent.parent))
```

- [ ] **Step 7: Install dependencies and verify**

Run: `cd /Users/alanw/code/github/web/4tlog && uv sync`
Expected: creates `.venv/` and `uv.lock` with no errors.

Run: `uv run pytest`
Expected: `no tests ran` (no test files yet) — exits 0, confirms pytest is wired up.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock .env.example .gitignore app tests
git commit -m "Scaffold 4tlog Flask project structure and dependencies"
```

---

### Task 2: Config module

**Files:**
- Create: `app/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `.env` via `python-dotenv`.
- Produces: `app.config.Config` class with attributes `SECRET_KEY`, `SESSION_COOKIE_HTTPONLY`, `SESSION_COOKIE_SAMESITE`, `SESSION_COOKIE_SECURE`, `PERMANENT_SESSION_LIFETIME`, `SESSION_ABSOLUTE_LIFETIME`, `MAX_CONTENT_LENGTH`. Later tasks (`app/__init__.py`) do `app.config.from_object(Config)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import importlib
import os


def test_config_requires_secret_key(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    import app.config as config_mod
    with __import__("pytest").raises(RuntimeError):
        importlib.reload(config_mod)
    # restore for subsequent tests in the same process
    os.environ["SECRET_KEY"] = "test-secret-key-for-ci"
    importlib.reload(config_mod)


def test_config_loads_defaults(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "a-real-secret")
    import app.config as config_mod
    importlib.reload(config_mod)
    assert config_mod.Config.SECRET_KEY == "a-real-secret"
    assert config_mod.Config.SESSION_COOKIE_HTTPONLY is True
    assert config_mod.Config.PERMANENT_SESSION_LIFETIME == 3600
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.config'`

- [ ] **Step 3: Write `app/config.py`**

```python
"""Application configuration loaded from environment / .env file."""

import os
from dotenv import load_dotenv

load_dotenv()


def _require_secret_key() -> str:
    val = os.environ.get("SECRET_KEY", "")
    if not val or val == "change-me-in-production":
        raise RuntimeError(
            "SECRET_KEY is not set or is the insecure default. "
            "Generate one with: uv run python manage_users.py secret"
        )
    return val


class Config:
    SECRET_KEY = _require_secret_key()
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    _ssl_active = os.path.exists(
        os.environ.get("SSL_CERT", "certs/cert.pem")
    ) and os.path.exists(os.environ.get("SSL_KEY", "certs/key.pem"))
    SESSION_COOKIE_SECURE = os.environ.get(
        "COOKIE_SECURE", "auto"
    ).lower() == "true" or (
        os.environ.get("COOKIE_SECURE", "auto").lower() == "auto" and _ssl_active
    )
    PERMANENT_SESSION_LIFETIME = 3600  # 1 hour
    SESSION_ABSOLUTE_LIFETIME = int(
        os.environ.get("SESSION_ABSOLUTE_LIFETIME", str(10 * 3600))
    )  # 10 h
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", str(4 * 1024 * 1024)))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "Add Config module for env-based settings"
```

---

### Task 3: App logger (in-memory ring buffer)

**Files:**
- Create: `app/app_logger.py`
- Test: `tests/test_app_logger.py`

**Interfaces:**
- Produces: `app_log(level, component, message, **extra)`, `set_log_level(level)`, `get_log_level()`, `get_log_levels()`, `get_log_entries(level=None, component=None, limit=500) -> list[dict]`, `clear_log_entries()`. Consumed by `admin_routes.py` (Task 12) and any route wanting structured logging.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_app_logger.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_app_logger.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.app_logger'`

- [ ] **Step 3: Write `app/app_logger.py`**

```python
"""Application-level logging with an in-memory ring buffer.

Log levels: TRACE  DEBUG  INFO  WARN  ERROR

Usage:
    from app.app_logger import app_log, set_log_level, get_log_entries
    app_log("INFO", "auth", "User logged in", username="admin")
"""

import threading
from collections import deque
from datetime import datetime, timezone

_LEVELS = ["TRACE", "DEBUG", "INFO", "WARN", "ERROR"]
_LEVEL_RANK = {lvl: i for i, lvl in enumerate(_LEVELS)}

_MAX_ENTRIES = 2000
_buffer: deque = deque(maxlen=_MAX_ENTRIES)
_lock = threading.Lock()
_current_level = "INFO"


def set_log_level(level: str) -> None:
    global _current_level
    level = level.upper()
    if level not in _LEVEL_RANK:
        raise ValueError(
            f"Invalid log level '{level}'. Choose from: {', '.join(_LEVELS)}"
        )
    _current_level = level


def get_log_level() -> str:
    return _current_level


def get_log_levels() -> list[str]:
    return list(_LEVELS)


def app_log(level: str, component: str, message: str, **extra) -> None:
    level = level.upper()
    if _LEVEL_RANK.get(level, 0) < _LEVEL_RANK.get(_current_level, 0):
        return
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "level": level,
        "component": component,
        "message": message,
    }
    if extra:
        entry["extra"] = extra
    with _lock:
        _buffer.append(entry)


def get_log_entries(
    level: str | None = None, component: str | None = None, limit: int = 500
) -> list[dict]:
    with _lock:
        entries = list(_buffer)
    if level:
        rank = _LEVEL_RANK.get(level.upper(), 0)
        entries = [e for e in entries if _LEVEL_RANK.get(e["level"], 0) >= rank]
    if component:
        entries = [e for e in entries if e["component"] == component]
    return entries[-limit:]


def clear_log_entries() -> None:
    with _lock:
        _buffer.clear()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_app_logger.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add app/app_logger.py tests/test_app_logger.py
git commit -m "Add in-memory ring-buffer app logger"
```

---

### Task 4: CSRF and API error helpers

**Files:**
- Create: `app/security.py`
- Test: `tests/test_security.py`

**Interfaces:**
- Consumes: `app.app_logger.app_log` (Task 3).
- Produces: `ensure_csrf_token() -> str`, `validate_csrf_request() -> bool`, `csrf_error_response()`, `internal_api_error(component, exc, status=500)`, `upstream_api_error(component, exc)`. Consumed by `app/__init__.py` (Task 9).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_security.py
import pytest
from flask import Flask
from app.security import ensure_csrf_token, validate_csrf_request


@pytest.fixture
def app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test"
    return app


def test_ensure_csrf_token_persists_in_session(app):
    with app.test_request_context("/"):
        token1 = ensure_csrf_token()
        token2 = ensure_csrf_token()
        assert token1 == token2
        assert len(token1) > 20


def test_validate_csrf_request_accepts_matching_header(app):
    with app.test_request_context(
        "/", headers={}, method="POST"
    ):
        token = ensure_csrf_token()
    with app.test_request_context(
        "/", method="POST", headers={"X-CSRF-Token": token}
    ) as ctx:
        from flask import session
        session["_csrf_token"] = token
        assert validate_csrf_request() is True


def test_validate_csrf_request_rejects_missing_token(app):
    with app.test_request_context("/", method="POST"):
        assert validate_csrf_request() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_security.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.security'`

- [ ] **Step 3: Write `app/security.py`**

```python
"""Security helpers for CSRF and safe API error responses."""

from __future__ import annotations

import hmac
import secrets
import uuid

from flask import jsonify, request, session

from app.app_logger import app_log


def ensure_csrf_token() -> str:
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def validate_csrf_request() -> bool:
    expected = session.get("_csrf_token", "")
    if not expected:
        return False
    provided = (
        request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or ""
    )
    return hmac.compare_digest(expected, provided)


def csrf_error_response():
    if request.path.startswith("/api/") or request.path.startswith("/admin/api/"):
        return jsonify({"error": "CSRF validation failed"}), 400
    return "CSRF validation failed", 400


def _error_id() -> str:
    return uuid.uuid4().hex[:12]


def internal_api_error(component: str, exc: Exception, status: int = 500):
    eid = _error_id()
    app_log(
        "ERROR", component, "Internal API error",
        error_id=eid, exc_type=type(exc).__name__, exc=str(exc),
        path=request.path, method=request.method,
    )
    return jsonify({"error": "Internal server error", "error_id": eid}), status


def upstream_api_error(component: str, exc: Exception):
    eid = _error_id()
    app_log(
        "WARN", component, "Upstream request failed",
        error_id=eid, exc_type=type(exc).__name__, exc=str(exc),
        path=request.path, method=request.method,
    )
    return jsonify({"error": "Upstream request failed", "error_id": eid}), 502
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_security.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/security.py tests/test_security.py
git commit -m "Add CSRF token and API error helpers"
```

---

### Task 5: Tab registry

**Files:**
- Create: `app/registry.py`
- Test: `tests/test_registry.py`

**Interfaces:**
- Produces: `register(key, name, endpoint, icon="")`, `get_registry() -> dict[str, dict]`, `known_tabs() -> dict[str, str]`. Consumed by every route blueprint (Tasks 10, 11, 12) and by `app/groups.py` (Task 7) via `KNOWN_TABS` sync in `app/__init__.py` (Task 9).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_registry.py
from app import registry


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.registry'`

- [ ] **Step 3: Write `app/registry.py`**

```python
"""Navigation tab registry — single source of truth for nav metadata.

Each blueprint self-registers at import time:

    from app import registry
    registry.register("my_tab", "My Tab", "myblueprint.myview")

The app factory then injects ``nav_registry`` into every template and
syncs ``groups.KNOWN_TABS`` from this registry.
"""

from __future__ import annotations

_registry: dict[str, dict] = {}


def register(key: str, name: str, endpoint: str, icon: str = "") -> None:
    _registry[key] = {"name": name, "endpoint": endpoint, "icon": icon}


def get_registry() -> dict[str, dict]:
    return dict(_registry)


def known_tabs() -> dict[str, str]:
    return {k: v["name"] for k, v in _registry.items()}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_registry.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/registry.py tests/test_registry.py
git commit -m "Add tab registry module"
```

---

### Task 6: Local bcrypt auth + user management CLI

**Files:**
- Create: `app/auth.py`
- Create: `manage_users.py`
- Create: `users.example.json`
- Test: `tests/test_auth.py`

**Interfaces:**
- Produces: `authenticate(username, password) -> tuple[str, list] | None`, `validate_password_policy(password)`, `add_user(username, password, role="viewer")`, `delete_user(username) -> bool`, `list_users() -> list[dict]`, `get_user_role(username) -> str`, `generate_secret_key() -> str`, `_load_users() -> dict` (used by `decorators.py` in Task 8 and `groups.py` in Task 7).
- Consumes: nothing from earlier tasks (self-contained; `USERS_FILE` path is relative to project root).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auth.py
import json
import pytest


@pytest.fixture
def users_file(tmp_path, monkeypatch):
    path = tmp_path / "users.json"
    import app.auth as auth_mod
    monkeypatch.setattr(auth_mod, "USERS_FILE", path)
    return path


def test_add_user_hashes_password(users_file):
    from app.auth import add_user, list_users
    add_user("alice", "Str0ng!Passw0rd", role="admin")
    users = list_users()
    assert users == [{"username": "alice", "role": "admin"}]
    data = json.loads(users_file.read_text())
    assert data["alice"]["password_hash"] != "Str0ng!Passw0rd"


def test_authenticate_success_and_failure(users_file):
    from app.auth import add_user, authenticate
    add_user("bob", "Str0ng!Passw0rd", role="viewer")
    assert authenticate("bob", "Str0ng!Passw0rd") == ("viewer", [])
    assert authenticate("bob", "wrong-password") is None
    assert authenticate("nobody", "whatever") is None


def test_delete_user(users_file):
    from app.auth import add_user, delete_user, list_users
    add_user("carol", "Str0ng!Passw0rd")
    assert delete_user("carol") is True
    assert delete_user("carol") is False
    assert list_users() == []


def test_validate_password_policy_rejects_weak_passwords():
    from app.auth import validate_password_policy
    with pytest.raises(ValueError):
        validate_password_policy("short")
    with pytest.raises(ValueError):
        validate_password_policy("alllowercase123!")
    validate_password_policy("Str0ng!Passw0rd")  # should not raise


def test_generate_secret_key_is_64_hex_chars():
    from app.auth import generate_secret_key
    key = generate_secret_key()
    assert len(key) == 64
    int(key, 16)  # raises if not valid hex
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.auth'`

- [ ] **Step 3: Write `app/auth.py`**

```python
"""Local user authentication — bcrypt hashed passwords stored in users.json."""

import json
import secrets
import string
from pathlib import Path

import bcrypt

USERS_FILE = Path(__file__).parent.parent / "users.json"


def _load_users() -> dict:
    if not USERS_FILE.exists():
        return {}
    with USERS_FILE.open() as f:
        return json.load(f)


def authenticate(username: str, password: str) -> "tuple[str, list] | None":
    """Return (role, ad_groups) on success, None on failure.

    ad_groups is always [] in Phase 1 (no RADIUS/AD integration yet) —
    kept in the return shape so decorators.py doesn't need to change
    when RADIUS is added later.
    """
    users = _load_users()
    entry = users.get(username)
    if not entry:
        return None
    stored_hash = entry.get("password_hash", "")
    if bcrypt.checkpw(password.encode(), stored_hash.encode()):
        return entry.get("role", "viewer"), []
    return None


def validate_password_policy(password: str) -> None:
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters long")
    if not any(c.islower() for c in password):
        raise ValueError("Password must include at least one lowercase letter")
    if not any(c.isupper() for c in password):
        raise ValueError("Password must include at least one uppercase letter")
    if not any(c.isdigit() for c in password):
        raise ValueError("Password must include at least one number")
    if not any(c in string.punctuation for c in password):
        raise ValueError("Password must include at least one special character")


def add_user(username: str, password: str, role: str = "viewer") -> None:
    validate_password_policy(password)
    users = _load_users()
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    users[username] = {"password_hash": hashed, "role": role}
    with USERS_FILE.open("w") as f:
        json.dump(users, f, indent=2)


def delete_user(username: str) -> bool:
    users = _load_users()
    if username not in users:
        return False
    del users[username]
    with USERS_FILE.open("w") as f:
        json.dump(users, f, indent=2)
    return True


def list_users() -> list:
    return [
        {"username": u, "role": v.get("role", "viewer")}
        for u, v in _load_users().items()
    ]


def get_user_role(username: str) -> str:
    users = _load_users()
    return users.get(username, {}).get("role", "viewer")


def generate_secret_key() -> str:
    return secrets.token_hex(32)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_auth.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Write `manage_users.py`**

```python
#!/usr/bin/env python3
"""CLI tool to manage local user accounts stored in users.json."""

import argparse
import sys


def cmd_add(args):
    from app.auth import add_user
    import getpass

    password = args.password or getpass.getpass(f"Password for {args.username}: ")
    if not password:
        print("Password cannot be empty.", file=sys.stderr)
        sys.exit(1)
    try:
        add_user(args.username, password, args.role)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    print(f"User '{args.username}' added with role '{args.role}'.")


def cmd_delete(args):
    from app.auth import delete_user

    if delete_user(args.username):
        print(f"User '{args.username}' deleted.")
    else:
        print(f"User '{args.username}' not found.", file=sys.stderr)
        sys.exit(1)


def cmd_list(_):
    from app.auth import list_users

    users = list_users()
    if not users:
        print("No users configured.")
        return
    print(f"{'Username':<20} {'Role':<10}")
    print("-" * 30)
    for u in users:
        print(f"{u['username']:<20} {u['role']:<10}")


def cmd_secret(_):
    from app.auth import generate_secret_key

    key = generate_secret_key()
    print(f"Generated SECRET_KEY:\n{key}")
    print("\nAdd this to your .env file as:\nSECRET_KEY=" + key)


parser = argparse.ArgumentParser(description="4tlog user management")
sub = parser.add_subparsers(dest="command", required=True)

p_add = sub.add_parser("add", help="Add or update a user")
p_add.add_argument("username")
p_add.add_argument("--password", default=None, help="Password (prompted if omitted)")
p_add.add_argument("--role", default="viewer", choices=["viewer", "admin"])
p_add.set_defaults(func=cmd_add)

p_del = sub.add_parser("delete", help="Delete a user")
p_del.add_argument("username")
p_del.set_defaults(func=cmd_delete)

p_list = sub.add_parser("list", help="List all users")
p_list.set_defaults(func=cmd_list)

p_secret = sub.add_parser("secret", help="Generate a random SECRET_KEY")
p_secret.set_defaults(func=cmd_secret)

if __name__ == "__main__":
    args = parser.parse_args()
    args.func(args)
```

- [ ] **Step 6: Write `users.example.json`**

```json
{
  "admin": {
    "password_hash": "REPLACE_ME - generate accounts with: uv run python manage_users.py add admin --role admin",
    "role": "admin"
  }
}
```

- [ ] **Step 7: Run full test suite to verify no regressions**

Run: `uv run pytest -v`
Expected: all previous tests plus the 5 new `test_auth.py` tests PASS.

- [ ] **Step 8: Commit**

```bash
git add app/auth.py manage_users.py users.example.json tests/test_auth.py
git commit -m "Add local bcrypt auth and user management CLI"
```

---

### Task 7: Groups (tab permissions)

**Files:**
- Create: `app/groups.py`
- Create: `groups.example.json`
- Test: `tests/test_groups.py`

**Interfaces:**
- Consumes: `app.auth._load_users` (Task 6).
- Produces: `list_groups()`, `get_group(name)`, `create_group(name, members=None, ad_groups=None, allowed_tabs=None, adom_restrict=False, allowed_adoms=None) -> bool`, `update_group(name, members, allowed_tabs, adom_restrict=False, allowed_adoms=None, ad_groups=None) -> bool`, `delete_group(name) -> bool`, `get_allowed_tabs(username, ad_groups=None, role=None) -> set[str]`, `user_can_access_tab(username, tab_key) -> bool`, module-level mutable `KNOWN_TABS: dict[str, str]` (populated by `app/__init__.py` in Task 9 from `registry.known_tabs()`). `get_allowed_adoms`/`user_can_access_adom` are included now (schema parity with `adom_restrict`/`allowed_adoms` fields) even though no ADOM-scoped routes exist until Phase 2 — cheap to keep, avoids a breaking `groups.json` schema change later.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_groups.py
import pytest


@pytest.fixture
def groups_file(tmp_path, monkeypatch):
    path = tmp_path / "groups.json"
    import app.groups as groups_mod
    monkeypatch.setattr(groups_mod, "GROUPS_FILE", path)
    groups_mod.KNOWN_TABS = {"dashboard": "Dashboard", "log_search": "Log Search", "admin": "Admin"}
    yield path
    groups_mod.KNOWN_TABS = {}


@pytest.fixture
def no_users(monkeypatch):
    import app.auth as auth_mod
    monkeypatch.setattr(auth_mod, "_load_users", lambda: {})


def test_create_list_get_group(groups_file, no_users):
    from app.groups import create_group, list_groups, get_group
    assert create_group("noc", members=["alice"], allowed_tabs=["dashboard"]) is True
    assert create_group("noc", allowed_tabs=["dashboard"]) is False  # duplicate
    assert [g["name"] for g in list_groups()] == ["noc"]
    g = get_group("noc")
    assert g["members"] == ["alice"]
    assert g["allowed_tabs"] == ["dashboard"]
    assert g["adom_restrict"] is False


def test_update_group_filters_unknown_tabs(groups_file, no_users):
    from app.groups import create_group, update_group, get_group
    create_group("noc", allowed_tabs=["dashboard"])
    ok = update_group("noc", members=["bob"], allowed_tabs=["dashboard", "bogus_tab"])
    assert ok is True
    g = get_group("noc")
    assert g["allowed_tabs"] == ["dashboard"]  # bogus_tab filtered out
    assert g["members"] == ["bob"]


def test_update_group_missing_returns_false(groups_file, no_users):
    from app.groups import update_group
    assert update_group("ghost", members=[], allowed_tabs=[]) is False


def test_delete_group(groups_file, no_users):
    from app.groups import create_group, delete_group
    create_group("noc", allowed_tabs=["dashboard"])
    assert delete_group("noc") is True
    assert delete_group("noc") is False


def test_get_allowed_tabs_union_across_groups(groups_file, no_users):
    from app.groups import create_group, get_allowed_tabs
    create_group("g1", members=["alice"], allowed_tabs=["dashboard"])
    create_group("g2", members=["alice"], allowed_tabs=["log_search"])
    assert get_allowed_tabs("alice") == {"dashboard", "log_search"}


def test_get_allowed_tabs_admin_role_gets_everything(groups_file, no_users):
    from app.groups import get_allowed_tabs
    assert get_allowed_tabs("whoever", role="admin") == {"dashboard", "log_search", "admin"}


def test_get_allowed_tabs_no_membership_is_empty(groups_file, no_users):
    from app.groups import get_allowed_tabs
    assert get_allowed_tabs("nobody") == set()


def test_user_can_access_tab(groups_file, no_users):
    from app.groups import create_group, user_can_access_tab
    create_group("g1", members=["alice"], allowed_tabs=["dashboard"])
    assert user_can_access_tab("alice", "dashboard") is True
    assert user_can_access_tab("alice", "admin") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_groups.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.groups'`

- [ ] **Step 3: Write `app/groups.py`**

```python
"""Group management — local store backed by groups.json.

A group has:
  name           str   unique identifier
  members        list  of local username strings (users.json accounts)
  ad_groups      list  of AD/RADIUS group name strings (reserved for a future
                       RADIUS/AD integration; unused while RADIUS_ENABLED stays
                       false, but kept in the schema so groups.json does not
                       need a breaking migration later)
  allowed_tabs   list  of tab keys (see KNOWN_TABS)
  adom_restrict  bool  when True, only ADOMs/targets in allowed_adoms are
                       accessible (reserved for Phase 2's FAZ-target access
                       control; unused by any route in Phase 1)
  allowed_adoms  list  of ADOM/target name strings (only used when
                       adom_restrict=True)

Tab keys are the canonical identifiers the nav uses. When a new route/tab is
added to the app, register it via app.registry.register() — it will appear
automatically in KNOWN_TABS once app/__init__.py syncs the registry.
"""

import json
import threading
from pathlib import Path

GROUPS_FILE = Path(__file__).parent.parent / "groups.json"
_lock = threading.Lock()

# Populated at startup by app/__init__.py from app.registry.
KNOWN_TABS: dict[str, str] = {}


def _load() -> dict:
    if not GROUPS_FILE.exists():
        return {}
    with GROUPS_FILE.open() as f:
        return json.load(f)


def _save(data: dict) -> None:
    with GROUPS_FILE.open("w") as f:
        json.dump(data, f, indent=2)


def _group_to_dict(name: str, g: dict) -> dict:
    return {
        "name": name,
        "members": g.get("members", []),
        "ad_groups": g.get("ad_groups", []),
        "allowed_tabs": g.get("allowed_tabs", []),
        "adom_restrict": bool(g.get("adom_restrict", False)),
        "allowed_adoms": g.get("allowed_adoms", []),
    }


def list_groups() -> list[dict]:
    with _lock:
        groups = _load()
    return [_group_to_dict(name, g) for name, g in groups.items()]


def get_group(name: str) -> dict | None:
    with _lock:
        groups = _load()
    g = groups.get(name)
    if g is None:
        return None
    return _group_to_dict(name, g)


def create_group(
    name: str,
    members: list[str] | None = None,
    ad_groups: list[str] | None = None,
    allowed_tabs: list[str] | None = None,
    adom_restrict: bool = False,
    allowed_adoms: list[str] | None = None,
) -> bool:
    """Returns False if the group name already exists."""
    name = name.strip()
    if not name:
        raise ValueError("Group name cannot be empty.")
    with _lock:
        groups = _load()
        if name in groups:
            return False
        groups[name] = {
            "members": list(members or []),
            "ad_groups": list(ad_groups or []),
            "allowed_tabs": list(allowed_tabs or []),
            "adom_restrict": bool(adom_restrict),
            "allowed_adoms": list(allowed_adoms or []),
        }
        _save(groups)
    return True


def update_group(
    name: str,
    members: list[str],
    allowed_tabs: list[str],
    adom_restrict: bool = False,
    allowed_adoms: list[str] | None = None,
    ad_groups: list[str] | None = None,
) -> bool:
    """Returns False if the group does not exist."""
    with _lock:
        groups = _load()
        if name not in groups:
            return False
        groups[name]["members"] = list(members)
        groups[name]["ad_groups"] = list(ad_groups or [])
        if KNOWN_TABS:
            groups[name]["allowed_tabs"] = [t for t in allowed_tabs if t in KNOWN_TABS]
        else:
            groups[name]["allowed_tabs"] = list(allowed_tabs)
        groups[name]["adom_restrict"] = bool(adom_restrict)
        groups[name]["allowed_adoms"] = list(allowed_adoms or [])
        _save(groups)
    return True


def delete_group(name: str) -> bool:
    with _lock:
        groups = _load()
        if name not in groups:
            return False
        del groups[name]
        _save(groups)
    return True


def get_allowed_tabs(
    username: str, ad_groups: list[str] | None = None, role: str | None = None
) -> set[str]:
    """Return the set of tab keys the user may access.

    - Admins always get all currently-registered tabs.
    - Non-admins get the union of allowed_tabs across all groups they belong to
      (membership by username in group['members'] OR ad_groups overlap).
    - Users in no group get no tabs.
    """
    from app.auth import _load_users

    if role == "admin":
        return set(KNOWN_TABS.keys())

    users = _load_users()
    user_entry = users.get(username, {})
    if user_entry.get("role") == "admin":
        return set(KNOWN_TABS.keys())

    with _lock:
        groups = _load()

    ad_set = set(ad_groups or [])
    tabs: set[str] = set()
    for g in groups.values():
        if username in g.get("members", []) or ad_set & set(g.get("ad_groups", [])):
            tabs.update(g.get("allowed_tabs", []))
    return tabs


def user_can_access_tab(username: str, tab_key: str) -> bool:
    return tab_key in get_allowed_tabs(username)


def get_allowed_adoms(
    username: str, ad_groups: list[str] | None = None, role: str | None = None
) -> list[str] | None:
    """Return the list of ADOM/target names the user may access, or None for
    unrestricted. Not consumed by any route until Phase 2, but implemented
    now so groups.json's schema is stable across phases.
    """
    from app.auth import _load_users

    if role == "admin":
        return None

    users = _load_users()
    user_entry = users.get(username, {})
    if user_entry.get("role") == "admin":
        return None

    with _lock:
        groups = _load()

    ad_set = set(ad_groups or [])
    user_groups = [
        g
        for g in groups.values()
        if username in g.get("members", []) or ad_set & set(g.get("ad_groups", []))
    ]

    if not user_groups:
        return []

    if any(not g.get("adom_restrict", False) for g in user_groups):
        return None

    allowed: set[str] = set()
    for g in user_groups:
        allowed.update(g.get("allowed_adoms", []))
    return sorted(allowed)


def user_can_access_adom(
    username: str, adom: str, ad_groups: list[str] | None = None
) -> bool:
    allowed = get_allowed_adoms(username, ad_groups=ad_groups)
    if allowed is None:
        return True
    return adom in allowed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_groups.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Write `groups.example.json`**

```json
{
  "everyone": {
    "members": [],
    "ad_groups": [],
    "allowed_tabs": ["dashboard", "log_search"],
    "adom_restrict": false,
    "allowed_adoms": []
  }
}
```

- [ ] **Step 6: Commit**

```bash
git add app/groups.py groups.example.json tests/test_groups.py
git commit -m "Add group-based tab permission module"
```

---

### Task 8: Route decorators

**Files:**
- Create: `app/decorators.py`
- Test: `tests/test_decorators.py`

**Interfaces:**
- Consumes: `app.auth._load_users` (Task 6), `app.groups.get_allowed_tabs` (Task 7).
- Produces: `login_required(f)`, `tab_required(tab_key)(f)`, `admin_required(f)`, `check_adom_access(adom) -> tuple | None`. Consumed by every page/API route in Tasks 10–12.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_decorators.py
import time
import pytest
from flask import Flask, session, jsonify


@pytest.fixture
def app(tmp_path, monkeypatch):
    import app.auth as auth_mod
    import app.groups as groups_mod
    monkeypatch.setattr(auth_mod, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(groups_mod, "GROUPS_FILE", tmp_path / "groups.json")
    groups_mod.KNOWN_TABS = {"dashboard": "Dashboard"}

    flask_app = Flask(__name__)
    flask_app.config["SECRET_KEY"] = "test"
    flask_app.config["SESSION_ABSOLUTE_LIFETIME"] = 36000

    from app.decorators import login_required, tab_required, admin_required

    @flask_app.route("/login")
    def login():
        return "login page"

    @flask_app.route("/protected")
    @login_required
    def protected():
        return "ok"

    @flask_app.route("/dash")
    @tab_required("dashboard")
    def dash():
        return "dashboard"

    @flask_app.route("/admin-only")
    @admin_required
    def admin_only():
        return "admin"

    @flask_app.route("/api/thing")
    @login_required
    def api_thing():
        return jsonify({"ok": True})

    yield flask_app
    groups_mod.KNOWN_TABS = {}


@pytest.fixture
def client(app):
    return app.test_client()


def _login(client, username="alice", role="viewer"):
    with client.session_transaction() as sess:
        sess["user"] = username
        sess["role"] = role
        sess["ad_groups"] = []
        sess["allowed_tabs"] = ["dashboard"] if role != "admin" else []
        sess["login_at"] = int(time.time())


def test_login_required_redirects_when_anonymous(client):
    resp = client.get("/protected")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_login_required_allows_authenticated(client):
    _login(client)
    resp = client.get("/protected")
    assert resp.status_code == 200


def test_login_required_api_returns_401_json(client):
    resp = client.get("/api/thing")
    assert resp.status_code == 401
    assert resp.get_json() == {"error": "Not authenticated"}


def test_tab_required_allows_permitted_tab(client):
    _login(client, role="viewer")
    resp = client.get("/dash")
    assert resp.status_code == 200


def test_tab_required_blocks_unpermitted_tab(client):
    _login(client, username="bob", role="viewer")
    with client.session_transaction() as sess:
        sess["allowed_tabs"] = []
    resp = client.get("/dash")
    assert resp.status_code == 403


def test_admin_required_blocks_viewer(client):
    _login(client, role="viewer")
    resp = client.get("/admin-only")
    assert resp.status_code == 403


def test_admin_required_allows_admin(client):
    _login(client, role="admin")
    resp = client.get("/admin-only")
    assert resp.status_code == 200


def test_session_expires_after_absolute_lifetime(client, app):
    app.config["SESSION_ABSOLUTE_LIFETIME"] = 1
    _login(client)
    with client.session_transaction() as sess:
        sess["login_at"] = int(time.time()) - 10
    resp = client.get("/protected")
    assert resp.status_code == 302
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_decorators.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.decorators'`

- [ ] **Step 3: Write `app/decorators.py`**

```python
"""Shared route decorators — import these instead of redefining in every blueprint."""

from __future__ import annotations
from functools import wraps
import time as _time
from flask import session as flask_session, redirect, url_for, abort, jsonify, request
from flask import current_app


def _revalidate_session() -> "tuple | None":
    """Re-check that the session is still valid on every request."""
    login_at = flask_session.get("login_at")
    if login_at is None:
        flask_session.clear()
        return redirect(url_for("auth.login")), 302

    lifetime = current_app.config.get("SESSION_ABSOLUTE_LIFETIME", 36000)
    if _time.time() - login_at > lifetime:
        flask_session.clear()
        if request.path.startswith("/api/") or request.path.startswith("/admin/api/"):
            return jsonify({"error": "Session expired"}), 401
        return redirect(url_for("auth.login")), 302

    username = flask_session.get("user", "")
    if username:
        from app.auth import _load_users
        from app.groups import get_allowed_tabs

        users = _load_users()
        entry = users.get(username)
        ad_groups = flask_session.get("ad_groups", [])
        if entry is None:
            if not flask_session.get("role"):
                flask_session.clear()
                if request.path.startswith("/api/") or request.path.startswith("/admin/api/"):
                    return jsonify({"error": "Not authenticated"}), 401
                return redirect(url_for("auth.login")), 302
        else:
            flask_session["role"] = entry.get("role", "viewer")
        flask_session["allowed_tabs"] = list(
            get_allowed_tabs(username, ad_groups=ad_groups, role=flask_session.get("role"))
        )

    return None


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in flask_session:
            if request.path.startswith("/api/") or request.path.startswith("/admin/api/"):
                return jsonify({"error": "Not authenticated"}), 401
            return redirect(url_for("auth.login", next=request.path))
        err = _revalidate_session()
        if err is not None:
            return err
        return f(*args, **kwargs)

    return decorated


def tab_required(tab_key: str):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if "user" not in flask_session:
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Not authenticated"}), 401
                return redirect(url_for("auth.login", next=request.path))
            err = _revalidate_session()
            if err is not None:
                return err
            if flask_session.get("role") != "admin" and tab_key not in set(
                flask_session.get("allowed_tabs", [])
            ):
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Access denied"}), 403
                abort(403)
            return f(*args, **kwargs)

        return decorated

    return decorator


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in flask_session:
            if request.path.startswith("/api/") or request.path.startswith("/admin/api/"):
                return jsonify({"error": "Not authenticated"}), 401
            return redirect(url_for("auth.login", next=request.path))
        err = _revalidate_session()
        if err is not None:
            return err
        if flask_session.get("role") != "admin":
            if request.path.startswith("/api/") or request.path.startswith("/admin/api/"):
                return jsonify({"error": "Admin role required"}), 403
            abort(403)
        return f(*args, **kwargs)

    return decorated


def check_adom_access(adom: str) -> "tuple | None":
    """Return a 403 JSON response tuple if the current user cannot access ``adom``.

    Not called by any route until Phase 2's FAZ-target routes exist.
    """
    if flask_session.get("role") == "admin":
        return None
    from app.groups import user_can_access_adom

    ad_groups = flask_session.get("ad_groups", [])
    if not user_can_access_adom(flask_session.get("user", ""), adom, ad_groups=ad_groups):
        return jsonify(
            {"error": f"Access to ADOM '{adom}' is not permitted for your account"}
        ), 403
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_decorators.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add app/decorators.py tests/test_decorators.py
git commit -m "Add login/tab/admin route decorators with session revalidation"
```

---

### Task 9: App factory and WSGI entry point

**Files:**
- Modify: `app/__init__.py` (replace empty placeholder from Task 1)
- Create: `wsgi.py`
- Test: `tests/test_smoke.py`

**Interfaces:**
- Consumes: `app.config.Config` (Task 2), `app.security.ensure_csrf_token`/`validate_csrf_request`/`csrf_error_response` (Task 4), `app.registry` (Task 5), `app.groups.KNOWN_TABS` (Task 7).
- Produces: `create_app() -> Flask`. `wsgi.py` exposes module-level `app` for Gunicorn (`wsgi:app`).
- Note: `_BLUEPRINT_MODULES` list starts empty in this task (no route blueprints exist yet) — Tasks 10–12 each append one entry and re-verify the smoke test still passes.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_smoke.py
"""Smoke tests — verify the app can be imported and instantiated."""
import os

import pytest


@pytest.fixture
def app():
    os.environ.setdefault("SECRET_KEY", "test-secret")
    from app import create_app
    return create_app()


@pytest.fixture
def client(app):
    return app.test_client()


def test_app_creates(app):
    assert app is not None


def test_security_headers_present(client):
    resp = client.get("/nonexistent-path")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_smoke.py -v`
Expected: FAIL — `app/__init__.py` has no `create_app` (it's still the empty placeholder from Task 1).

- [ ] **Step 3: Write `app/__init__.py`**

```python
from flask import Flask, jsonify, request, session
from werkzeug.exceptions import RequestEntityTooLarge
from app.config import Config
from app.security import csrf_error_response, ensure_csrf_token, validate_csrf_request

# Blueprint modules to import — each one calls registry.register() at import
# time.  To add a new module, append its dotted path here and nothing else.
_BLUEPRINT_MODULES: list[str] = [
    # "app.routes.auth_routes",       ← added in Task 10
    # "app.routes.dashboard_routes",  ← added in Task 11
    # "app.routes.log_search_routes", ← added in Task 11
    # "app.routes.admin_routes",      ← added in Task 12
]


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(Config)

    @app.before_request
    def _security_filters():
        ensure_csrf_token()
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if request.endpoint == "static":
                return None
            if not validate_csrf_request():
                return csrf_error_response()
        return None

    @app.after_request
    def _set_security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        resp.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self' data:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'"
        )
        forwarded_proto = request.headers.get("X-Forwarded-Proto", "")
        if request.is_secure or forwarded_proto.lower() == "https":
            resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return resp

    @app.errorhandler(RequestEntityTooLarge)
    def _file_too_large(_exc):
        if request.path.startswith("/api/") or request.path.startswith("/admin/api/"):
            return jsonify({"error": "Uploaded file is too large"}), 413
        return "Uploaded file is too large", 413

    import importlib

    for module_path in _BLUEPRINT_MODULES:
        mod = importlib.import_module(module_path)
        if hasattr(mod, "bp"):
            app.register_blueprint(mod.bp)

    from app import registry
    from app import groups

    groups.KNOWN_TABS = registry.known_tabs()

    @app.context_processor
    def inject_session_globals():
        role = session.get("role", "viewer")
        if role == "admin":
            allowed = set(registry.known_tabs().keys())
        else:
            allowed = set(session.get("allowed_tabs", []))
        return {
            "current_role": role,
            "allowed_tabs": allowed,
            "nav_registry": registry.get_registry(),
            "csrf_token": ensure_csrf_token(),
        }

    return app
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_smoke.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Write `wsgi.py`**

```python
import os
from app import create_app
from dotenv import load_dotenv

load_dotenv()

app = create_app()

try:
    _proxy_count = int(os.environ.get("TRUSTED_PROXY_COUNT", "0"))
except ValueError:
    import logging as _logging

    _logging.warning("TRUSTED_PROXY_COUNT is not a valid integer; ProxyFix not applied")
    _proxy_count = 0
if _proxy_count > 0:
    from werkzeug.middleware.proxy_fix import ProxyFix

    app = ProxyFix(app, x_for=_proxy_count, x_proto=_proxy_count, x_host=_proxy_count)

if __name__ == "__main__":
    cert = os.environ.get("SSL_CERT", "certs/cert.pem")
    key = os.environ.get("SSL_KEY", "certs/key.pem")
    port = int(os.environ.get("PORT", "5443"))

    ssl_ctx = None
    if os.path.exists(cert) and os.path.exists(key):
        import ssl

        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_ctx.load_cert_chain(cert, key)

    app.run(host="0.0.0.0", port=port, debug=False, ssl_context=ssl_ctx)
```

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -v`
Expected: all tests from Tasks 1–9 PASS.

- [ ] **Step 7: Commit**

```bash
git add app/__init__.py wsgi.py tests/test_smoke.py
git commit -m "Add Flask app factory and WSGI entry point"
```

---

### Task 10: Login page and base template

**Files:**
- Create: `app/routes/auth_routes.py`
- Create: `app/templates/base.html`
- Create: `app/templates/login.html`
- Create: `app/static/css/style.css`
- Modify: `app/__init__.py:9-14` (uncomment `"app.routes.auth_routes"` in `_BLUEPRINT_MODULES`)
- Test: `tests/test_auth_routes.py`

**Interfaces:**
- Consumes: `app.auth.authenticate` (Task 6), `app.groups.get_allowed_tabs` (Task 7), `app.registry` (Task 5), `app.app_logger.app_log` (Task 3).
- Produces: `bp` Blueprint named `"auth"` with endpoints `auth.login` (`GET`/`POST` `/login`) and `auth.logout` (`POST` `/logout`). Session keys set on login: `user`, `role`, `ad_groups`, `allowed_tabs`, `login_at` — this exact key set is relied on by `decorators.py` (Task 8, already written) and by every later route.

- [ ] **Step 1: Copy and rebrand the stylesheet**

```bash
mkdir -p app/static/css
cp /Users/alanw/code/github/web/4thealth/app/static/css/style.css app/static/css/style.css
sed -i '' 's/4THealth/4tlog/g; s/4thealth/4tlog/g' app/static/css/style.css
```

This gives the new project the same visual system (CSS custom properties for light/dark theme, `.topbar`, `.data-table`, `.btn`, `.modal-overlay`, `.checkbox-group`, `.alert`, etc.) that later tabs and the admin UI depend on, without hand-authoring hundreds of lines of CSS. Confirm the file copied:

Run: `grep -c "4thealth" app/static/css/style.css`
Expected: `0` (no leftover old branding)

- [ ] **Step 2: Write the failing test**

```python
# tests/test_auth_routes.py
import os
import pytest


@pytest.fixture
def app(tmp_path, monkeypatch):
    os.environ.setdefault("SECRET_KEY", "test-secret")
    import app.auth as auth_mod
    import app.groups as groups_mod
    monkeypatch.setattr(auth_mod, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(groups_mod, "GROUPS_FILE", tmp_path / "groups.json")
    auth_mod.add_user("alice", "Str0ng!Passw0rd", role="admin")

    from app import create_app
    return create_app()


@pytest.fixture
def client(app):
    return app.test_client()


def test_login_page_reachable(client):
    resp = client.get("/login")
    assert resp.status_code == 200
    assert b"Password" in resp.data


def test_unauthenticated_root_has_no_crash(client):
    resp = client.get("/nonexistent")
    assert resp.status_code == 404


def test_login_with_wrong_password_returns_401(client):
    resp = client.post("/login", data={"username": "alice", "password": "wrong"})
    assert resp.status_code == 401


def test_login_success_sets_session(client):
    resp = client.post(
        "/login", data={"username": "alice", "password": "Str0ng!Passw0rd"}
    )
    assert resp.status_code in (302, 200)
    with client.session_transaction() as sess:
        assert sess["user"] == "alice"
        assert sess["role"] == "admin"


def test_logout_clears_session(client):
    client.post("/login", data={"username": "alice", "password": "Str0ng!Passw0rd"})
    with client.session_transaction() as sess:
        csrf = sess.get("_csrf_token", "")
    resp = client.post("/logout", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert "user" not in sess
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_auth_routes.py -v`
Expected: FAIL — `/login` returns 404 (no blueprint registered yet).

- [ ] **Step 4: Write `app/routes/auth_routes.py`**

```python
import threading
import time
from collections import defaultdict
from urllib.parse import urlparse
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from app.auth import authenticate
from app.groups import get_allowed_tabs
from app.app_logger import app_log
from app import registry

# In-memory sliding-window rate limiter for /login:
# 10 attempts per IP per 10 minutes, 5 attempts per username per 10 minutes.
_WINDOW_SECONDS = 600
_IP_MAX = 10
_USER_MAX = 5
_USER_FAILURES_MAX_KEYS = 10_000

_lock = threading.Lock()
_ip_failures: dict[str, list[float]] = defaultdict(list)
_user_failures: dict[str, list[float]] = defaultdict(list)


def _norm_username(username: str) -> str:
    return username.strip().lower()


def _is_rate_limited(ip: str, username: str) -> bool:
    now = time.monotonic()
    cutoff = now - _WINDOW_SECONDS
    norm = _norm_username(username)
    with _lock:
        _ip_failures[ip] = [t for t in _ip_failures[ip] if t > cutoff]
        _user_failures[norm] = [t for t in _user_failures[norm] if t > cutoff]
        return len(_ip_failures[ip]) >= _IP_MAX or len(_user_failures[norm]) >= _USER_MAX


def _record_failure(ip: str, username: str) -> None:
    now = time.monotonic()
    norm = _norm_username(username)
    with _lock:
        _ip_failures[ip].append(now)
        if len(_user_failures) >= _USER_FAILURES_MAX_KEYS and norm not in _user_failures:
            oldest_key = next(iter(_user_failures))
            del _user_failures[oldest_key]
        _user_failures[norm].append(now)


def _clear_failures(ip: str, username: str) -> None:
    norm = _norm_username(username)
    with _lock:
        _ip_failures.pop(ip, None)
        _user_failures.pop(norm, None)


def _safe_redirect(url: str) -> bool:
    parsed = urlparse(url)
    return (
        not parsed.scheme
        and not parsed.netloc
        and parsed.path.startswith("/")
        and url != "/login"
    )


bp = Blueprint("auth", __name__)


def _first_allowed_url(allowed_tabs: list) -> str:
    for key, meta in registry.get_registry().items():
        if key in allowed_tabs:
            return url_for(meta["endpoint"])
    return url_for("auth.login")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            flash("Username and password are required.", "danger")
            return render_template("login.html"), 400

        ip = request.remote_addr or ""
        if _is_rate_limited(ip, username):
            app_log("WARN", "auth", "Login rate-limited", username=username, remote=ip)
            flash("Too many failed attempts. Please wait before trying again.", "danger")
            return render_template("login.html"), 429

        auth_result = authenticate(username, password)
        if auth_result is not None:
            role, ad_groups = auth_result
            _clear_failures(ip, username)
            session.permanent = True
            session["user"] = username
            session["role"] = role
            session["ad_groups"] = ad_groups
            allowed = list(get_allowed_tabs(username, ad_groups=ad_groups, role=role))
            session["allowed_tabs"] = allowed
            session["login_at"] = int(time.time())
            app_log("INFO", "auth", "Login successful", username=username, role=session["role"])
            next_url = request.args.get("next", "").strip()
            if next_url and _safe_redirect(next_url):
                return redirect(next_url)
            return redirect(_first_allowed_url(allowed))

        _record_failure(ip, username)
        app_log("WARN", "auth", "Failed login attempt", username=username, remote=ip)
        flash("Invalid credentials.", "danger")
        return render_template("login.html"), 401
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    username = session.get("user", "unknown")
    app_log("INFO", "auth", "Logout", username=username)
    session.clear()
    return redirect(url_for("auth.login"))
```

- [ ] **Step 5: Write `app/templates/base.html`**

```html
<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="csrf-token" content="{{ csrf_token }}" />
  <title>{% block title %}4tlog{% endblock %}</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}?v=1" />
  {% block head %}{% endblock %}
</head>
<body>
{% if session.get('user') %}
<header class="topbar">
  <div class="topbar-brand">
    <span class="brand-icon">&#128269;</span> 4tlog
  </div>
  <nav class="topbar-nav">
    {% for key, tab in nav_registry.items() %}
      {% if key in allowed_tabs %}
    <a href="{{ url_for(tab.endpoint) }}" class="nav-link {% if request.endpoint == tab.endpoint %}active{% endif %}">{{ tab.icon ~ ' ' if tab.icon }}{{ tab.name }}</a>
      {% endif %}
    {% endfor %}
    {% if current_role == 'admin' %}
    <a href="{{ url_for('admin.admin_page') }}" class="nav-link nav-link-admin {% if request.endpoint == 'admin.admin_page' %}active{% endif %}">&#9881; Admin</a>
    {% endif %}
  </nav>
  <div class="topbar-right">
    <span class="nav-user">{{ session.get('user') }}</span>
    <button class="btn btn-sm btn-ghost" id="themeToggle" title="Toggle light/dark mode">&#9788;</button>
    <form method="post" action="{{ url_for('auth.logout') }}" style="display:inline">
      <input type="hidden" name="csrf_token" value="{{ csrf_token }}" />
      <button type="submit" class="btn btn-sm btn-ghost">Logout</button>
    </form>
  </div>
</header>
{% endif %}

<main class="main-content">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% for cat, msg in messages %}
    <div class="alert alert-{{ cat }}">{{ msg }}</div>
    {% endfor %}
  {% endwith %}
  {% block content %}{% endblock %}
</main>

<script>
(function () {
  const csrfMeta = document.querySelector('meta[name="csrf-token"]');
  const csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';
  const nativeFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    const opts = init || {};
    const method = String(opts.method || 'GET').toUpperCase();
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
      const headers = new Headers(opts.headers || {});
      if (csrfToken && !headers.has('X-CSRF-Token')) headers.set('X-CSRF-Token', csrfToken);
      opts.headers = headers;
    }
    return nativeFetch(input, opts);
  };

  const stored = localStorage.getItem('theme') || 'light';
  document.documentElement.setAttribute('data-theme', stored);
  const btn = document.getElementById('themeToggle');
  if (btn) {
    btn.textContent = stored === 'dark' ? '☀' : '☽';
    btn.addEventListener('click', () => {
      const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('theme', next);
      btn.textContent = next === 'dark' ? '☀' : '☽';
    });
  }
})();
</script>
{% block scripts %}{% endblock %}
</body>
</html>
```

- [ ] **Step 6: Write `app/templates/login.html`**

```html
{% extends "base.html" %}
{% block title %}Login — 4tlog{% endblock %}
{% block content %}
<div class="login-wrap">
  <div class="login-card">
    <h1 class="login-title">4tlog</h1>
    <p class="login-subtitle">FortiAnalyzer Log Search</p>
    <form method="post" action="{{ url_for('auth.login') }}">
      <input type="hidden" name="csrf_token" value="{{ csrf_token }}" />
      <div class="form-group">
        <label for="username">Username</label>
        <input type="text" class="form-control" id="username" name="username" autofocus required />
      </div>
      <div class="form-group">
        <label for="password">Password</label>
        <input type="password" class="form-control" id="password" name="password" required />
      </div>
      <button type="submit" class="btn btn-primary btn-block">Log In</button>
    </form>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 7: Register the auth blueprint**

In `app/__init__.py`, change:
```python
_BLUEPRINT_MODULES: list[str] = [
    # "app.routes.auth_routes",       ← added in Task 10
```
to:
```python
_BLUEPRINT_MODULES: list[str] = [
    "app.routes.auth_routes",
```

- [ ] **Step 8: Run test to verify it passes**

Run: `uv run pytest tests/test_auth_routes.py -v`
Expected: PASS (5 tests)

Run: `uv run pytest -v`
Expected: all tests from Tasks 1–10 PASS (the old `tests/test_smoke.py` root-path assumptions still hold since `/` isn't registered yet).

- [ ] **Step 9: Commit**

```bash
git add app/routes/auth_routes.py app/templates/base.html app/templates/login.html app/static/css/style.css app/__init__.py tests/test_auth_routes.py
git commit -m "Add login/logout routes and base page template"
```

---

### Task 11: Dashboard and Log Search placeholder tabs

**Files:**
- Create: `app/routes/dashboard_routes.py`
- Create: `app/routes/log_search_routes.py`
- Create: `app/templates/dashboard.html`
- Create: `app/templates/log_search.html`
- Modify: `app/__init__.py` (uncomment `"app.routes.dashboard_routes"` and `"app.routes.log_search_routes"`)
- Test: `tests/test_tab_routes.py`

**Interfaces:**
- Consumes: `app.decorators.tab_required` (Task 8), `app.registry.register` (Task 5).
- Produces: `dashboard.bp` with endpoint `dashboard.index` (`GET /`, tab key `dashboard`); `log_search.bp` with endpoint `log_search.index` (`GET /log-search`, tab key `log_search`). Both are placeholders — Phase 2 replaces `dashboard.html`'s body with real FAZ health cards, Phase 3 replaces `log_search.html`'s body with the real filter/results UI. The route functions, endpoint names, and tab keys defined here must not change in later phases (groups.json and any bookmarked URLs depend on them).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tab_routes.py
import os
import time
import pytest


@pytest.fixture
def app(tmp_path, monkeypatch):
    os.environ.setdefault("SECRET_KEY", "test-secret")
    import app.auth as auth_mod
    import app.groups as groups_mod
    monkeypatch.setattr(auth_mod, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(groups_mod, "GROUPS_FILE", tmp_path / "groups.json")
    auth_mod.add_user("alice", "Str0ng!Passw0rd", role="viewer")
    groups_mod.create_group("g1", members=["alice"], allowed_tabs=["dashboard"])

    from app import create_app
    return create_app()


@pytest.fixture
def client(app):
    return app.test_client()


def _login(client, username="alice", password="Str0ng!Passw0rd"):
    client.post("/login", data={"username": username, "password": password})


def test_dashboard_requires_login(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_dashboard_reachable_when_permitted(client):
    _login(client)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Dashboard" in resp.data


def test_log_search_blocked_without_tab_permission(client):
    _login(client)
    resp = client.get("/log-search")
    assert resp.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tab_routes.py -v`
Expected: FAIL — `/` and `/log-search` both 404 (no blueprints registered).

- [ ] **Step 3: Write `app/routes/dashboard_routes.py`**

```python
from flask import Blueprint, render_template, session
from app.decorators import tab_required
from app import registry

bp = Blueprint("dashboard", __name__)

registry.register("dashboard", "Dashboard", "dashboard.index")


@bp.route("/")
@tab_required("dashboard")
def index():
    return render_template("dashboard.html", user=session["user"])
```

- [ ] **Step 4: Write `app/routes/log_search_routes.py`**

```python
from flask import Blueprint, render_template, session
from app.decorators import tab_required
from app import registry

bp = Blueprint("log_search", __name__)

registry.register("log_search", "Log Search", "log_search.index")


@bp.route("/log-search")
@tab_required("log_search")
def index():
    return render_template("log_search.html", user=session["user"])
```

- [ ] **Step 5: Write `app/templates/dashboard.html`**

```html
{% extends "base.html" %}
{% block title %}Dashboard — 4tlog{% endblock %}
{% block content %}
<h1>Dashboard</h1>
<p class="text-muted">FortiAnalyzer fleet health cards will appear here (Phase 2).</p>
{% endblock %}
```

- [ ] **Step 6: Write `app/templates/log_search.html`**

```html
{% extends "base.html" %}
{% block title %}Log Search — 4tlog{% endblock %}
{% block content %}
<h1>Log Search</h1>
<p class="text-muted">FAZ log search filters and results will appear here (Phase 3).</p>
{% endblock %}
```

- [ ] **Step 7: Register both blueprints**

In `app/__init__.py`, uncomment both lines so `_BLUEPRINT_MODULES` reads:
```python
_BLUEPRINT_MODULES: list[str] = [
    "app.routes.auth_routes",
    "app.routes.dashboard_routes",
    "app.routes.log_search_routes",
    # "app.routes.admin_routes",      ← added in Task 12
]
```

- [ ] **Step 8: Run test to verify it passes**

Run: `uv run pytest tests/test_tab_routes.py -v`
Expected: PASS (3 tests)

Run: `uv run pytest -v`
Expected: all tests from Tasks 1–11 PASS.

- [ ] **Step 9: Commit**

```bash
git add app/routes/dashboard_routes.py app/routes/log_search_routes.py app/templates/dashboard.html app/templates/log_search.html app/__init__.py tests/test_tab_routes.py
git commit -m "Add Dashboard and Log Search placeholder tabs"
```

---

### Task 12: Admin tab — Users, Groups, Logs

**Files:**
- Create: `app/routes/admin_routes.py`
- Create: `app/templates/admin.html`
- Create: `app/static/js/admin.js`
- Modify: `app/__init__.py` (uncomment `"app.routes.admin_routes"`)
- Test: `tests/test_admin_routes.py`

**Interfaces:**
- Consumes: `app.decorators.admin_required` (Task 8), `app.groups.{list_groups,get_group,create_group,update_group,delete_group}` (Task 7), `app.auth.list_users` (Task 6), `app.registry.known_tabs` (Task 5), `app.app_logger.{app_log,get_log_entries,get_log_level,get_log_levels,set_log_level,clear_log_entries}` (Task 3).
- Produces: `bp` Blueprint named `"admin"`, `url_prefix="/admin"`. Page: `admin.admin_page` (`GET /admin`). JSON API: `GET/POST /admin/api/groups`, `PUT/DELETE /admin/api/groups/<name>`, `GET /admin/api/users`, `GET /admin/api/tabs`, `GET /admin/api/logs`, `POST /admin/api/logs/level`, `DELETE /admin/api/logs`. This exact endpoint set is what later phases extend (Phase 4 adds `/admin/api/faz-targets` alongside it) — do not rename any of these paths.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_admin_routes.py
import os
import pytest


@pytest.fixture
def app(tmp_path, monkeypatch):
    os.environ.setdefault("SECRET_KEY", "test-secret")
    import app.auth as auth_mod
    import app.groups as groups_mod
    monkeypatch.setattr(auth_mod, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(groups_mod, "GROUPS_FILE", tmp_path / "groups.json")
    auth_mod.add_user("admin1", "Str0ng!Passw0rd", role="admin")
    auth_mod.add_user("viewer1", "Str0ng!Passw0rd", role="viewer")

    from app import create_app
    return create_app()


@pytest.fixture
def client(app):
    return app.test_client()


def _login(client, username, password="Str0ng!Passw0rd"):
    client.post("/login", data={"username": username, "password": password})


def _csrf(client):
    with client.session_transaction() as sess:
        return sess.get("_csrf_token", "")


def test_admin_page_blocked_for_viewer(client):
    _login(client, "viewer1")
    resp = client.get("/admin/")
    assert resp.status_code == 403


def test_admin_page_reachable_for_admin(client):
    _login(client, "admin1")
    resp = client.get("/admin/")
    assert resp.status_code == 200


def test_admin_users_list(client):
    _login(client, "admin1")
    resp = client.get("/admin/api/users")
    assert resp.status_code == 200
    usernames = {u["username"] for u in resp.get_json()}
    assert usernames == {"admin1", "viewer1"}


def test_admin_tabs_list_includes_registered_tabs(client):
    _login(client, "admin1")
    resp = client.get("/admin/api/tabs")
    keys = {t["key"] for t in resp.get_json()}
    assert {"dashboard", "log_search", "admin"} <= keys


def test_admin_group_crud(client):
    _login(client, "admin1")
    csrf = _csrf(client)
    resp = client.post(
        "/admin/api/groups",
        json={"name": "noc", "members": ["viewer1"], "allowed_tabs": ["dashboard"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 201
    resp = client.get("/admin/api/groups")
    assert [g["name"] for g in resp.get_json()] == ["noc"]

    resp = client.put(
        "/admin/api/groups/noc",
        json={"members": ["viewer1"], "allowed_tabs": ["dashboard", "log_search"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 200
    assert set(resp.get_json()["allowed_tabs"]) == {"dashboard", "log_search"}

    resp = client.delete("/admin/api/groups/noc", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200
    assert client.get("/admin/api/groups").get_json() == []


def test_admin_logs_endpoints(client):
    _login(client, "admin1")
    csrf = _csrf(client)
    resp = client.get("/admin/api/logs")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "entries" in body and "current_level" in body

    resp = client.post(
        "/admin/api/logs/level", json={"level": "DEBUG"}, headers={"X-CSRF-Token": csrf}
    )
    assert resp.status_code == 200
    assert resp.get_json()["current_level"] == "DEBUG"

    resp = client.delete("/admin/api/logs", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200


def test_admin_api_blocked_without_csrf(client):
    _login(client, "admin1")
    resp = client.post("/admin/api/groups", json={"name": "x", "allowed_tabs": []})
    assert resp.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_admin_routes.py -v`
Expected: FAIL — `/admin/` 404s (no blueprint registered).

- [ ] **Step 3: Write `app/routes/admin_routes.py`**

```python
"""Admin-only routes.

Page:  GET  /admin

Groups API (JSON):
  GET    /admin/api/groups
  POST   /admin/api/groups           {"name": str, "members": [...], "allowed_tabs": [...],
                                      "adom_restrict": bool, "allowed_adoms": [...]}
  PUT    /admin/api/groups/<name>    {"members": [...], "allowed_tabs": [...],
                                      "adom_restrict": bool, "allowed_adoms": [...]}
  DELETE /admin/api/groups/<name>
  GET    /admin/api/users            list of {username, role} for member picker

Tab registry:
  GET    /admin/api/tabs             known tab keys + display names

Logs API (JSON):
  GET    /admin/api/logs?level=INFO&component=auth&limit=500
  POST   /admin/api/logs/level       {"level": "DEBUG"}
  DELETE /admin/api/logs             clears the buffer
"""

from flask import Blueprint, render_template, session, jsonify, request
from app.decorators import admin_required as _admin_required
from app.groups import list_groups, get_group, create_group, update_group, delete_group
from app import registry
from app.auth import list_users
from app.app_logger import (
    app_log,
    get_log_entries,
    get_log_level,
    get_log_levels,
    set_log_level,
    clear_log_entries,
)

bp = Blueprint("admin", __name__, url_prefix="/admin")

registry.register("admin", "Admin", "admin.admin_page")


@bp.route("/")
@_admin_required
def admin_page():
    app_log("DEBUG", "admin", "Admin page accessed", username=session["user"])
    return render_template("admin.html", user=session["user"])


# ── Groups API ────────────────────────────────────────────────────────────────


@bp.route("/api/groups")
@_admin_required
def api_groups_list():
    return jsonify(list_groups())


@bp.route("/api/groups", methods=["POST"])
@_admin_required
def api_groups_create():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    members = data.get("members", [])
    ad_groups = data.get("ad_groups", [])
    allowed_tabs = data.get("allowed_tabs", [])
    adom_restrict = bool(data.get("adom_restrict", False))
    allowed_adoms = data.get("allowed_adoms", [])
    try:
        ok = create_group(name, members, ad_groups, allowed_tabs, adom_restrict, allowed_adoms)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not ok:
        return jsonify({"error": f"Group '{name}' already exists"}), 409
    app_log("INFO", "admin", "Group created", by=session["user"], group=name)
    return jsonify(get_group(name)), 201


@bp.route("/api/groups/<name>", methods=["PUT"])
@_admin_required
def api_groups_update(name: str):
    data = request.get_json(silent=True) or {}
    members = data.get("members", [])
    ad_groups = data.get("ad_groups", [])
    allowed_tabs = data.get("allowed_tabs", [])
    adom_restrict = bool(data.get("adom_restrict", False))
    allowed_adoms = data.get("allowed_adoms", [])
    if not update_group(
        name, members, allowed_tabs, adom_restrict, allowed_adoms, ad_groups=ad_groups
    ):
        return jsonify({"error": f"Group '{name}' not found"}), 404
    app_log("INFO", "admin", "Group updated", by=session["user"], group=name)
    return jsonify(get_group(name))


@bp.route("/api/groups/<name>", methods=["DELETE"])
@_admin_required
def api_groups_delete(name: str):
    if not delete_group(name):
        return jsonify({"error": f"Group '{name}' not found"}), 404
    app_log("INFO", "admin", "Group deleted", by=session["user"], group=name)
    return jsonify({"deleted": name})


# ── Users API (for member picker) ─────────────────────────────────────────────


@bp.route("/api/users")
@_admin_required
def api_users_list():
    return jsonify(list_users())


# ── Tabs registry ─────────────────────────────────────────────────────────────


@bp.route("/api/tabs")
@_admin_required
def api_tabs_list():
    return jsonify([{"key": k, "name": v} for k, v in registry.known_tabs().items()])


# ── Logs API ──────────────────────────────────────────────────────────────────


@bp.route("/api/logs")
@_admin_required
def api_logs_get():
    level = request.args.get("level") or None
    component = request.args.get("component") or None
    try:
        limit = int(request.args.get("limit", 500))
    except ValueError:
        limit = 500
    entries = get_log_entries(level=level, component=component, limit=limit)
    return jsonify(
        {
            "current_level": get_log_level(),
            "levels": get_log_levels(),
            "count": len(entries),
            "entries": entries,
        }
    )


@bp.route("/api/logs/level", methods=["POST"])
@_admin_required
def api_logs_set_level():
    data = request.get_json(silent=True) or {}
    level = (data.get("level") or "").upper()
    try:
        set_log_level(level)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    app_log("INFO", "admin", "Log level changed", by=session["user"], new_level=level)
    return jsonify({"current_level": get_log_level()})


@bp.route("/api/logs", methods=["DELETE"])
@_admin_required
def api_logs_clear():
    clear_log_entries()
    app_log("INFO", "admin", "Log buffer cleared", by=session["user"])
    return jsonify({"cleared": True})
```

- [ ] **Step 4: Write `app/templates/admin.html`**

```html
{% extends "base.html" %}
{% block title %}Admin — 4tlog{% endblock %}
{% block content %}
<h1>Admin</h1>

<div class="admin-tabs" id="adminTabs">
  <button class="admin-tab-btn active" data-panel="panel-groups">Groups &amp; Permissions</button>
  <button class="admin-tab-btn" data-panel="panel-users">Users</button>
  <button class="admin-tab-btn" data-panel="panel-logs">Logs</button>
</div>

<div class="admin-panel active" id="panel-groups">
  <div class="panel-header">
    <h2>Groups &amp; Permissions</h2>
    <button class="btn btn-primary" id="btnNewGroup">+ New Group</button>
  </div>
  <div class="table-wrapper">
    <table class="data-table" id="groupsTable">
      <thead>
        <tr><th>Name</th><th>Members</th><th>Allowed Tabs</th><th>Actions</th></tr>
      </thead>
      <tbody id="groupsTbody"></tbody>
    </table>
  </div>
</div>

<div class="admin-panel" id="panel-users">
  <div class="panel-header">
    <h2>Users</h2>
    <p class="text-muted">Accounts are managed with the CLI: <code>uv run python manage_users.py add &lt;username&gt; --role admin|viewer</code></p>
  </div>
  <div class="table-wrapper">
    <table class="data-table" id="usersTable">
      <thead><tr><th>Username</th><th>Role</th></tr></thead>
      <tbody id="usersTbody"></tbody>
    </table>
  </div>
</div>

<div class="admin-panel" id="panel-logs">
  <div class="panel-header">
    <h2>Logs</h2>
    <div>
      <select class="form-select-sm" id="logLevelSelect"></select>
      <button class="btn btn-primary btn-sm" id="btnSetLevel">Set</button>
      <button class="btn btn-sm" id="btnRefreshLogs">&#8635; Refresh</button>
      <button class="btn btn-sm" id="btnClearLogs">Clear Buffer</button>
    </div>
  </div>
  <div class="log-status-bar" id="logStatusBar">
    Active level: <strong id="logCurrentLevel">&mdash;</strong> &nbsp;|&nbsp; Showing <strong id="logCount">0</strong> entries
  </div>
  <div class="log-container" id="logContainer"></div>
</div>

<div class="modal-overlay hidden" id="groupModal">
  <div class="modal">
    <div class="modal-header">
      <h3 id="groupModalTitle">New Group</h3>
      <button class="modal-close" id="groupModalClose">&times;</button>
    </div>
    <div class="modal-body">
      <input type="hidden" id="groupModalMode" value="create" />
      <input type="hidden" id="groupModalOrigName" value="" />
      <div class="form-group">
        <label>Group Name</label>
        <input type="text" class="form-control" id="groupNameInput" placeholder="e.g. NOC-Team" />
      </div>
      <div class="form-group">
        <label>Allowed Tabs</label>
        <div id="tabCheckboxes" class="checkbox-group"></div>
      </div>
      <div class="form-group">
        <label>Members</label>
        <div id="memberCheckboxes" class="checkbox-group"></div>
      </div>
      <div id="groupModalError" class="alert alert-danger hidden"></div>
    </div>
    <div class="modal-footer">
      <button class="btn" id="groupModalCancel">Cancel</button>
      <button class="btn btn-primary" id="groupModalSave">Save Group</button>
    </div>
  </div>
</div>
{% endblock %}
{% block scripts %}
<script src="{{ url_for('static', filename='js/admin.js') }}?v=1"></script>
{% endblock %}
```

- [ ] **Step 5: Write `app/static/js/admin.js`**

```javascript
(function () {
  'use strict';

  const state = { groups: [], users: [], tabs: [] };

  function el(tag, attrs, children) {
    const e = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (k === 'text') e.textContent = v;
      else e.setAttribute(k, v);
    });
    (children || []).forEach((c) => e.appendChild(c));
    return e;
  }

  // ── Admin sub-tab switching ────────────────────────────────────────────────
  document.querySelectorAll('.admin-tab-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.admin-tab-btn').forEach((b) => b.classList.remove('active'));
      document.querySelectorAll('.admin-panel').forEach((p) => p.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById(btn.dataset.panel).classList.add('active');
      if (btn.dataset.panel === 'panel-logs') loadLogs();
    });
  });

  // ── Groups ─────────────────────────────────────────────────────────────────
  function renderGroups() {
    const tbody = document.getElementById('groupsTbody');
    tbody.innerHTML = '';
    state.groups.forEach((g) => {
      const tr = el('tr', {});
      tr.appendChild(el('td', { text: g.name }));
      tr.appendChild(el('td', { text: g.members.join(', ') || '—' }));
      tr.appendChild(el('td', { text: g.allowed_tabs.join(', ') || '—' }));
      const actions = el('td', {});
      const editBtn = el('button', { class: 'btn btn-sm', text: 'Edit' });
      editBtn.addEventListener('click', () => openGroupModal(g));
      const delBtn = el('button', { class: 'btn btn-sm', text: 'Delete' });
      delBtn.addEventListener('click', () => deleteGroup(g.name));
      actions.appendChild(editBtn);
      actions.appendChild(delBtn);
      tr.appendChild(actions);
      tbody.appendChild(tr);
    });
  }

  async function loadGroups() {
    const resp = await fetch('/admin/api/groups');
    state.groups = await resp.json();
    renderGroups();
  }

  async function deleteGroup(name) {
    if (!confirm(`Delete group "${name}"?`)) return;
    await fetch(`/admin/api/groups/${encodeURIComponent(name)}`, { method: 'DELETE' });
    await loadGroups();
  }

  function openGroupModal(group) {
    const modal = document.getElementById('groupModal');
    document.getElementById('groupModalMode').value = group ? 'edit' : 'create';
    document.getElementById('groupModalOrigName').value = group ? group.name : '';
    document.getElementById('groupModalTitle').textContent = group ? 'Edit Group' : 'New Group';
    document.getElementById('groupNameInput').value = group ? group.name : '';
    document.getElementById('groupNameInput').disabled = !!group;
    document.getElementById('groupModalError').classList.add('hidden');

    const tabWrap = document.getElementById('tabCheckboxes');
    tabWrap.innerHTML = '';
    state.tabs.forEach((t) => {
      const label = el('label', { class: 'checkbox-item' });
      const input = el('input', { type: 'checkbox', value: t.key });
      input.checked = !!(group && group.allowed_tabs.includes(t.key));
      label.appendChild(input);
      label.appendChild(document.createTextNode(' ' + t.name));
      tabWrap.appendChild(label);
    });

    const memberWrap = document.getElementById('memberCheckboxes');
    memberWrap.innerHTML = '';
    state.users.forEach((u) => {
      const label = el('label', { class: 'checkbox-item' });
      const input = el('input', { type: 'checkbox', value: u.username });
      input.checked = !!(group && group.members.includes(u.username));
      label.appendChild(input);
      label.appendChild(document.createTextNode(' ' + u.username));
      memberWrap.appendChild(label);
    });

    modal.classList.remove('hidden');
  }

  function closeGroupModal() {
    document.getElementById('groupModal').classList.add('hidden');
  }

  async function saveGroup() {
    const mode = document.getElementById('groupModalMode').value;
    const origName = document.getElementById('groupModalOrigName').value;
    const name = document.getElementById('groupNameInput').value.trim();
    const allowed_tabs = Array.from(
      document.querySelectorAll('#tabCheckboxes input:checked')
    ).map((i) => i.value);
    const members = Array.from(
      document.querySelectorAll('#memberCheckboxes input:checked')
    ).map((i) => i.value);

    const errBox = document.getElementById('groupModalError');
    errBox.classList.add('hidden');

    let resp;
    if (mode === 'create') {
      resp = await fetch('/admin/api/groups', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, members, allowed_tabs }),
      });
    } else {
      resp = await fetch(`/admin/api/groups/${encodeURIComponent(origName)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ members, allowed_tabs }),
      });
    }
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      errBox.textContent = body.error || 'Save failed.';
      errBox.classList.remove('hidden');
      return;
    }
    closeGroupModal();
    await loadGroups();
  }

  document.getElementById('btnNewGroup').addEventListener('click', () => openGroupModal(null));
  document.getElementById('groupModalClose').addEventListener('click', closeGroupModal);
  document.getElementById('groupModalCancel').addEventListener('click', closeGroupModal);
  document.getElementById('groupModalSave').addEventListener('click', saveGroup);

  // ── Users ──────────────────────────────────────────────────────────────────
  function renderUsers() {
    const tbody = document.getElementById('usersTbody');
    tbody.innerHTML = '';
    state.users.forEach((u) => {
      const tr = el('tr', {});
      tr.appendChild(el('td', { text: u.username }));
      tr.appendChild(el('td', { text: u.role }));
      tbody.appendChild(tr);
    });
  }

  async function loadUsers() {
    const resp = await fetch('/admin/api/users');
    state.users = await resp.json();
    renderUsers();
  }

  // ── Logs ───────────────────────────────────────────────────────────────────
  async function loadLogLevels() {
    const resp = await fetch('/admin/api/logs?limit=1');
    const body = await resp.json();
    const select = document.getElementById('logLevelSelect');
    select.innerHTML = '';
    body.levels.forEach((lvl) => {
      const opt = el('option', { value: lvl, text: lvl });
      if (lvl === body.current_level) opt.selected = true;
      select.appendChild(opt);
    });
    document.getElementById('logCurrentLevel').textContent = body.current_level;
  }

  async function loadLogs() {
    const resp = await fetch('/admin/api/logs?limit=200');
    const body = await resp.json();
    document.getElementById('logCurrentLevel').textContent = body.current_level;
    document.getElementById('logCount').textContent = body.count;
    const container = document.getElementById('logContainer');
    container.innerHTML = '';
    body.entries.slice().reverse().forEach((entry) => {
      const line = el('div', {
        class: 'log-line',
        text: `[${entry.ts}] ${entry.level} ${entry.component}: ${entry.message}`,
      });
      container.appendChild(line);
    });
  }

  document.getElementById('btnSetLevel').addEventListener('click', async () => {
    const level = document.getElementById('logLevelSelect').value;
    await fetch('/admin/api/logs/level', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ level }),
    });
    await loadLogs();
  });
  document.getElementById('btnRefreshLogs').addEventListener('click', loadLogs);
  document.getElementById('btnClearLogs').addEventListener('click', async () => {
    if (!confirm('Clear the log buffer?')) return;
    await fetch('/admin/api/logs', { method: 'DELETE' });
    await loadLogs();
  });

  // ── Init ───────────────────────────────────────────────────────────────────
  async function init() {
    const tabsResp = await fetch('/admin/api/tabs');
    state.tabs = await tabsResp.json();
    await loadUsers();
    await loadGroups();
    await loadLogLevels();
  }

  init();
})();
```

- [ ] **Step 6: Register the admin blueprint**

In `app/__init__.py`, change:
```python
    "app.routes.log_search_routes",
    # "app.routes.admin_routes",      ← added in Task 12
]
```
to:
```python
    "app.routes.log_search_routes",
    "app.routes.admin_routes",
]
```

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run pytest tests/test_admin_routes.py -v`
Expected: PASS (7 tests)

Run: `uv run pytest -v`
Expected: all tests from Tasks 1–12 PASS.

- [ ] **Step 8: Commit**

```bash
git add app/routes/admin_routes.py app/templates/admin.html app/static/js/admin.js app/__init__.py tests/test_admin_routes.py
git commit -m "Add Admin tab: Groups CRUD, Users list, Logs viewer"
```

---

### Task 13: Docker packaging

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.dockerignore`

**Interfaces:**
- Consumes: `pyproject.toml`/`uv.lock` (Task 1), `wsgi.py` (Task 9).
- Produces: a buildable image `4tlog:latest` exposing port `8100`, running `gunicorn ... wsgi:app`.

- [ ] **Step 1: Write `.dockerignore`**

```
.venv/
__pycache__/
*.pyc
.git/
.pytest_cache/
.ruff_cache/
docs/
tests/
users.json
groups.json
.env
certs/
```

- [ ] **Step 2: Write `Dockerfile`**

```dockerfile
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./

RUN uv sync --extra prod --no-dev

ENV PATH="/app/.venv/bin:$PATH"

COPY wsgi.py manage_users.py ./
COPY app/ app/

RUN useradd --system --no-create-home --shell /sbin/nologin appuser \
    && mkdir -p /app/certs \
    && chown -R appuser:appuser /app

ENV HOME=/tmp
USER appuser

EXPOSE 8100

CMD ["gunicorn", \
     "--workers", "2", \
     "--threads", "4", \
     "--worker-class", "gthread", \
     "--bind", "0.0.0.0:8100", \
     "--timeout", "120", \
     "--worker-tmp-dir", "/dev/shm", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "wsgi:app"]
```

This omits the `--certfile`/`--keyfile` flags from 4thealth's Dockerfile since TLS termination for the container path is expected to happen at a reverse proxy in front of it; `docker-compose.yml`'s healthcheck below targets plain HTTP accordingly. (If TLS-inside-container is wanted later, add `certs/` bind mount + cert/key flags — not needed for Phase 1.)

- [ ] **Step 3: Write `docker-compose.yml`**

```yaml
services:
  app:
    build: .
    image: 4tlog:latest
    container_name: 4tlog
    restart: unless-stopped
    ports:
      - "8100:8100"
    env_file:
      - .env
    volumes:
      - ./users.json:/app/users.json:rw
      - ./groups.json:/app/groups.json:rw
    healthcheck:
      test: ["CMD", "python3", "-c",
             "import urllib.request; urllib.request.urlopen('http://localhost:8100/login', timeout=5)"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
```

- [ ] **Step 4: Build and smoke-test the image**

Run: `cd /Users/alanw/code/github/web/4tlog && docker build -t 4tlog:latest .`
Expected: image builds successfully.

Create a throwaway `users.json`/`groups.json`/`.env` for the smoke test:
```bash
echo '{}' > /tmp/4tlog-smoke-users.json
echo '{}' > /tmp/4tlog-smoke-groups.json
printf 'SECRET_KEY=%s\n' "$(openssl rand -hex 32)" > /tmp/4tlog-smoke.env
docker run --rm -d --name 4tlog-smoke -p 18100:8100 \
  --env-file /tmp/4tlog-smoke.env \
  -v /tmp/4tlog-smoke-users.json:/app/users.json \
  -v /tmp/4tlog-smoke-groups.json:/app/groups.json \
  4tlog:latest
sleep 3
curl -sf http://localhost:18100/login | grep -q "Password" && echo "OK"
docker stop 4tlog-smoke
```
Expected: prints `OK`.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile docker-compose.yml .dockerignore
git commit -m "Add Docker packaging for 4tlog"
```

---

### Task 14: RHEL bare-metal deployment doc and README

**Files:**
- Create: `docs/deployment.md`
- Modify: `readme.md` (replace the existing repo-root readme's content to describe the web app; the old Ansible-focused content moves into a "Legacy Ansible scaffold" section pointing at `ansible/readme.md`)

**Interfaces:** None (documentation only).

- [ ] **Step 1: Write `docs/deployment.md`**

```markdown
# RHEL Bare-Metal Deployment

This covers running 4tlog directly on a RHEL/Rocky/AlmaLinux host with
Gunicorn behind Nginx, managed by systemd — the alternative to the Docker
path in `container.md`.

## 1. System packages

```bash
sudo dnf install -y python3.12 python3.12-venv nginx git
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## 2. Application user and directory

```bash
sudo useradd --system --home-dir /opt/4tlog --shell /sbin/nologin 4tlog
sudo mkdir -p /opt/4tlog
sudo chown 4tlog:4tlog /opt/4tlog
```

Clone the repo into `/opt/4tlog` as the `4tlog` user (or copy a release
tarball), then:

```bash
cd /opt/4tlog
sudo -u 4tlog uv sync --extra prod --no-dev
sudo -u 4tlog cp .env.example .env   # edit SECRET_KEY, etc.
sudo -u 4tlog cp users.example.json users.json
sudo -u 4tlog cp groups.example.json groups.json
sudo -u 4tlog uv run python manage_users.py secret     # paste into .env
sudo -u 4tlog uv run python manage_users.py add admin --role admin
```

## 3. TLS certificates

Terminate TLS at Nginx (recommended) rather than Gunicorn. Obtain a
certificate (e.g. via `certbot --nginx`) or place an internal CA-issued
cert/key at a path Nginx can read.

## 4. systemd unit

`/etc/systemd/system/4tlog.service`:

```ini
[Unit]
Description=4tlog Gunicorn service
After=network.target

[Service]
User=4tlog
Group=4tlog
WorkingDirectory=/opt/4tlog
Environment="PATH=/opt/4tlog/.venv/bin"
ExecStart=/opt/4tlog/.venv/bin/gunicorn \
    --workers 2 --threads 4 --worker-class gthread \
    --bind 127.0.0.1:8100 --timeout 120 \
    --access-logfile - --error-logfile - \
    wsgi:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now 4tlog
sudo systemctl status 4tlog
```

**Note on the `gthread` worker class:** later phases add a background health
polling thread. `sync` workers fork child processes and background threads
from the parent do not transfer — always use `--worker-class gthread`, even
though Phase 1 has no background threads yet.

## 5. Nginx reverse proxy

`/etc/nginx/conf.d/4tlog.conf`:

```nginx
server {
    listen 443 ssl;
    server_name 4tlog.example.internal;

    ssl_certificate     /etc/pki/tls/certs/4tlog.crt;
    ssl_certificate_key /etc/pki/tls/private/4tlog.key;

    location / {
        proxy_pass http://127.0.0.1:8100;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}

server {
    listen 80;
    server_name 4tlog.example.internal;
    return 301 https://$host$request_uri;
}
```

Set `TRUSTED_PROXY_COUNT=1` in `.env` so Flask trusts Nginx's
`X-Forwarded-*` headers for HSTS and client-IP-based rate limiting.

```bash
sudo systemctl enable --now nginx
sudo nginx -t && sudo systemctl reload nginx
```

## 6. Firewalld

```bash
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --reload
```

## 7. SELinux

If SELinux is enforcing and Nginx refuses to proxy to Gunicorn:

```bash
sudo setsebool -P httpd_can_network_connect 1
```

## 8. Verify

```bash
curl -sf https://4tlog.example.internal/login | grep -q Password && echo OK
```
```

- [ ] **Step 2: Update `readme.md`**

Read the current `readme.md` first:

Run: `cat readme.md`

Then rewrite it to describe the web app as the primary interface, keeping a short pointer to the legacy Ansible scaffold. Use this structure (fill in based on what Step 2's `cat` showed, keeping any content worth preserving):

```markdown
# 4tlog

A web dashboard for monitoring FortiAnalyzer health and searching FortiAnalyzer
traffic/event logs by source/destination IP, port, and time window, with
CSV/JSON/PDF export.

See [CLAUDE.md](CLAUDE.md) for architecture notes and
[docs/superpowers/specs/2026-07-24-web-app-design.md](docs/superpowers/specs/2026-07-24-web-app-design.md)
for the full design.

## Quick start (development)

```bash
uv sync
cp .env.example .env               # set SECRET_KEY (uv run python manage_users.py secret)
cp users.example.json users.json
cp groups.example.json groups.json
uv run python manage_users.py add admin --role admin
uv run python wsgi.py              # http://localhost:5000 (or https://localhost:5443 with certs/)
```

## Deployment

- Docker: see [container.md](container.md) *(to be added alongside Docker packaging)*
- RHEL bare-metal: see [docs/deployment.md](docs/deployment.md)

## Legacy Ansible scaffold

The original proof-of-concept for FAZ log search was an Ansible playbook.
It has been superseded by the web app's `app/faz_client.py` (Phase 2) but
remains in the repo for reference — see [ansible/readme.md](ansible/readme.md).
```

- [ ] **Step 3: Commit**

```bash
git add docs/deployment.md readme.md
git commit -m "Add RHEL deployment guide and update project README"
```

---

## End-of-phase verification

- [ ] Run the full test suite one more time: `uv run pytest -v` — expect all tests across Tasks 1–12 passing, zero failures.
- [ ] Manually walk the golden path: `uv run python wsgi.py`, browse to the app, log in as the admin account created in Task 6/14, confirm Dashboard and Log Search placeholder pages render, confirm Admin → Groups CRUD and Logs viewer work, log out.
- [ ] Confirm `docker build -t 4tlog:latest .` succeeds and the container smoke test from Task 13 Step 4 passes.
