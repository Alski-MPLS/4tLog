import time
import json
import pytest
from flask import Flask, session, jsonify


@pytest.fixture
def app(tmp_path, monkeypatch):
    import app.auth as auth_mod
    import app.groups as groups_mod

    # Create test data files
    users_file = tmp_path / "users.json"
    groups_file = tmp_path / "groups.json"

    users_data = {
        "alice": {"role": "viewer"},
        "bob": {"role": "viewer"},
        "admin_user": {"role": "admin"},
    }
    users_file.write_text(json.dumps(users_data))

    groups_data = {
        "viewers": {
            "members": ["alice"],
            "allowed_tabs": ["dashboard"],
        }
    }
    groups_file.write_text(json.dumps(groups_data))

    monkeypatch.setattr(auth_mod, "USERS_FILE", users_file)
    monkeypatch.setattr(groups_mod, "GROUPS_FILE", groups_file)
    groups_mod.KNOWN_TABS = {"dashboard": "Dashboard"}

    flask_app = Flask(__name__)
    flask_app.config["SECRET_KEY"] = "test"
    flask_app.config["SESSION_ABSOLUTE_LIFETIME"] = 36000

    from app.decorators import login_required, tab_required, admin_required
    from flask import Blueprint

    # Create auth blueprint to provide auth.login endpoint
    auth_bp = Blueprint("auth", __name__)

    @auth_bp.route("/login")
    def login():
        return "login page"

    flask_app.register_blueprint(auth_bp)

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
    # Use admin_user when role is admin (unless explicitly overridden)
    if username == "alice" and role == "admin":
        username = "admin_user"
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
