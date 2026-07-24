# tests/test_tab_routes.py
import os

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
    client.get("/login")
    with client.session_transaction() as sess:
        csrf = sess.get("_csrf_token", "")
    client.post("/login", data={"username": username, "password": password, "csrf_token": csrf})


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


def test_viewer_nav_has_no_admin_link_even_if_granted(client):
    # Defense in depth: even if "admin" somehow ends up in a viewer's
    # allowed_tabs (e.g. via a mis-set group), the nav must not render an
    # Admin link for them — only current_role == 'admin' controls that.
    _login(client)
    with client.session_transaction() as sess:
        sess["allowed_tabs"] = ["dashboard", "admin"]
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"nav-link-admin" not in resp.data


def test_admin_nav_has_exactly_one_admin_link(client, app, tmp_path):
    import app.auth as auth_mod

    auth_mod.add_user("admin1", "Str0ng!Passw0rd", role="admin")
    client.get("/login")
    with client.session_transaction() as sess:
        csrf = sess.get("_csrf_token", "")
    client.post(
        "/login",
        data={"username": "admin1", "password": "Str0ng!Passw0rd", "csrf_token": csrf},
    )
    resp = client.get("/admin/")
    assert resp.status_code == 200
    assert resp.data.count(b"nav-link-admin") == 1
