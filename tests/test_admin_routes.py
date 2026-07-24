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
    client.get("/login")
    with client.session_transaction() as sess:
        csrf = sess.get("_csrf_token", "")
    client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": csrf},
    )


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
        "/admin/api/logs/level",
        json={"level": "DEBUG"},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 200
    assert resp.get_json()["current_level"] == "DEBUG"

    resp = client.delete("/admin/api/logs", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200


def test_admin_api_blocked_without_csrf(client):
    _login(client, "admin1")
    resp = client.post("/admin/api/groups", json={"name": "x", "allowed_tabs": []})
    assert resp.status_code == 400
